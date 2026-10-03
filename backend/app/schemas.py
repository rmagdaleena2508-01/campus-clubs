import re
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, HttpUrl, field_validator, model_validator

from app.models import ApplicationStage, ClubRole, ClubStatus, DriveStatus, UserKind

SLUG = r"^[a-z0-9][a-z0-9-]{1,48}[a-z0-9]$"


class Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Auth and profile
# ---------------------------------------------------------------------------
class GoogleSignIn(BaseModel):
    id_token: str = Field(min_length=10, max_length=4096)


class EmailCodeRequest(BaseModel):
    email: EmailStr


class EmailCodeVerify(BaseModel):
    email: EmailStr
    code: str = Field(pattern=r"^\d{6}$")
    # needed only the first time someone signs in (institution only for non-SRM emails)
    full_name: str | None = Field(default=None, min_length=2, max_length=80)
    institution: str | None = Field(default=None, min_length=2, max_length=120)


class StudentProfileOut(Out):
    register_no: str | None
    campus_id: int | None
    department_id: int | None
    year_of_study: int | None
    bio: str | None
    interests: list[str]


class MeOut(Out):
    id: uuid.UUID
    email: str
    full_name: str
    handle: str
    kind: UserKind
    is_platform_owner: bool
    needs_onboarding: bool
    student_profile: StudentProfileOut | None = None


class SessionOut(BaseModel):
    user: MeOut
    csrf_token: str


class Onboarding(BaseModel):
    campus_id: int
    department_id: int
    year_of_study: int = Field(ge=1, le=5)
    register_no: str = Field(pattern=r"^[A-Za-z0-9]{6,20}$")


class CampusOut(Out):
    id: int
    code: str
    name: str


class DepartmentOut(CampusOut):
    pass


# ---------------------------------------------------------------------------
# Clubs
# ---------------------------------------------------------------------------
class ClubLink(BaseModel):
    label: str = Field(min_length=1, max_length=40)
    url: HttpUrl


class ClubRequest(BaseModel):
    name: str = Field(min_length=3, max_length=80)
    slug: str = Field(pattern=SLUG)
    tagline: str | None = Field(default=None, max_length=140)
    description: str = Field(min_length=30, max_length=4000)
    category: Literal["technical", "cultural", "sports", "literary", "social", "entrepreneurship", "other"]
    department_id: int | None = None
    links: list[ClubLink] = Field(default_factory=list, max_length=8)


class ClubOut(Out):
    id: uuid.UUID
    slug: str
    name: str
    tagline: str | None
    description: str
    category: str
    campus_id: int
    department_id: int | None
    links: list[dict]
    status: ClubStatus
    created_at: datetime


class ClubReview(BaseModel):
    decision: Literal["approve", "reject"]
    note: str | None = Field(default=None, max_length=500)


class RoleChange(BaseModel):
    role: ClubRole
    title: str | None = Field(default=None, max_length=40)


class MemberOut(BaseModel):
    user_id: uuid.UUID
    full_name: str
    handle: str
    role: ClubRole
    title: str | None
    joined_at: datetime


# ---------------------------------------------------------------------------
# Recruitment
# ---------------------------------------------------------------------------
QuestionType = Literal["text", "long_text", "choice", "multi", "url"]


class Question(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9_]{1,40}$")
    label: str = Field(min_length=1, max_length=200)
    type: QuestionType
    required: bool = True
    options: list[str] | None = Field(default=None, max_length=30)

    @model_validator(mode="after")
    def options_match_type(self):
        has_options = self.type in ("choice", "multi")
        if has_options and not self.options:
            raise ValueError(f"question {self.id!r} needs options")
        if not has_options and self.options:
            raise ValueError(f"question {self.id!r} can't have options")
        return self


class Eligibility(BaseModel):
    years: list[int] = Field(default_factory=list)            # empty = any year
    department_ids: list[int] = Field(default_factory=list)   # empty = any department


class DriveCreate(BaseModel):
    title: str = Field(min_length=3, max_length=100)
    description: str | None = Field(default=None, max_length=4000)
    opens_at: datetime
    closes_at: datetime
    seats: int | None = Field(default=None, gt=0, le=1000)
    eligibility: Eligibility = Field(default_factory=Eligibility)
    form_schema: list[Question] = Field(min_length=1, max_length=25)

    @model_validator(mode="after")
    def check(self):
        if self.closes_at <= self.opens_at:
            raise ValueError("closes_at must be after opens_at")
        ids = [q.id for q in self.form_schema]
        if len(ids) != len(set(ids)):
            raise ValueError("question ids must be unique")
        return self


class DriveOut(Out):
    id: uuid.UUID
    club_id: uuid.UUID
    title: str
    description: str | None
    status: DriveStatus
    opens_at: datetime
    closes_at: datetime
    seats: int | None
    eligibility: dict
    form_schema: list[dict]


class ApplicationCreate(BaseModel):
    answers: dict[str, str | list[str]]


class StageChange(BaseModel):
    stage: Literal["shortlisted", "interview", "selected", "rejected"]
    internal_note: str | None = Field(default=None, max_length=1000)


class MyApplicationOut(Out):
    """What the applicant sees: never the club's internal note."""
    id: uuid.UUID
    drive_id: uuid.UUID
    stage: ApplicationStage
    answers: dict
    created_at: datetime
    updated_at: datetime


class ReviewApplicationOut(MyApplicationOut):
    """What club admins see in their queue."""
    user_id: uuid.UUID
    applicant_name: str
    applicant_handle: str
    internal_note: str | None


def validate_answers(questions: list[dict], answers: dict) -> dict:
    """Check answers against the drive's form. Returns only known question ids."""
    clean: dict = {}
    for q in questions:
        value = answers.get(q["id"])
        empty = value is None or value == "" or value == []
        if empty:
            if q.get("required", True):
                raise ValueError(f"'{q['label']}' is required")
            continue

        kind = q["type"]
        if kind == "multi":
            if not isinstance(value, list) or not set(value) <= set(q["options"]):
                raise ValueError(f"'{q['label']}' has an invalid choice")
        elif not isinstance(value, str):
            raise ValueError(f"'{q['label']}' must be text")
        elif kind == "choice" and value not in q["options"]:
            raise ValueError(f"'{q['label']}' has an invalid choice")
        elif kind == "url" and not re.match(r"^https?://\S{3,500}$", value):
            raise ValueError(f"'{q['label']}' must be a link")
        elif len(value) > (4000 if kind == "long_text" else 300):
            raise ValueError(f"'{q['label']}' is too long")
        clean[q["id"]] = value
    return clean
