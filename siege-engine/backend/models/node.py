"""Structured-model entities: Node, Edge, Fragment, Draft.

These are the v2 projection tables — the current approved state of the
structured model. They are not written to directly by application code;
every write goes through ``backend.graph.reducer.append_event``, which
validates an event, writes it to ``graph_events``, and applies the
corresponding projection update.

See ``docs/architecture/v2-rearchitecture.md`` for the data-model
shape these tables back.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base

# Allowed enum-like values. Stored as TEXT with CHECK constraints for
# SQLite portability. The canonical definitions live as Python enums
# in backend.graph.ids / backend.graph.fragments.

NODE_TIERS = (
    "feat",
    "resp",
    "comp",
    "impl",
    "plan",
    "policy",
    "expansion",
    "reqs",
    "subreqs",
    "sysarch",
    "manifest",
    "fanin",
)
NODE_KINDS = ("domain", "presentational")
EDGE_TYPES = ("dependency", "domain_parent", "policy_application")
FRAGMENT_KINDS = ("techspec", "pubapi", "privapi", "policies", "deps")
DRAFT_TARGET_TYPES = ("node", "fragment")
DRAFT_STATUSES = ("pending", "approved", "discarded")


class Node(Base):
    __tablename__ = "nodes"
    __table_args__ = (
        CheckConstraint(
            f"tier IN {NODE_TIERS}",
            name="ck_nodes_tier",
        ),
        CheckConstraint(
            f"kind IN {NODE_KINDS}",
            name="ck_nodes_kind",
        ),
        UniqueConstraint("project_id", "id", name="uq_nodes_project_id"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tier: Mapped[str] = mapped_column(String(8), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    parent_id: Mapped[str | None] = mapped_column(
        ForeignKey("nodes.id", ondelete="SET NULL"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class Edge(Base):
    __tablename__ = "edges"
    __table_args__ = (
        CheckConstraint(
            f"edge_type IN {EDGE_TYPES}",
            name="ck_edges_edge_type",
        ),
        UniqueConstraint(
            "project_id",
            "edge_type",
            "source_id",
            "target_id",
            name="uq_edges_project_type_source_target",
        ),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    edge_type: Mapped[str] = mapped_column(String(16), nullable=False)
    source_id: Mapped[str] = mapped_column(
        ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False
    )
    target_id: Mapped[str] = mapped_column(
        ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Fragment(Base):
    __tablename__ = "fragments"
    __table_args__ = (
        CheckConstraint(
            f"fragment_kind IN {FRAGMENT_KINDS}",
            name="ck_fragments_fragment_kind",
        ),
        UniqueConstraint("owner_id", "fragment_kind", name="uq_fragments_owner_kind"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    owner_id: Mapped[str] = mapped_column(
        ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False
    )
    fragment_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class Draft(Base):
    __tablename__ = "drafts"
    __table_args__ = (
        CheckConstraint(
            f"target_type IN {DRAFT_TARGET_TYPES}",
            name="ck_drafts_target_type",
        ),
        CheckConstraint(
            f"status IN {DRAFT_STATUSES}",
            name="ck_drafts_status",
        ),
        # Partial unique index enforced in migration (SQLite needs raw SQL).
        Index("ix_drafts_target", "target_type", "target_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    target_type: Mapped[str] = mapped_column(String(16), nullable=False)
    target_id: Mapped[str] = mapped_column(String(64), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    batch_id: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
