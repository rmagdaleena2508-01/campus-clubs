from fastapi import Depends, Request
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_db
from app.errors import AppError, Forbidden, NotAuthenticated
from app.models import User, UserKind
from app.redis import get_redis
from app.security.sessions import load_session

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


async def optional_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> User | None:
    sid = request.cookies.get(settings.SESSION_COOKIE)
    if not sid:
        return None
    session = await load_session(redis, sid)
    if session is None:
        return None

    # CSRF: a write must echo the token only our own frontend can read
    if request.method not in SAFE_METHODS and request.headers.get("X-CSRF-Token") != session["csrf"]:
        raise Forbidden("Security check failed. Refresh the page and try again.")

    user = await db.scalar(select(User).where(User.id == session["user_id"], User.deleted_at.is_(None)))
    if user is not None:
        request.state.csrf = session["csrf"]
    return user


async def current_user(user: User | None = Depends(optional_user)) -> User:
    if user is None:
        raise NotAuthenticated()
    return user


async def srm_student(user: User = Depends(current_user)) -> User:
    """An @srmist.edu.in user who has finished onboarding (campus, department, year)."""
    if user.kind != UserKind.COLLEGE:
        raise Forbidden("Only SRM students can do this.")
    if user.student_profile is None or not user.student_profile.is_complete:
        raise AppError("Finish setting up your profile first.", 428)
    return user
