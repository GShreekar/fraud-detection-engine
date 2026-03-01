"""
Redis client — async connection setup for velocity checks.

Provides connect_redis(), close_redis(), and get_redis() for use
as a FastAPI lifespan hook and dependency.
"""

import logging

from redis.asyncio import Redis

from app.config import settings

logger = logging.getLogger(__name__)

redis_client: Redis | None = None


async def connect_redis() -> None:
    """Create the global async Redis connection (called at startup)."""
    global redis_client
    redis_client = Redis(
        host=settings.REDIS_HOST,
        port=settings.REDIS_PORT,
        decode_responses=True,
    )
    logger.info("redis_connected", extra={"host": settings.REDIS_HOST, "port": settings.REDIS_PORT})


async def close_redis() -> None:
    """Close the global async Redis connection (called at shutdown)."""
    global redis_client
    if redis_client is not None:
        await redis_client.close()
        redis_client = None
        logger.info("redis_disconnected")


def get_redis() -> Redis | None:
    """Return the current Redis client instance."""
    return redis_client
