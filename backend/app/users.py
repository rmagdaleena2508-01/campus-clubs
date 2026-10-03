import re
import secrets

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User, UserKind
from app.schemas import MeOut, StudentProfileOut


async def unique_handle(db: AsyncSession, email: str) -> str:
    """Turn 'ab1234@srmist.edu.in' into an unused public handle like 'ab1234'."""
    base = re.sub(r"[^a-z0-9-]+", "-", email.split("@")[0].lower()).strip("-")[:24]
    if len(base) < 3:
        base = f"user-{base}".strip("-")
    candidate = base
    for _ in range(20):
        taken = await db.scalar(select(User.id).where(User.handle == candidate))
        if taken is None:
            return candidate
        candidate = f"{base}-{secrets.randbelow(10_000)}"
    return f"{base}-{secrets.token_hex(4)}"


def me_out(user: User) -> MeOut:
    profile = user.student_profile
    return MeOut(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        handle=user.handle,
        kind=user.kind,
        is_platform_owner=user.is_platform_owner,
        needs_onboarding=user.kind == UserKind.COLLEGE and (profile is None or not profile.is_complete),
        student_profile=StudentProfileOut.model_validate(profile) if profile else None,
    )
