import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit
from app.db import get_db
from app.deps import current_user, optional_user, srm_student
from app.errors import AppError, Conflict, NotFound
from app.models import Club, ClubRole, ClubStatus, Membership, MembershipStatus, User
from app.permissions import require
from app.schemas import ClubOut, ClubRequest, ClubReview, MemberOut, RoleChange

router = APIRouter(prefix="/clubs", tags=["clubs"])

MAX_PENDING_REQUESTS = 2


async def get_club(db: AsyncSession, club_id: uuid.UUID) -> Club:
    club = await db.get(Club, club_id)
    if club is None:
        raise NotFound("Club not found.")
    return club


@router.post("", response_model=ClubOut, status_code=201)
async def request_club(
    data: ClubRequest,
    request: Request,
    user: User = Depends(srm_student),
    db: AsyncSession = Depends(get_db),
):
    pending = await db.scalar(select(func.count()).select_from(Club).where(
        Club.requested_by == user.id, Club.status == ClubStatus.PENDING
    ))
    if pending >= MAX_PENDING_REQUESTS:
        raise AppError("You already have club requests waiting for review.", 429)
    if await db.scalar(select(Club.id).where(Club.slug == data.slug)) is not None:
        raise Conflict("That club link is taken. Try another.")

    club = Club(
        **data.model_dump(exclude={"links"}),
        links=[link.model_dump(mode="json") for link in data.links],
        campus_id=user.student_profile.campus_id,
        status=ClubStatus.PENDING,
        requested_by=user.id,
    )
    db.add(club)
    await db.flush()
    await audit.record(db, request, user, "club.request", "club", club.id, club.id,
                       after={"name": club.name, "slug": club.slug})
    await db.refresh(club)
    return club


@router.get("", response_model=list[ClubOut])
async def directory(
    db: AsyncSession = Depends(get_db),
    campus_id: int | None = None,
    department_id: int | None = None,
    category: str | None = None,
    q: str | None = Query(default=None, max_length=60),
    limit: int = Query(default=50, le=100),
    offset: int = Query(default=0, ge=0),
):
    """Public club directory: active clubs only."""
    stmt = select(Club).where(Club.status == ClubStatus.ACTIVE)
    if campus_id is not None:
        stmt = stmt.where(Club.campus_id == campus_id)
    if department_id is not None:
        stmt = stmt.where(Club.department_id == department_id)
    if category:
        stmt = stmt.where(Club.category == category)
    if q:
        like = f"%{q.replace('%', '').replace('_', '')}%"
        stmt = stmt.where(or_(Club.name.ilike(like), Club.tagline.ilike(like)))
    stmt = stmt.order_by(Club.name).limit(limit).offset(offset)
    return (await db.scalars(stmt)).all()


@router.get("/review-queue", response_model=list[ClubOut])
async def review_queue(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    await require(db, user, "club.review")
    stmt = select(Club).where(Club.status == ClubStatus.PENDING).order_by(Club.created_at)
    return (await db.scalars(stmt)).all()


@router.get("/{slug}", response_model=ClubOut)
async def club_page(slug: str, user: User | None = Depends(optional_user), db: AsyncSession = Depends(get_db)):
    club = await db.scalar(select(Club).where(Club.slug == slug.lower()))
    visible = club is not None and (
        club.status == ClubStatus.ACTIVE
        or (user is not None and (user.id == club.requested_by or user.is_platform_owner))
    )
    if not visible:
        raise NotFound("Club not found.")
    return club


@router.post("/{club_id}/review", response_model=ClubOut)
async def review_club(
    club_id: uuid.UUID,
    data: ClubReview,
    request: Request,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    await require(db, user, "club.review")
    club = await get_club(db, club_id)
    if club.status != ClubStatus.PENDING:
        raise Conflict("This club has already been reviewed.")

    club.status = ClubStatus.ACTIVE if data.decision == "approve" else ClubStatus.REJECTED
    club.reviewed_by = user.id
    club.reviewed_at = datetime.now(timezone.utc)
    club.review_note = data.note
    if club.status == ClubStatus.ACTIVE:
        # whoever asked for the club becomes its first Club Admin
        db.add(Membership(club_id=club.id, user_id=club.requested_by, role=ClubRole.ADMIN,
                          title="President", status=MembershipStatus.ACTIVE))

    await audit.record(db, request, user, f"club.{data.decision}", "club", club.id, club.id,
                       after={"status": club.status.value, "note": data.note})
    await db.flush()
    return club


@router.post("/{club_id}/suspend", response_model=ClubOut)
async def suspend_club(club_id: uuid.UUID, request: Request,
                       user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    await require(db, user, "club.suspend")
    club = await get_club(db, club_id)
    before = club.status.value
    club.status = ClubStatus.SUSPENDED
    await audit.record(db, request, user, "club.suspend", "club", club.id, club.id,
                       before={"status": before}, after={"status": "suspended"})
    await db.flush()
    return club


@router.get("/{club_id}/members", response_model=list[MemberOut])
async def members(club_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    await get_club(db, club_id)
    rows = await db.execute(
        select(Membership, User.full_name, User.handle)
        .join(User, User.id == Membership.user_id)
        .where(Membership.club_id == club_id, Membership.status == MembershipStatus.ACTIVE)
        .order_by(Membership.role, User.full_name)
    )
    return [
        MemberOut(user_id=m.user_id, full_name=name, handle=handle, role=m.role, title=m.title, joined_at=m.joined_at)
        for m, name, handle in rows
    ]


@router.put("/{club_id}/members/{user_id}/role", response_model=MemberOut)
async def change_role(
    club_id: uuid.UUID,
    user_id: uuid.UUID,
    data: RoleChange,
    request: Request,
    actor: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    await require(db, actor, "club.manage_roles", club_id)
    # Lock the club row so role changes in one club happen one at a time
    # (two admins can't demote each other at the same moment)
    await db.execute(select(Club.id).where(Club.id == club_id).with_for_update())
    membership = await db.scalar(select(Membership).where(
        Membership.club_id == club_id, Membership.user_id == user_id,
        Membership.status == MembershipStatus.ACTIVE,
    ))
    if membership is None:
        raise NotFound("This person is not a member of the club.")

    if membership.role == ClubRole.ADMIN and data.role != ClubRole.ADMIN:
        admins = await db.scalar(select(func.count()).select_from(Membership).where(
            Membership.club_id == club_id, Membership.role == ClubRole.ADMIN,
            Membership.status == MembershipStatus.ACTIVE,
        ))
        if admins <= 1:
            raise AppError("A club needs at least one admin. Make someone else admin first.")

    before = {"role": membership.role.value, "title": membership.title}
    membership.role = data.role
    membership.title = data.title
    await audit.record(db, request, actor, "member.role", "membership", membership.id, club_id,
                       before=before, after={"role": data.role.value, "title": data.title})
    member = await db.get(User, user_id)
    return MemberOut(user_id=user_id, full_name=member.full_name, handle=member.handle,
                     role=membership.role, title=membership.title, joined_at=membership.joined_at)
