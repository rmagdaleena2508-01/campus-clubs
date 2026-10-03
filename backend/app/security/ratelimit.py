from redis.asyncio import Redis

from app.errors import TooManyRequests


async def hit(redis: Redis, bucket: str, limit: int, window_seconds: int) -> None:
    """Fixed-window limiter: allow `limit` hits per `window_seconds` for this bucket."""
    key = f"rl:{bucket}"
    count = await redis.incr(key)
    if count == 1:
        await redis.expire(key, window_seconds)
    if count > limit:
        raise TooManyRequests()
