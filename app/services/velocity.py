"""
VelocityService — Redis-backed sliding window transaction frequency checks.

Detects abnormal transaction bursts for a given user, IP address, or device
within a configurable time window using Redis sorted sets.  Also detects
country-change anomalies and spending-pattern spikes.
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
VELOCITY_DEVICE_SCORE = 0.55
VELOCITY_COUNTRY_CHANGE_SCORE = 0.40
VELOCITY_AMOUNT_SPIKE_SCORE = 0.45


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

            user_velocity = await self._check_user_velocity(redis, transaction)
            ip_velocity = await self._check_ip_velocity(redis, transaction)
            device_velocity = await self._check_device_velocity(redis, transaction)

            # Use one primary burst dimension to avoid over-penalizing the same event.
            primary_velocity: tuple[float, str | None] = (0.0, None)
            if user_velocity[1] is not None:
                primary_velocity = user_velocity
            elif device_velocity[1] is not None:
                primary_velocity = device_velocity
            elif ip_velocity[1] is not None:
                primary_velocity = ip_velocity

            checks = [
                primary_velocity,
                await self._check_country_change(redis, transaction),
                await self._check_amount_spike(redis, transaction),
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
        if count > settings.VELOCITY_MAX_TRANSACTIONS_USER:
            return VELOCITY_USER_SCORE, "user_velocity"
        return 0.0, None

    async def _check_ip_velocity(
        self, redis: Redis, transaction: TransactionRequest
    ) -> tuple[float, str | None]:
        """Check transaction frequency for a specific IP address within the sliding window."""
        key = f"velocity:ip:{transaction.ip_address}"
        count = await self._sliding_window_count(redis, key, transaction)
        if count > settings.VELOCITY_MAX_TRANSACTIONS_IP:
            return VELOCITY_IP_SCORE, "ip_velocity"
        return 0.0, None

    async def _check_device_velocity(
        self, redis: Redis, transaction: TransactionRequest
    ) -> tuple[float, str | None]:
        """Check transaction frequency for a specific device within the sliding window."""
        key = f"velocity:device:{transaction.device_id}"
        count = await self._sliding_window_count(redis, key, transaction)
        if count > settings.VELOCITY_MAX_TRANSACTIONS_DEVICE:
            return VELOCITY_DEVICE_SCORE, "device_velocity"
        return 0.0, None

    async def _check_country_change(
        self, redis: Redis, transaction: TransactionRequest
    ) -> tuple[float, str | None]:
        """Detect when a user transacts from a different country than their last seen."""
        key = f"user:country:{transaction.user_id}"
        last_country = await redis.get(key)

        # Always update the last-seen country (with TTL)
        await redis.set(
            key,
            transaction.country,
            ex=settings.VELOCITY_COUNTRY_CACHE_TTL_SECONDS,
        )

        if last_country is not None and last_country != transaction.country:
            return VELOCITY_COUNTRY_CHANGE_SCORE, "country_change"
        return 0.0, None

    async def _check_amount_spike(
        self, redis: Redis, transaction: TransactionRequest
    ) -> tuple[float, str | None]:
        """Flag when current amount exceeds N× the user's recent average."""
        key = f"amounts:user:{transaction.user_id}"
        now = time.time()

        # Retrieve recent amounts (stored as "txn_id:amount" members, score = timestamp)
        entries = await redis.zrange(key, 0, -1)

        # Add current transaction's amount to the history
        member = f"{transaction.transaction_id}:{transaction.amount}"
        await redis.zadd(key, {member: now})
        await redis.expire(key, settings.VELOCITY_WINDOW_SECONDS * 10)

        # Trim to keep only the most recent N entries
        total = await redis.zcard(key)
        if total > settings.VELOCITY_AMOUNT_HISTORY_SIZE:
            await redis.zremrangebyrank(key, 0, total - settings.VELOCITY_AMOUNT_HISTORY_SIZE - 1)

        # Need at least 2 prior entries to compute a meaningful average
        if len(entries) < 2:
            return 0.0, None

        amounts = []
        for entry in entries:
            parts = entry.rsplit(":", 1)
            if len(parts) == 2:
                try:
                    amounts.append(float(parts[1]))
                except ValueError:
                    continue

        if not amounts:
            return 0.0, None

        mean_amount = sum(amounts) / len(amounts)
        if mean_amount > 0 and transaction.amount > settings.VELOCITY_AMOUNT_SPIKE_MULTIPLIER * mean_amount:
            return VELOCITY_AMOUNT_SPIKE_SCORE, "amount_spike"
        return 0.0, None

    async def _sliding_window_count(
        self, redis: Redis, key: str, transaction: TransactionRequest
    ) -> int:
        """Add transaction to sorted set atomically, prune old entries, and return count."""
        now = time.time()
        window_start = now - settings.VELOCITY_WINDOW_SECONDS

        member = f"{transaction.transaction_id}:{now}"

        # Use a pipeline for atomicity — all 4 operations execute in a single round-trip
        pipe = redis.pipeline(transaction=False)
        pipe.zadd(key, {member: now})
        pipe.zremrangebyscore(key, "-inf", window_start)
        pipe.zcount(key, window_start, "+inf")
        pipe.expire(key, settings.VELOCITY_WINDOW_SECONDS)
        results = await pipe.execute()

        # results[2] is the ZCOUNT result
        return results[2]
