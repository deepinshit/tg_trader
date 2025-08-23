# /backend/redis/functions.py

from typing import AsyncGenerator

from backend.redis.store import RedisStore

async def get_redis_store() -> AsyncGenerator[RedisStore, None]:
    """
    Provides a Redis connection per request using context manager.
    Ensures proper connection cleanup after request lifecycle.
    """
    async with RedisStore() as store:
        yield store