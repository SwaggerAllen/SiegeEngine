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
    BigInteger,
    Boolean,
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
    "vocab",
    "ref",
)
NODE_KINDS = ("domain", "presentational")
EDGE_TYPES = (
    "dependency",
    "domain_parent",
    "policy_application",
    "decomposition",
    "reference",
)
FRAGMENT_KINDS = (
    # Sysarch / legacy slots — sysarch_mint writes ``techspec`` /
    # ``pubapi`` skeletons here at top-level-comp creation time;
    # comparch_mint writes the same skeletons on each subcomp it
    # mints. Kept as the readable "lowest layer" fallback so a
    # comparch reset can clear the rich layer without losing the
    # sysarch seed underneath. ``privapi`` / ``policies`` / ``deps``
    # / ``failuresurface`` exist here only for legacy projects whose
    # rich content predates the layer split — fresh writes go to the
    # ``comparch*`` slots below.
    "techspec",
    "pubapi",
    "privapi",
    "policies",
    "deps",
    "failuresurface",
    # Comparch-layer slots — comparch_mint writes the rich
    # per-comp content here, comparch reset clears just these.
    "comparchtechspec",
    "comparchpubapi",
    "comparchprivapi",
    "comparchpolicies",
    "comparchdeps",
    "comparchfailuresurface",
    # Subcomparch-layer slots — subcomparch_mint writes the rich
    # per-subcomp content here, subcomparch reset clears just these.
    "subcomparchtechspec",
    "subcomparchpubapi",
    "subcomparchprivapi",
    "subcomparchdeps",
)
DRAFT_TARGET_TYPES = ("node", "fragment")
DRAFT_STATUSES = ("pending", "approved", "discarded")
# Phase 9 staleness ledger reasons. Each marker records why a
# downstream node became stale w.r.t. a specific upstream neighbor.
STALENESS_REASONS = (
    "content_changed",
    "fragment_changed",
    "edge_created",
    "edge_deleted",
    "structural_change",
)


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
    # v3: optional git-backed body. When set, body content lives at
    # ``body_path`` in the project repo at sha ``body_sha`` and the
    # ``content`` column carries a sentinel (kept NOT NULL for
    # legacy callers). Readers prefer git when body_sha is set;
    # legacy rows (body_sha NULL) continue reading from content.
    # Used today for ref nodes; vocab + others will follow.
    body_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    body_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    # Optional grouping label, currently used only by feat_* nodes
    # minted from an approved <features> expansion containing
    # <group> blocks. Null for ungrouped features and for all
    # non-feature tiers. See
    # ``backend.graph.parsers.validators.validate_features``.
    group_label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Whether a feature was marked with <implicit/> in the
    # expansion — i.e. the LLM inferred it as obviously-necessary
    # rather than finding it in the user's input doc. Defaults
    # false and is ignored by non-feature tiers.
    is_implicit: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Phase-11 followup B7. Whether a feat_* node is deferred —
    # design-toward but skip in the current pipeline. Deferred
    # features stay visible in the expansion and DAG; downstream
    # generation tiers (reqs, sysarch) filter them out via
    # ``list_features(include_deferred=False)``. Defaults false
    # and is ignored by non-feature tiers.
    is_deferred: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Whether a comp_* node was minted with the foundation role.
    # Set at mint time by sysarch_mint / comparch_mint from the
    # ``<foundation/>`` marker in the parsed arch doc. Defaults
    # false and is ignored by non-comp tiers. Persisting the flag
    # is what lets the comparch-generation pass know whether the
    # target is itself a foundation and therefore should decompose
    # exhaustively without nesting another foundation subcomponent
    # (see ``docs/architecture/v2-rearchitecture.md`` §Foundation
    # components).
    is_foundation: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Phase 8 — AI self-review output for tiers whose reviews
    # target the node directly rather than a Draft row. Used
    # by ``fanin`` tier, which has no draft lifecycle — its
    # content writes via ``FanInContentUpdated`` and its
    # review lands here. Empty for every other tier.
    review_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
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
    # Length 32 covers the longest layer-prefixed kind ("comparchfailuresurface"
    # = 22 chars). SQLite ignores VARCHAR length but other engines wouldn't.
    fragment_kind: Mapped[str] = mapped_column(String(32), nullable=False)
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
    # Phase 8 — AI self-review output. Starts empty; populated by
    # a ``v2.review_<tier>`` job after the draft commits.
    # Overwritten on ``DraftReviewUpdated`` events. Reset to empty
    # when a new draft replaces this one.
    review_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Phase 12 auto-revision — ``user_regen`` if the discard came
    # from a user-initiated Reject & Regenerate, ``auto_revision``
    # if it came from the AI-driven revision loop (draft generated,
    # AI-reviewed, discarded without the user seeing it as pending).
    # ``NULL`` while the draft is still pending / applied, and on
    # legacy discarded drafts that predate the field (all of which
    # are user-initiated by construction).
    discard_reason: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # Phase 13 — generator's self-report of what this draft contains
    # / changed vs its prior draft. 1-3 sentences of prose lifted out
    # of the ``<change-summary>`` tag at persist time. ``NULL`` on
    # pre-Phase-13 drafts, on fan-in drafts (out of scope), and on
    # drafts whose generator skipped the tag. Display-only — the
    # summary does NOT feed back into the next regen's prompt.
    change_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class StalenessLedger(Base):
    """Phase 9 — per-pair staleness marker.

    One row per ``(stale_node_id, source_node_id, reason)`` triple.
    Mutated by :func:`backend.graph.fanout.apply_staleness_changes`
    directly from inside ``append_event`` — staleness is derived
    state, not primary state, so it does **not** round-trip through
    the event log. On replay the ledger starts empty and stays
    empty; nothing is stale in a freshly-rebuilt projection because
    nothing has happened after rebuild yet.

    The unique constraint on the triple makes mark-insertion
    idempotent — re-inserting the same marker before the
    corresponding clear is a no-op (the dispatcher bumps
    ``source_offset`` on the existing row instead of writing a
    duplicate).
    """

    __tablename__ = "staleness_ledger"
    __table_args__ = (
        CheckConstraint(
            f"reason IN {STALENESS_REASONS}",
            name="ck_staleness_ledger_reason",
        ),
        UniqueConstraint(
            "project_id",
            "stale_node_id",
            "source_node_id",
            "reason",
            name="uq_staleness_ledger_triple",
        ),
        Index(
            "ix_staleness_ledger_stale_node",
            "project_id",
            "stale_node_id",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    stale_node_id: Mapped[str] = mapped_column(
        ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False
    )
    source_node_id: Mapped[str] = mapped_column(
        ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False
    )
    source_offset: Mapped[int] = mapped_column(BigInteger, nullable=False)
    reason: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
