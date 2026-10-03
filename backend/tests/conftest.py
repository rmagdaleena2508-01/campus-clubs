"""
Tests run against real Postgres and Redis from docker-compose, using a
separate database (clubs_test) and Redis db 15. Emails are captured in OUTBOX
instead of being sent.
"""
import os

os.environ["DATABASE_URL"] = "postgresql+asyncpg://clubs:clubs@localhost:5433/clubs_test"
os.environ["REDIS_URL"] = "redis://localhost:6380/15"
os.environ["GOOGLE_CLIENT_ID"] = "test-client"
os.environ["COOKIE_SECURE"] = "false"

from datetime import datetime, timedelta, timezone  # noqa: E402
from pathlib import Path  # noqa: E402

import asyncpg  # noqa: E402
import pytest  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

SCHEMA = Path(__file__).resolve().parents[2] / "db" / "schema.sql"


@pytest.fixture(scope="session", autouse=True)
async def database():
    admin = await asyncpg.connect("postgresql://clubs:clubs@localhost:5433/clubs")
    await admin.execute("DROP DATABASE IF EXISTS clubs_test WITH (FORCE)")
    await admin.execute("CREATE DATABASE clubs_test")
    await admin.close()

    conn = await asyncpg.connect("postgresql://clubs:clubs@localhost:5433/clubs_test")
    await conn.execute(SCHEMA.read_text())
    await conn.close()

    from app.cli import seed
    await seed()
    yield


@pytest.fixture(autouse=True)
async def clean(database):
    from app.db import engine
    from app.redis import redis

    await redis.flushdb()
    async with engine.begin() as conn:
        await conn.exec_driver_sql(
            "TRUNCATE audit_log, applications, recruitment_drives, memberships, clubs, "
            "platform_settings, student_profiles, external_profiles, users CASCADE"
        )
    yield


OUTBOX: list[tuple[str, str]] = []


@pytest.fixture(autouse=True)
def sent_emails(monkeypatch):
    from app.routers import auth

    OUTBOX.clear()

    async def capture(to, subject, body):
        OUTBOX.append((to, body))

    monkeypatch.setattr(auth, "send_email", capture)
    return OUTBOX


def last_code(email: str) -> str:
    body = next(body for to, body in reversed(OUTBOX) if to == email)
    return body.split()[3].rstrip(".")


@pytest.fixture
def client_factory():
    from app.main import app

    clients: list[AsyncClient] = []

    def make() -> AsyncClient:
        c = AsyncClient(transport=ASGITransport(app=app, client=("10.0.0.%d" % (len(clients) + 1), 1234)),
                        base_url="http://test")
        clients.append(c)
        return c

    yield make


async def sign_in(client: AsyncClient, email: str, name: str = "Test Student",
                  institution: str | None = None) -> dict:
    """Sign in with an email code, the way every user does."""
    r = await client.post("/auth/email/start", json={"email": email})
    assert r.status_code == 200, r.text
    r = await client.post("/auth/email/verify", json={
        "email": email, "code": last_code(email.lower()), "full_name": name, "institution": institution,
    })
    assert r.status_code == 200, r.text
    body = r.json()
    client.headers["X-CSRF-Token"] = body["csrf_token"]
    return body["user"]


async def onboard(client: AsyncClient, register_no: str, year: int = 2, campus_code: str = "KTR",
                  department_code: str = "CSE") -> None:
    campuses = {c["code"]: c["id"] for c in (await client.get("/campuses")).json()}
    departments = {d["code"]: d["id"] for d in (await client.get("/departments")).json()}
    r = await client.put("/me/onboarding", json={
        "campus_id": campuses[campus_code], "department_id": departments[department_code],
        "year_of_study": year, "register_no": register_no,
    })
    assert r.status_code == 200, r.text


async def make_owner(email: str) -> None:
    from app.cli import set_owner
    await set_owner(email, True)


def window(hours_from_now_start: int = -1, hours_long: int = 48) -> tuple[str, str]:
    start = datetime.now(timezone.utc) + timedelta(hours=hours_from_now_start)
    return start.isoformat(), (start + timedelta(hours=hours_long)).isoformat()
