"""v2 foundation — structured-model tables

Revision ID: b1_v2_foundation
Revises: a1_drop_v1_leftover_cols
Create Date: 2026-04-12

Creates the v2 structured-model backing tables: the append-only graph
event log, the projection tables (nodes, edges, fragments, drafts),
the pending-change queue, and review view markers.

These tables back the data layer described in
``docs/architecture/v2-rearchitecture.md``. Every write goes through
``backend.graph.reducer.append_event``, which validates an event,
writes it to ``graph_events``, and updates the projections.

Enum-like columns are stored as TEXT with CHECK constraints for SQLite
portability; the canonical enum definitions live as Python enums in
``backend.graph.ids`` and ``backend.graph.fragments``. Extending any
enum value in a later migration requires ``batch_alter_table``.

Forward-only. Downgrade raises NotImplementedError.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b1_v2_foundation"
down_revision: Union[str, Sequence[str], None] = "a1_drop_v1_leftover_cols"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


NODE_TIERS = ("feat", "resp", "comp", "impl")
NODE_KINDS = ("domain", "presentational")
EDGE_TYPES = ("dependency", "domain_parent")
FRAGMENT_KINDS = ("pubapi", "privapi", "deps")
DRAFT_TARGET_TYPES = ("node", "fragment")
DRAFT_STATUSES = ("pending", "approved", "discarded")
PENDING_INSTRUCTION_STATUSES = ("queued", "running", "applied", "discarded", "failed")


def upgrade() -> None:
    op.create_table(
        "graph_events",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("offset", sa.BigInteger(), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "offset", name="uq_graph_events_project_offset"),
    )
    op.create_index(
        "ix_graph_events_project_id", "graph_events", ["project_id"], unique=False
    )

    op.create_table(
        "nodes",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("tier", sa.String(length=8), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("parent_id", sa.String(length=32), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("display_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["parent_id"], ["nodes.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(f"tier IN {NODE_TIERS}", name="ck_nodes_tier"),
        sa.CheckConstraint(f"kind IN {NODE_KINDS}", name="ck_nodes_kind"),
        sa.UniqueConstraint("project_id", "id", name="uq_nodes_project_id"),
    )
    op.create_index("ix_nodes_project_id", "nodes", ["project_id"], unique=False)

    op.create_table(
        "edges",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("edge_type", sa.String(length=16), nullable=False),
        sa.Column("source_id", sa.String(length=32), nullable=False),
        sa.Column("target_id", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_id"], ["nodes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["target_id"], ["nodes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(f"edge_type IN {EDGE_TYPES}", name="ck_edges_edge_type"),
        sa.UniqueConstraint(
            "project_id",
            "edge_type",
            "source_id",
            "target_id",
            name="uq_edges_project_type_source_target",
        ),
    )
    op.create_index("ix_edges_project_id", "edges", ["project_id"], unique=False)

    op.create_table(
        "fragments",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("owner_id", sa.String(length=32), nullable=False),
        sa.Column("fragment_kind", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_id"], ["nodes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            f"fragment_kind IN {FRAGMENT_KINDS}", name="ck_fragments_fragment_kind"
        ),
        sa.UniqueConstraint("owner_id", "fragment_kind", name="uq_fragments_owner_kind"),
    )
    op.create_index("ix_fragments_project_id", "fragments", ["project_id"], unique=False)

    op.create_table(
        "drafts",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("target_type", sa.String(length=16), nullable=False),
        sa.Column("target_id", sa.String(length=64), nullable=False),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("batch_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            f"target_type IN {DRAFT_TARGET_TYPES}", name="ck_drafts_target_type"
        ),
        sa.CheckConstraint(f"status IN {DRAFT_STATUSES}", name="ck_drafts_status"),
    )
    op.create_index("ix_drafts_project_id", "drafts", ["project_id"], unique=False)
    op.create_index("ix_drafts_target", "drafts", ["target_type", "target_id"], unique=False)
    # Partial unique index: at most one pending draft per (target_type, target_id).
    # SQLAlchemy metadata doesn't carry this, so it lives in the migration.
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_drafts_pending_target "
        "ON drafts (target_type, target_id) "
        "WHERE status = 'pending'"
    )

    op.create_table(
        "pending_instructions",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("instruction_type", sa.String(length=64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="queued"),
        sa.Column("job_id", sa.String(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            f"status IN {PENDING_INSTRUCTION_STATUSES}",
            name="ck_pending_instructions_status",
        ),
    )
    op.create_index(
        "ix_pending_instructions_project_id",
        "pending_instructions",
        ["project_id"],
        unique=False,
    )

    op.create_table(
        "views",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("batch_id", sa.String(length=64), nullable=False),
        sa.Column("event_offset", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_views_project_id", "views", ["project_id"], unique=False)


def downgrade() -> None:
    raise NotImplementedError("v2 migrations are forward-only.")
