"""
Two ways in:
  * SRM students and staff: Google sign-in, restricted to @srmist.edu.in.
  * Outside participants: a 6-digit code sent to their personal email.
"""
from fastapi import APIRouter, Depends, Request, Response
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_db
from app.deps import current_user
from app.errors import AppError
from app.mailer import send_email
from app.models import ExternalProfile, StudentProfile, User, UserKind
from app.redis import get_redis
from app.schemas import EmailCodeRequest, EmailCodeVerify, GoogleSignIn, SessionOut
from app.security import otp, ratelimit
from app.security.google import verify_google_token
from app.security.sessions import (
    clear_session_cookie, create_session, destroy_all_sessions, destroy_session, set_session_cookie
)
from app.users import me_out, unique_handle

router = APIRouter(prefix="/auth", tags=["auth"])


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


async def start_session(redis: Redis, response: Response, user: User) -> SessionOut:
    sid, csrf = await create_session(redis, user.id)
    set_session_cookie(response, sid)
    return SessionOut(user=me_out(user), csrf_token=csrf)


@router.post("/google", response_model=SessionOut)
async def google_sign_in(
    data: GoogleSignIn,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
):
    await ratelimit.hit(redis, f"google:{client_ip(request)}", limit=30, window_seconds=600)
    identity = await verify_google_token(data.id_token)

    user = await db.scalar(select(User).where(User.google_sub == identity.sub))
    if user is None:
        user = await db.scalar(select(User).where(User.email == identity.email))
    if user is None:
        user = User(
            email=identity.email,
            full_name=identity.name,
            handle=await unique_handle(db, identity.email),
            kind=UserKind.COLLEGE,
            google_sub=identity.sub,
        )
        db.add(user)
        await db.flush()
        db.add(StudentProfile(user_id=user.id))
        await db.flush()
        await db.refresh(user, ["student_profile", "external_profile"])
    elif user.deleted_at is not None:
        raise AppError("This account was deleted.", 403)
    elif user.google_sub is None:
        user.google_sub = identity.sub

    return await start_session(redis, response, user)


@router.post("/email/start")
async def email_code_start(
    data: EmailCodeRequest,
    request: Request,
    redis: Redis = Depends(get_redis),
):
    email = data.email.lower()
    if email.endswith("@" + settings.COLLEGE_DOMAIN):
        raise AppError(f"@{settings.COLLEGE_DOMAIN} accounts sign in with Google.")

    await ratelimit.hit(redis, f"otp-ip:{client_ip(request)}", limit=20, window_seconds=3600)
    await ratelimit.hit(redis, f"otp-email:{email}", limit=3, window_seconds=600)

    code = await otp.issue_code(redis, email)
    await send_email(
        email,
        "Your sign-in code",
        f"Your code is {code}. It expires in {settings.OTP_TTL_SECONDS // 60} minutes.",
    )
    return {"message": "We sent a 6-digit code to your email."}


@router.post("/email/verify", response_model=SessionOut)
async def email_code_verify(
    data: EmailCodeVerify,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
):
    email = data.email.lower()
    await ratelimit.hit(redis, f"otp-verify-ip:{client_ip(request)}", limit=30, window_seconds=600)

    user = await db.scalar(select(User).where(User.email == email))
    if user is None and not (data.full_name and data.institution):
        # Ask for name and institution before burning the code
        raise AppError("Tell us your name and college to finish signing up.", 422)

    await otp.check_code(redis, email, data.code)

    if user is None:
        user = User(
            email=email,
            full_name=data.full_name.strip(),
            handle=await unique_handle(db, email),
            kind=UserKind.EXTERNAL,
        )
        db.add(user)
        await db.flush()
        db.add(ExternalProfile(user_id=user.id, institution=data.institution.strip()))
        await db.flush()
        await db.refresh(user, ["student_profile", "external_profile"])
    elif user.deleted_at is not None:
        raise AppError("This account was deleted.", 403)

    return await start_session(redis, response, user)


@router.post("/logout")
async def logout(request: Request, response: Response, redis: Redis = Depends(get_redis),
                 _: User = Depends(current_user)):
    await destroy_session(redis, request.cookies[settings.SESSION_COOKIE])
    clear_session_cookie(response)
    return {"message": "Signed out."}


@router.post("/logout-all")
async def logout_all(response: Response, redis: Redis = Depends(get_redis),
                     user: User = Depends(current_user)):
    await destroy_all_sessions(redis, user.id)
    clear_session_cookie(response)
    return {"message": "Signed out on every device."}
