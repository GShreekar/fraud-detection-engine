"""
Redis client — connection setup for velocity checks and caching.

TODO: initialize async Redis connection using config settings.
"""

# TODO: from redis.asyncio import Redis
# TODO: from app.config import settings

# redis_client: Redis | None = None

# async def get_redis() -> Redis:
#     global redis_client
#     if redis_client is None:
#         redis_client = Redis(host=settings.REDIS_HOST, port=settings.REDIS_PORT)
#     return redis_client
