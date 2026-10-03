from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import current_user
from app.errors import AppError, Forbidden
from app.models import Campus, Department, StudentProfile, User, UserKind
from app.schemas import Onboarding, SessionOut
from app.users import me_out

router = APIRouter(prefix="/me", tags=["me"])


@router.get("", response_model=SessionOut)
async def get_me(request: Request, user: User = Depends(current_user)):
    # The frontend calls this on page load to get the user and a CSRF token for writes
    return SessionOut(user=me_out(user), csrf_token=request.state.csrf)


@router.put("/onboarding", response_model=SessionOut)
async def onboarding(
    data: Onboarding,
    request: Request,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    if user.kind != UserKind.COLLEGE:
        raise Forbidden("Only SRM students set a campus and department.")
    if await db.get(Campus, data.campus_id) is None or await db.get(Department, data.department_id) is None:
        raise AppError("Pick a valid campus and department.", 422)

    clash = await db.scalar(select(StudentProfile.user_id).where(
        StudentProfile.register_no == data.register_no.upper(), StudentProfile.user_id != user.id
    ))
    if clash is not None:
        raise AppError("This register number is already linked to another account.", 409)

    profile = user.student_profile
    if profile is None:
        profile = StudentProfile(user_id=user.id)
        db.add(profile)
        user.student_profile = profile
    profile.campus_id = data.campus_id
    profile.department_id = data.department_id
    profile.year_of_study = data.year_of_study
    profile.register_no = data.register_no.upper()
    return SessionOut(user=me_out(user), csrf_token=request.state.csrf)
