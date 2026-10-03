"""
One-time email codes for outside participants.

Only a hash of the code is stored, it expires after OTP_TTL_SECONDS, and it is
burned after OTP_MAX_ATTEMPTS wrong guesses so it can't be brute-forced.
"""
import hashlib
import hmac
import json
import secrets

from redis.asyncio import Redis

from app.config import settings
from app.errors import AppError


def _key(email: str) -> str:
    return f"otp:{email}"


def _hash(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


async def issue_code(redis: Redis, email: str) -> str:
    code = f"{secrets.randbelow(1_000_000):06d}"
    await redis.set(
        _key(email),
        json.dumps({"hash": _hash(code), "attempts": 0}),
        ex=settings.OTP_TTL_SECONDS,
    )
    return code


async def check_code(redis: Redis, email: str, code: str) -> None:
    raw = await redis.get(_key(email))
    if raw is None:
        raise AppError("This code has expired. Ask for a new one.")
    data = json.loads(raw)

    if not hmac.compare_digest(data["hash"], _hash(code)):
        data["attempts"] += 1
        if data["attempts"] >= settings.OTP_MAX_ATTEMPTS:
            await redis.delete(_key(email))
            raise AppError("Too many wrong codes. Ask for a new one.")
        ttl = await redis.ttl(_key(email))
        await redis.set(_key(email), json.dumps(data), ex=max(ttl, 1))
        raise AppError("That code is not right.")

    await redis.delete(_key(email))
