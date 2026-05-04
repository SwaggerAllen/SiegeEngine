"""Add ``batches`` table + ``Job.batch_id`` FK (Phase 14 universal batch tagging).

Revision ID: b22_batches_table
Revises: b21_layered_fragment_kinds
Create Date: 2026-05-03

Every multi-job operation (tier-op like Reset All) and every per-
node operation (bootstrap_reset, bootstrap_feedback, etc.) mints a
``Batch`` row and stamps the resulting ``batch_id`` onto every
job it enqueues. The minted id also threads through the
``DraftGenerated`` event into ``Draft.batch_id``, replacing the
prior per-draft-fresh-mint with batch-aware semantics so multi-
draft tier-ops share one batch.

This unlocks:
- Resume-after-interrupt at the batch level (re-enqueue only the
  jobs that didn't complete).
- Review-summary scoping to the most-recent batch's drafts.
- Per-batch detail views as a future read-side affordance.

``Job.batch_id`` is nullable because the wider system enqueues
many cascade jobs from inside handlers (post-commit review hook,
mint → downstream generate fan-outs) that are system automation,
not user-issued operations. Those stay batchless until / unless we
plumb explicit cascade-batch propagation.

Forward-only; downgrade raises NotImplementedError.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b22_batches_table"
down_revision: Union[str, Sequence[str], None] = "b21_layered_fragment_kinds"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "batches",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("op_type", sa.String(length=64), nullable=False),
        sa.Column("tier", sa.String(length=32), nullable=True),
        sa.Column("scope_keys", sa.JSON(), nullable=False),
        sa.Column("params", sa.JSON(), nullable=False),
        sa.Column(
            "initiator_user_id",
            sa.String(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "started_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default="running",
        ),
    )

    with op.batch_alter_table("jobs") as batch:
        batch.add_column(
            sa.Column(
                "batch_id",
                sa.String(length=64),
                sa.ForeignKey(
                    "batches.id",
                    name="fk_jobs_batch_id",
                    ondelete="SET NULL",
                ),
                nullable=True,
            )
        )
    op.create_index("ix_jobs_batch_id", "jobs", ["batch_id"])


def downgrade() -> None:
    raise NotImplementedError("v2 migrations are forward-only.")
