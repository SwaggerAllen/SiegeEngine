"""add failed to artifactstatus enum

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-03-25 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = 'f6a7b8c9d0e1'
down_revision: Union[str, Sequence[str], None] = 'e5f6a7b8c9d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # SQLite stores enums as plain strings, so no schema change needed.
    # For PostgreSQL, add the new value to the native enum type.
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("ALTER TYPE artifactstatus ADD VALUE IF NOT EXISTS 'FAILED' BEFORE 'STALE'")


def downgrade() -> None:
    # PostgreSQL does not support removing enum values.
    # SQLite needs no change.
    pass
