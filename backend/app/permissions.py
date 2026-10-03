"""
Every permission decision in the API goes through this module.

Club roles live in the memberships table, never in the session, so promoting
or removing someone takes effect on their very next request.
"""
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import Forbidden
from app.models import ClubRole, Membership, MembershipStatus, User

ROLE_RANK = {ClubRole.MEMBER: 1, ClubRole.CORE: 2, ClubRole.ADMIN: 3}

# action -> the lowest club role allowed to do it
CLUB_ACTIONS: dict[str, ClubRole] = {
    "club.edit": ClubRole.ADMIN,
    "club.manage_roles": ClubRole.ADMIN,
    "drive.manage": ClubRole.ADMIN,
    "application.review": ClubRole.ADMIN,
    "event.manage": ClubRole.CORE,
    "event.approve_external": ClubRole.CORE,
    "event.checkin": ClubRole.CORE,
    "event.publish_results": ClubRole.ADMIN,
    "announcement.post": ClubRole.CORE,
}

# actions only the Platform Owner may take
OWNER_ACTIONS = {"club.review", "club.suspend", "club.transfer", "platform.settings"}


async def club_role(db: AsyncSession, user: User, club_id: uuid.UUID) -> ClubRole | None:
    return await db.scalar(
        select(Membership.role).where(
            Membership.club_id == club_id,
            Membership.user_id == user.id,
            Membership.status == MembershipStatus.ACTIVE,
        )
    )


async def can(db: AsyncSession, user: User, action: str, club_id: uuid.UUID | None = None) -> bool:
    if action in OWNER_ACTIONS:
        return user.is_platform_owner

    needed = CLUB_ACTIONS.get(action)
    if needed is None:
        raise ValueError(f"Unknown action {action!r}")  # a typo must fail loudly, never allow
    if club_id is None:
        return False

    role = await club_role(db, user, club_id)
    return role is not None and ROLE_RANK[role] >= ROLE_RANK[needed]


async def require(db: AsyncSession, user: User, action: str, club_id: uuid.UUID | None = None) -> None:
    if not await can(db, user, action, club_id):
        raise Forbidden()
