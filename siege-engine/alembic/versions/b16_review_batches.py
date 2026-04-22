"""v2 Phase 12 — review batches + projection snapshot cache

Revision ID: b16_review_batches
Revises: b15_is_deferred
Create Date: 2026-04-22

Adds two tables backing the Phase 12 batched review walker:

* ``review_batches`` — one row per batched-review session. The
  batch pins ``pinned_offset = GraphEvent.offset`` at open time so
  the walker can snapshot the projection state the user started
  reviewing against, and surfaces ``closed_at`` when every
  stale-at-pin node has been reviewed or the user explicitly
  closes the batch.
* ``projection_snapshots`` — a content-addressed cache keyed by
  ``(project_id, offset)``. Each row holds a JSON-serialized
  projection payload produced by ``rebuild_projections`` at that
  offset. Immutable: rows are inserted once and never updated.
  The cache is pure optimization on the log-walk path used by the
  batch walker's fragment-diff computation (Phase 12c).

Forward-only; downgrade raises NotImplementedError.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b16_review_batches"
down_revision: Union[str, Sequence[str], None] = "b15_is_deferred"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "review_batches",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(32),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("pinned_offset", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
        sa.Column("closed_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "ix_review_batches_project",
        "review_batches",
        ["project_id", "created_at"],
    )

    op.create_table(
        "projection_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "project_id",
            sa.String(32),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("offset", sa.BigInteger(), nullable=False),
        sa.Column("payload_blob", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
        sa.UniqueConstraint(
            "project_id",
            "offset",
            name="uq_projection_snapshots_project_offset",
        ),
    )


def downgrade() -> None:
    raise NotImplementedError("v2 migrations are forward-only.")
