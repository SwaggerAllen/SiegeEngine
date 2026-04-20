"""v2 Phase 9 — staleness ledger

Revision ID: b14_staleness_ledger
Revises: b13_review_text
Create Date: 2026-04-19

Adds the ``staleness_ledger`` table that records, per
``(project_id, stale_node_id, source_node_id, reason)`` triple, the
upstream change that invalidated a downstream reader and the event
offset at which the change landed. Written by
``_apply_staleness_marked`` and cleared by
``_apply_staleness_cleared``; emitted in turn by the central fanout
dispatcher (:mod:`backend.graph.fanout`) in response to content,
edge, and structural events.

See ``docs/architecture/v2-roadmap.md`` Phase 9 and
``seed-docs/catapult-spec-v3.md`` §A.3.6 (reactive runtime /
staling). Forward-only; downgrade raises NotImplementedError.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b14_staleness_ledger"
down_revision: Union[str, Sequence[str], None] = "b13_review_text"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


STALENESS_REASONS = (
    "content_changed",
    "fragment_changed",
    "edge_created",
    "edge_deleted",
    "structural_change",
)


def upgrade() -> None:
    op.create_table(
        "staleness_ledger",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "project_id",
            sa.String(32),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "stale_node_id",
            sa.String(32),
            sa.ForeignKey("nodes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "source_node_id",
            sa.String(32),
            sa.ForeignKey("nodes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_offset", sa.BigInteger(), nullable=False),
        sa.Column("reason", sa.String(32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
        sa.CheckConstraint(
            f"reason IN {STALENESS_REASONS}",
            name="ck_staleness_ledger_reason",
        ),
        sa.UniqueConstraint(
            "project_id",
            "stale_node_id",
            "source_node_id",
            "reason",
            name="uq_staleness_ledger_triple",
        ),
    )
    op.create_index(
        "ix_staleness_ledger_project_id",
        "staleness_ledger",
        ["project_id"],
    )
    op.create_index(
        "ix_staleness_ledger_stale_node",
        "staleness_ledger",
        ["project_id", "stale_node_id"],
    )


def downgrade() -> None:
    raise NotImplementedError("v2 migrations are forward-only.")
