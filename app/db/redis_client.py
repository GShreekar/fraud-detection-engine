"""
Redis client — async connection setup for velocity checks.

Provides connect_redis(), close_redis(), and get_redis() for use
as a FastAPI lifespan hook and dependency.
"""

import logging

from redis.asyncio import ConnectionPool, Redis

from app.config import settings

logger = logging.getLogger(__name__)

redis_client: Redis | None = None


async def connect_redis() -> None:
    """Create the global async Redis connection and verify it (called at startup)."""
    global redis_client
    pool = ConnectionPool(
        host=settings.REDIS_HOST,
        port=settings.REDIS_PORT,
        password=settings.REDIS_PASSWORD,
        db=settings.REDIS_DB,
        max_connections=settings.REDIS_MAX_CONNECTIONS,
        socket_timeout=settings.REDIS_SOCKET_TIMEOUT,
        decode_responses=True,
    )
    redis_client = Redis(connection_pool=pool)
    try:
        await redis_client.ping()
        logger.info(
            "redis_connected",
            extra={"host": settings.REDIS_HOST, "port": settings.REDIS_PORT},
        )
    except Exception as exc:
        logger.warning(
            "redis_connectivity_check_failed",
            extra={
                "host": settings.REDIS_HOST,
                "port": settings.REDIS_PORT,
                "error": str(exc),
            },
        )


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
