"""add jobs queued dedup index

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-03-22 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'e5f6a7b8c9d0'
down_revision: Union[str, Sequence[str], None] = 'd4e5f6a7b8c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add partial unique index to prevent duplicate queued jobs."""
    # SQLite partial unique index: only one queued job per (job_type, payload).
    # Completed/failed/cancelled jobs are unaffected.
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_jobs_queued_dedup "
        "ON jobs (job_type, payload) "
        "WHERE status = 'queued'"
    )


def downgrade() -> None:
    """Remove partial unique index."""
    op.execute("DROP INDEX IF EXISTS uq_jobs_queued_dedup")
