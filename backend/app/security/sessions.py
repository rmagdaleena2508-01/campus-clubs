"""
Server-side sessions in Redis.

The browser only holds a random session id in an httpOnly cookie, so page
scripts (and any XSS) can never read it. Each session also carries a CSRF
token that the frontend must echo in the X-CSRF-Token header on writes.

    sess:<sid>            -> {"user_id": ..., "csrf": ...}   (TTL, sliding)
    user_sessions:<uid>   -> set of sids, for "log out of all devices"
"""
import json
import secrets
import uuid

from fastapi import Response
from redis.asyncio import Redis

from app.config import settings


def _key(sid: str) -> str:
    return f"sess:{sid}"


def _user_key(user_id: uuid.UUID | str) -> str:
    return f"user_sessions:{user_id}"


async def create_session(redis: Redis, user_id: uuid.UUID) -> tuple[str, str]:
    """Start a fresh session (never reuse an old id, which prevents session fixation)."""
    sid = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(32)
    ttl = settings.SESSION_TTL_SECONDS
    await redis.set(_key(sid), json.dumps({"user_id": str(user_id), "csrf": csrf}), ex=ttl)
    await redis.sadd(_user_key(user_id), sid)
    await redis.expire(_user_key(user_id), ttl)
    return sid, csrf


async def load_session(redis: Redis, sid: str) -> dict | None:
    raw = await redis.get(_key(sid))
    if raw is None:
        return None
    await redis.expire(_key(sid), settings.SESSION_TTL_SECONDS)
    return json.loads(raw)


async def destroy_session(redis: Redis, sid: str) -> None:
    data = await load_session(redis, sid)
    await redis.delete(_key(sid))
    if data:
        await redis.srem(_user_key(data["user_id"]), sid)


async def destroy_all_sessions(redis: Redis, user_id: uuid.UUID) -> None:
    sids = await redis.smembers(_user_key(user_id))
    if sids:
        await redis.delete(*[_key(s) for s in sids])
    await redis.delete(_user_key(user_id))


def set_session_cookie(response: Response, sid: str) -> None:
    response.set_cookie(
        settings.SESSION_COOKIE,
        sid,
        max_age=settings.SESSION_TTL_SECONDS,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(settings.SESSION_COOKIE, path="/")
