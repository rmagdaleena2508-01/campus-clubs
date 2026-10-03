"""
Recruitment drives replace the Google Form.

A Club Admin sets the rules once on the drive (window, eligibility, seats,
questions). Every application lands in one queue and moves through:

    applied -> shortlisted -> interview -> selected | rejected

Selecting someone makes them a club member in the same transaction.
"""
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit
from app.db import get_db
from app.deps import current_user, optional_user, srm_student
from app.errors import AppError, Conflict, Forbidden, NotFound
from app.models import (
    Application, ApplicationStage, Club, ClubRole, ClubStatus, DriveStatus, Membership,
    MembershipStatus, PlatformSetting, RecruitmentDrive, User,
)
from app.permissions import can, require
from app.redis import get_redis
from app.routers.clubs import get_club
from app.schemas import (
    ApplicationCreate, DriveCreate, DriveOut, MyApplicationOut, ReviewApplicationOut,
    StageChange, validate_answers,
)
from app.security import ratelimit

router = APIRouter(tags=["recruitment"])

DEFAULT_MAX_CLUBS = 5

NEXT_STAGES = {
    ApplicationStage.APPLIED: {"shortlisted", "interview", "selected", "rejected"},
    ApplicationStage.SHORTLISTED: {"interview", "selected", "rejected"},
    ApplicationStage.INTERVIEW: {"selected", "rejected"},
}


def now() -> datetime:
    return datetime.now(timezone.utc)


async def get_drive(db: AsyncSession, drive_id: uuid.UUID, lock: bool = False) -> RecruitmentDrive:
    stmt = select(RecruitmentDrive).where(RecruitmentDrive.id == drive_id)
    if lock:
        stmt = stmt.with_for_update()
    drive = await db.scalar(stmt)
    if drive is None:
        raise NotFound("Recruitment drive not found.")
    return drive


async def max_clubs_per_student(db: AsyncSession) -> int:
    setting = await db.get(PlatformSetting, "max_clubs_per_student")
    return int(setting.value) if setting else DEFAULT_MAX_CLUBS


async def active_club_count(db: AsyncSession, user_id: uuid.UUID) -> int:
    return await db.scalar(select(func.count()).select_from(Membership).where(
        Membership.user_id == user_id, Membership.status == MembershipStatus.ACTIVE
    ))


