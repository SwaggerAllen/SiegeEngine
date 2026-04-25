"""Add ``Job.is_deferred`` flag (Phase F follow-up).

Revision ID: b20_job_is_deferred
Revises: b19_failure_surface_fragment
Create Date: 2026-04-25

Replaces the load-bearing string marker on ``Job.error_message``
("deferred: …") with a typed boolean column. The marker was
introduced in Phase F to let the comparch wakeup hook find jobs
that completed via the deferred-retry path (handler raised
:class:`backend.graph.handlers._tier_generation.TierDeferredError`)
and re-enqueue them when their blocking dep settled. String-
discrimination on error_message is fragile — a refactor that
changes the prefix silently breaks the wakeup. This migration
adds an explicit ``is_deferred`` column so the wakeup query keys
off a typed flag.

Forward-only; downgrade raises NotImplementedError.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b20_job_is_deferred"
down_revision: Union[str, Sequence[str], None] = "b19_failure_surface_fragment"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # SQLite requires batch mode for ALTER TABLE ADD COLUMN with
    # constraint — but a plain bool with default False is safe.
    with op.batch_alter_table("jobs") as batch:
        batch.add_column(
            sa.Column(
                "is_deferred",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )


def downgrade() -> None:
    raise NotImplementedError("v2 migrations are forward-only.")
