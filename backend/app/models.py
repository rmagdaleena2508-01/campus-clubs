"""
ORM models. db/schema.sql is the source of truth for the tables; these classes
only map the tables the API uses so far (people, clubs, recruitment, audit).
"""
import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, String, Text, text
from sqlalchemy.dialects.postgresql import ARRAY, ENUM, INET, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def pg_enum(enum_cls: type[enum.Enum], name: str) -> ENUM:
    # The types already exist in Postgres (schema.sql); store the lowercase values
    return ENUM(enum_cls, name=name, create_type=False, values_callable=lambda e: [m.value for m in e])


def uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))


def now_default() -> Mapped[datetime]:
    return mapped_column(server_default=text("now()"))


class UserKind(str, enum.Enum):
    COLLEGE = "college"
    EXTERNAL = "external"


class ClubStatus(str, enum.Enum):
    PENDING = "pending"
    ACTIVE = "active"
    REJECTED = "rejected"
    SUSPENDED = "suspended"
    ARCHIVED = "archived"


class ClubRole(str, enum.Enum):
    ADMIN = "admin"
    CORE = "core"
    MEMBER = "member"


class MembershipStatus(str, enum.Enum):
    ACTIVE = "active"
    LEFT = "left"
    REMOVED = "removed"


class DriveStatus(str, enum.Enum):
    DRAFT = "draft"
    OPEN = "open"
    CLOSED = "closed"


class ApplicationStage(str, enum.Enum):
    APPLIED = "applied"
    SHORTLISTED = "shortlisted"
    INTERVIEW = "interview"
    SELECTED = "selected"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"


# ---------------------------------------------------------------------------
# People
# ---------------------------------------------------------------------------
class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = uuid_pk()
    email: Mapped[str] = mapped_column(String)          # citext in Postgres; always stored lowercase
    full_name: Mapped[str]
    handle: Mapped[str] = mapped_column(String)
    kind: Mapped[UserKind] = mapped_column(pg_enum(UserKind, "user_kind"))
    google_sub: Mapped[str | None]
    avatar_key: Mapped[str | None]
    is_platform_owner: Mapped[bool] = mapped_column(server_default=text("false"))
    created_at: Mapped[datetime] = now_default()
    deleted_at: Mapped[datetime | None]

    student_profile: Mapped["StudentProfile | None"] = relationship(back_populates="user", lazy="selectin")
    external_profile: Mapped["ExternalProfile | None"] = relationship(back_populates="user", lazy="selectin")


class Campus(Base):
    __tablename__ = "campuses"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str]
    name: Mapped[str]


class Department(Base):
    __tablename__ = "departments"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str]
    name: Mapped[str]


class StudentProfile(Base):
    __tablename__ = "student_profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    register_no: Mapped[str | None]
    campus_id: Mapped[int | None] = mapped_column(ForeignKey("campuses.id"))
    department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id"))
    year_of_study: Mapped[int | None]
    bio: Mapped[str | None] = mapped_column(Text)
    interests: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'"))

    user: Mapped[User] = relationship(back_populates="student_profile")

    @property
    def is_complete(self) -> bool:
        return all([self.campus_id, self.department_id, self.year_of_study])


class ExternalProfile(Base):
    __tablename__ = "external_profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    institution: Mapped[str]
    phone: Mapped[str | None]

    user: Mapped[User] = relationship(back_populates="external_profile")


class PlatformSetting(Base):
    __tablename__ = "platform_settings"

    key: Mapped[str] = mapped_column(primary_key=True)
    value: Mapped[Any] = mapped_column(JSONB)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    updated_at: Mapped[datetime] = now_default()


# ---------------------------------------------------------------------------
# Clubs
# ---------------------------------------------------------------------------
class Club(Base):
    __tablename__ = "clubs"

    id: Mapped[uuid.UUID] = uuid_pk()
    slug: Mapped[str] = mapped_column(String)
    name: Mapped[str]
    tagline: Mapped[str | None]
    description: Mapped[str] = mapped_column(Text)
    category: Mapped[str]
    campus_id: Mapped[int] = mapped_column(ForeignKey("campuses.id"))
    department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id"))
    logo_key: Mapped[str | None]
    links: Mapped[list[dict]] = mapped_column(JSONB, server_default=text("'[]'"))
    status: Mapped[ClubStatus] = mapped_column(pg_enum(ClubStatus, "club_status"))
    requested_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    reviewed_at: Mapped[datetime | None]
    review_note: Mapped[str | None]
    created_at: Mapped[datetime] = now_default()


class Membership(Base):
    __tablename__ = "memberships"

    id: Mapped[uuid.UUID] = uuid_pk()
    club_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clubs.id"))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    role: Mapped[ClubRole] = mapped_column(pg_enum(ClubRole, "club_role"))
    title: Mapped[str | None]
    status: Mapped[MembershipStatus] = mapped_column(pg_enum(MembershipStatus, "membership_status"))
    joined_at: Mapped[datetime] = now_default()
    ended_at: Mapped[datetime | None]


# ---------------------------------------------------------------------------
# Recruitment
# ---------------------------------------------------------------------------
class RecruitmentDrive(Base):
    __tablename__ = "recruitment_drives"

    id: Mapped[uuid.UUID] = uuid_pk()
    club_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clubs.id"))
    title: Mapped[str]
    description: Mapped[str | None]
    status: Mapped[DriveStatus] = mapped_column(pg_enum(DriveStatus, "drive_status"))
    opens_at: Mapped[datetime]
    closes_at: Mapped[datetime]
    seats: Mapped[int | None]
    eligibility: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'"))
    form_schema: Mapped[list[dict]] = mapped_column(JSONB, server_default=text("'[]'"))
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = now_default()


class Application(Base):
    __tablename__ = "applications"

    id: Mapped[uuid.UUID] = uuid_pk()
    drive_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("recruitment_drives.id"))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    answers: Mapped[dict] = mapped_column(JSONB)
    stage: Mapped[ApplicationStage] = mapped_column(pg_enum(ApplicationStage, "application_stage"))
    internal_note: Mapped[str | None]
    decided_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    decided_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = now_default()
    updated_at: Mapped[datetime] = now_default()


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------
class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str]
    entity_type: Mapped[str]
    entity_id: Mapped[str]
    club_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("clubs.id"))
    before: Mapped[dict | None] = mapped_column(JSONB)
    after: Mapped[dict | None] = mapped_column(JSONB)
    ip: Mapped[str | None] = mapped_column(INET)
    created_at: Mapped[datetime] = now_default()
