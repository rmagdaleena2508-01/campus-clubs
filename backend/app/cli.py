"""
Admin commands that must never be reachable over the API.

    uv run python -m app.cli seed                    # campuses + departments
    uv run python -m app.cli make-owner <email>      # grant Platform Owner
    uv run python -m app.cli remove-owner <email>
"""
import asyncio
import sys

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert

from app.db import SessionLocal
from app.models import Campus, Department, User

CAMPUSES = [
    ("KTR", "Kattankulathur"),
    ("RMP", "Ramapuram"),
    ("VDP", "Vadapalani"),
    ("NCR", "Delhi NCR (Modinagar)"),
    ("TRP", "Tiruchirappalli"),
]

DEPARTMENTS = [
    ("CSE", "Computer Science and Engineering"),
    ("IT", "Information Technology"),
    ("ECE", "Electronics and Communication Engineering"),
    ("EEE", "Electrical and Electronics Engineering"),
    ("MECH", "Mechanical Engineering"),
    ("CIVIL", "Civil Engineering"),
    ("AUTO", "Automobile Engineering"),
    ("AERO", "Aerospace Engineering"),
    ("BIOTECH", "Biotechnology"),
    ("CHEM", "Chemical Engineering"),
    ("OTHER", "Other"),
]


async def seed() -> None:
    async with SessionLocal() as db:
        for model, rows in ((Campus, CAMPUSES), (Department, DEPARTMENTS)):
            stmt = insert(model).values([{"code": c, "name": n} for c, n in rows])
            await db.execute(stmt.on_conflict_do_nothing(index_elements=["code"]))
        await db.commit()
    print("Seeded campuses and departments.")


async def set_owner(email: str, value: bool) -> None:
    async with SessionLocal() as db:
        result = await db.execute(
            update(User).where(User.email == email.lower()).values(is_platform_owner=value).returning(User.id)
        )
        if result.scalar() is None:
            sys.exit(f"No user with email {email}. Sign in once first.")
        await db.commit()
    print(f"{email} is {'now' if value else 'no longer'} a Platform Owner.")


def main() -> None:
    match sys.argv[1:]:
        case ["seed"]:
            asyncio.run(seed())
        case ["make-owner", email]:
            asyncio.run(set_owner(email, True))
        case ["remove-owner", email]:
            asyncio.run(set_owner(email, False))
        case _:
            sys.exit(__doc__)


if __name__ == "__main__":
    main()
