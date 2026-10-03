import uuid

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog, User


async def record(
    db: AsyncSession,
    request: Request,
    actor: User | None,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID | str,
    club_id: uuid.UUID | None = None,
    before: dict | None = None,
    after: dict | None = None,
) -> None:
    """Write one audit row inside the current transaction, so it commits with the change."""
    db.add(AuditLog(
        actor_id=actor.id if actor else None,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id),
        club_id=club_id,
        before=before,
        after=after,
        ip=request.client.host if request.client else None,
    ))