# ---------------------------------------------------------------------------
# Drives (Club Admin)
# ---------------------------------------------------------------------------
@router.post("/clubs/{club_id}/drives", response_model=DriveOut, status_code=201)
async def create_drive(
    club_id: uuid.UUID,
    data: DriveCreate,
    request: Request,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    await require(db, user, "drive.manage", club_id)
    club = await get_club(db, club_id)
    if club.status != ClubStatus.ACTIVE:
        raise AppError("Only active clubs can recruit.")

    drive = RecruitmentDrive(
        club_id=club_id,
        title=data.title,
        description=data.description,
        status=DriveStatus.DRAFT,
        opens_at=data.opens_at,
        closes_at=data.closes_at,
        seats=data.seats,
        eligibility=data.eligibility.model_dump(),
        form_schema=[q.model_dump() for q in data.form_schema],
        created_by=user.id,
    )
    db.add(drive)
    await db.flush()
    await audit.record(db, request, user, "drive.create", "drive", drive.id, club_id, after={"title": drive.title})
    return drive


@router.post("/drives/{drive_id}/open", response_model=DriveOut)
async def open_drive(drive_id: uuid.UUID, request: Request,
                     user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    return await move_drive(db, request, user, drive_id, "open", DriveStatus.DRAFT, DriveStatus.OPEN)


@router.post("/drives/{drive_id}/close", response_model=DriveOut)
async def close_drive(drive_id: uuid.UUID, request: Request,
                      user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    return await move_drive(db, request, user, drive_id, "close", DriveStatus.OPEN, DriveStatus.CLOSED)


async def move_drive(db: AsyncSession, request: Request, user: User, drive_id: uuid.UUID,
                     action: str, from_status: DriveStatus, to_status: DriveStatus) -> RecruitmentDrive:
    drive = await get_drive(db, drive_id, lock=True)
    await require(db, user, "drive.manage", drive.club_id)
    if drive.status != from_status:
        past = "opened" if action == "open" else "closed"
        raise Conflict(f"This drive is {drive.status.value}, so it can't be {past}.")
    drive.status = to_status
    await audit.record(db, request, user, f"drive.{action}", "drive", drive.id, drive.club_id,
                       before={"status": from_status.value}, after={"status": to_status.value})
    return drive


@router.get("/clubs/{club_id}/drives", response_model=list[DriveOut])
async def club_drives(club_id: uuid.UUID, user: User | None = Depends(optional_user),
                      db: AsyncSession = Depends(get_db)):
    stmt = select(RecruitmentDrive).where(RecruitmentDrive.club_id == club_id)
    if user is None or not await can(db, user, "drive.manage", club_id):
        stmt = stmt.where(RecruitmentDrive.status == DriveStatus.OPEN)
    return (await db.scalars(stmt.order_by(RecruitmentDrive.opens_at.desc()))).all()


# ---------------------------------------------------------------------------
# Applying (student)
# ---------------------------------------------------------------------------
@router.post("/drives/{drive_id}/applications", response_model=MyApplicationOut, status_code=201)
async def apply(
    drive_id: uuid.UUID,
    data: ApplicationCreate,
    user: User = Depends(srm_student),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
):
    await ratelimit.hit(redis, f"apply:{user.id}", limit=10, window_seconds=3600)
    drive = await get_drive(db, drive_id)
    club = await get_club(db, drive.club_id)

    if club.status != ClubStatus.ACTIVE or drive.status != DriveStatus.OPEN:
        raise AppError("This drive is not taking applications.")
    if not drive.opens_at <= now() <= drive.closes_at:
        raise AppError("Applications are closed for this drive.")

    profile = user.student_profile
    years, departments = drive.eligibility.get("years") or [], drive.eligibility.get("department_ids") or []
    if (years and profile.year_of_study not in years) or (departments and profile.department_id not in departments):
        raise Forbidden("You are not eligible for this drive.")

    already_member = await db.scalar(select(Membership.id).where(
        Membership.club_id == club.id, Membership.user_id == user.id,
        Membership.status == MembershipStatus.ACTIVE,
    ))
    if already_member is not None:
        raise Conflict("You are already a member of this club.")
    if await active_club_count(db, user.id) >= await max_clubs_per_student(db):
        raise AppError("You have reached the most clubs one student can join.")

    try:
        answers = validate_answers(drive.form_schema, data.answers)
    except ValueError as e:
        raise AppError(str(e), 422)

    application = Application(drive_id=drive.id, user_id=user.id, answers=answers, stage=ApplicationStage.APPLIED)
    db.add(application)
    try:
        await db.flush()
    except IntegrityError:
        raise Conflict("You have already applied to this drive.")
    await db.refresh(application)
    return application


@router.get("/me/applications", response_model=list[MyApplicationOut])
async def my_applications(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    stmt = select(Application).where(Application.user_id == user.id).order_by(Application.created_at.desc())
    return (await db.scalars(stmt)).all()


@router.post("/applications/{application_id}/withdraw", response_model=MyApplicationOut)
async def withdraw(application_id: uuid.UUID, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    application = await db.get(Application, application_id, with_for_update=True)
    if application is None or application.user_id != user.id:
        raise NotFound("Application not found.")
    if application.stage not in NEXT_STAGES:
        raise Conflict("This application is already decided.")
    application.stage = ApplicationStage.WITHDRAWN
    application.updated_at = now()
    return application


# ---------------------------------------------------------------------------
# Review queue (Club Admin)
# ---------------------------------------------------------------------------
@router.get("/drives/{drive_id}/applications", response_model=list[ReviewApplicationOut])
async def review_queue(
    drive_id: uuid.UUID,
    stage: ApplicationStage | None = None,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    drive = await get_drive(db, drive_id)
    await require(db, user, "application.review", drive.club_id)

    stmt = (
        select(Application, User.full_name, User.handle)
        .join(User, User.id == Application.user_id)
        .where(Application.drive_id == drive_id)
        .order_by(Application.created_at)
    )
    if stage is not None:
        stmt = stmt.where(Application.stage == stage)
    rows = await db.execute(stmt)
    return [
        ReviewApplicationOut(
            **MyApplicationOut.model_validate(a).model_dump(),
            user_id=a.user_id, applicant_name=name, applicant_handle=handle, internal_note=a.internal_note,
        )
        for a, name, handle in rows
    ]


@router.patch("/applications/{application_id}", response_model=ReviewApplicationOut)
async def move_application(
    application_id: uuid.UUID,
    data: StageChange,
    request: Request,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    application = await db.get(Application, application_id, with_for_update=True)
    if application is None:
        raise NotFound("Application not found.")
    # lock the drive too, so two admins can't both fill the last seat
    drive = await get_drive(db, application.drive_id, lock=True)
    await require(db, user, "application.review", drive.club_id)

    if data.stage not in NEXT_STAGES.get(application.stage, set()):
        raise Conflict(f"Can't move an application from {application.stage.value} to {data.stage}.")

    if data.stage == "selected":
        if drive.seats is not None:
            selected = await db.scalar(select(func.count()).select_from(Application).where(
                Application.drive_id == drive.id, Application.stage == ApplicationStage.SELECTED
            ))
            if selected >= drive.seats:
                raise Conflict("All seats in this drive are filled.")
        if await active_club_count(db, application.user_id) >= await max_clubs_per_student(db):
            raise AppError("This student has already joined the most clubs allowed.")
        await add_member(db, drive.club_id, application.user_id)

    before = {"stage": application.stage.value}
    application.stage = ApplicationStage(data.stage)
    if data.internal_note is not None:
        application.internal_note = data.internal_note
    application.decided_by = user.id
    application.decided_at = application.updated_at = now()
    await audit.record(db, request, user, "application.move", "application", application.id, drive.club_id,
                       before=before, after={"stage": data.stage})

    applicant = await db.get(User, application.user_id)
    return ReviewApplicationOut(
        **MyApplicationOut.model_validate(application).model_dump(),
        user_id=application.user_id, applicant_name=applicant.full_name,
        applicant_handle=applicant.handle, internal_note=application.internal_note,
    )


async def add_member(db: AsyncSession, club_id: uuid.UUID, user_id: uuid.UUID) -> None:
    """Make the user an active member, bringing back an old membership if they left before."""
    membership = await db.scalar(select(Membership).where(
        Membership.club_id == club_id, Membership.user_id == user_id
    ).with_for_update())
    if membership is None:
        db.add(Membership(club_id=club_id, user_id=user_id, role=ClubRole.MEMBER, status=MembershipStatus.ACTIVE))
    elif membership.status != MembershipStatus.ACTIVE:
        membership.status = MembershipStatus.ACTIVE
        membership.role = ClubRole.MEMBER
        membership.title = None
        membership.joined_at = now()
        membership.ended_at = None
