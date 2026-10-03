"""Initial schema from db/schema.sql

Revision ID: 0001
Revises:
Create Date: 2026-10-03
"""
from pathlib import Path

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

SCHEMA = Path(__file__).resolve().parents[3] / "db" / "schema.sql"


def upgrade() -> None:
    # asyncpg can run a whole multi-statement file, but only through its own execute()
    sql = SCHEMA.read_text()
    op.get_bind().connection.dbapi_connection.run_async(lambda conn: conn.execute(sql))


def downgrade() -> None:
    op.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
