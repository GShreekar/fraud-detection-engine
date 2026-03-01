"""
VelocityService — Redis-backed sliding window transaction frequency checks.

Detects abnormal transaction bursts for a given user or IP address
within a configurable time window using Redis sorted sets.
"""

import logging
import time

from redis.asyncio import Redis

from app.config import settings
from app.db.redis_client import get_redis
from app.models.transaction import TransactionRequest

logger = logging.getLogger(__name__)

# --- Score contributions per velocity dimension ---
VELOCITY_USER_SCORE = 0.6
VELOCITY_IP_SCORE = 0.5


class VelocityService:
    """Async, Redis-backed sliding window frequency checks."""

    async def evaluate(self, transaction: TransactionRequest) -> tuple[float, list[str]]:
        """Run all velocity dimension checks and return (capped_score, reasons)."""
        try:
            redis = get_redis()
            if redis is None:
                logger.warning(
                    "velocity_redis_unavailable",
                    extra={"transaction_id": transaction.transaction_id},
                )
                return 0.0, []

            checks = [
                await self._check_user_velocity(redis, transaction),
                await self._check_ip_velocity(redis, transaction),
            ]

            total_score = 0.0
            reasons: list[str] = []

            for score, reason in checks:
                total_score += score
                if reason is not None:
                    reasons.append(reason)

            return min(total_score, 1.0), reasons
        except Exception as exc:
            logger.warning(
                "velocity_check_failed",
                extra={"transaction_id": transaction.transaction_id, "error": str(exc)},
            )
            return 0.0, []

    async def _check_user_velocity(
        self, redis: Redis, transaction: TransactionRequest
    ) -> tuple[float, str | None]:
        """Check transaction frequency for a specific user within the sliding window."""
        key = f"velocity:user:{transaction.user_id}"
        count = await self._sliding_window_count(redis, key, transaction)
        if count > settings.VELOCITY_MAX_TRANSACTIONS:
            return VELOCITY_USER_SCORE, "velocity_user_exceeded"
        return 0.0, None

    async def _check_ip_velocity(
        self, redis: Redis, transaction: TransactionRequest
    ) -> tuple[float, str | None]:
        """Check transaction frequency for a specific IP address within the sliding window."""
        key = f"velocity:ip:{transaction.ip_address}"
        count = await self._sliding_window_count(redis, key, transaction)
        if count > settings.VELOCITY_MAX_TRANSACTIONS:
            return VELOCITY_IP_SCORE, "velocity_ip_exceeded"
        return 0.0, None

    async def _sliding_window_count(
        self, redis: Redis, key: str, transaction: TransactionRequest
    ) -> int:
        """Add transaction to sorted set, prune old entries, and return current count."""
        now = time.time()
        window_start = now - settings.VELOCITY_WINDOW_SECONDS

        # Add the current transaction (score = timestamp, member = unique id)
        member = f"{transaction.transaction_id}:{now}"
        await redis.zadd(key, {member: now})

        # Remove entries older than the window
        await redis.zremrangebyscore(key, "-inf", window_start)

        # Count entries within the window
        count = await redis.zcount(key, window_start, "+inf")

        # Set TTL so keys auto-expire
        await redis.expire(key, settings.VELOCITY_WINDOW_SECONDS)

        return count
