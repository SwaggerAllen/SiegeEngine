"""Reset helpers for per-component bootstrap tiers.

The sysarch / expansion / requirements tiers already have reset
helpers defined alongside their state helpers. This module
collects the equivalents for the per-component tiers — subreqs,
comparch, subcomparch, impl — so they can opt into the generic
``bootstrap_reset`` machinery.

Each ``collect_downstream_nodes_*`` returns the set of projection
nodes to delete on reset, scoped to the tier's target (a
top-level comp for subreqs/comparch, a subcomponent for
subcomparch, a comp-or-sub owner for impl). Cascades follow the
"everything derived from this tier" rule: resetting subreqs
invalidates comparch, subcomparch, impl, fanin, local policies,
and all subresps under the comp. Resetting comparch invalidates
the same set except the subresps (which are subreqs-owned).

The helpers share a ``_collect_pending_drafts_for_nodes``
implementation that mirrors the sysarch-side version — drafts
have no foreign-key constraint on their ``target_id``, so we
explicitly discard drafts pointing at a to-be-deleted node or a
fragment it owns before the ``NodeDeleted`` cascade fires.

Job cancellation is handled by ``bootstrap_reset`` using the
``downstream_job_types`` tuple. For per-comp resets the
cancellation is project-wide (same as sysarch reset today) — the
re-enqueue after reset restarts only the reset tier's own job,
and downstream generation re-propagates naturally through the
pipeline chain.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models.node import Draft, Fragment, Node

# ── Downstream job types ─────────────────────────────────────────

# Subreqs reset cascades all the way through the pipeline — every
# per-comp generation and mint job type, plus the policy tiers
# since local policies get deleted too.
_SUBREQS_DOWNSTREAM_JOB_TYPES: tuple[str, ...] = (
    "v2.generate_subrequirements",
    "v2.mint_subrequirements",
    "v2.generate_comparch",
    "v2.mint_comparch",
    "v2.generate_subcomparch",
    "v2.mint_subcomparch",
    "v2.apply_top_level_policies",
    "v2.apply_component_local_policies",
    "v2.generate_impl",
    "v2.generate_fanin",
)

# Comparch reset keeps subresps (they're subreqs-owned) but nukes
# everything comparch_mint + downstream produced: subcomps, local
# policies, subcomparch content, impl, fanin.
_COMPARCH_DOWNSTREAM_JOB_TYPES: tuple[str, ...] = (
    "v2.generate_comparch",
    "v2.mint_comparch",
    "v2.generate_subcomparch",
    "v2.mint_subcomparch",
    "v2.apply_top_level_policies",
    "v2.apply_component_local_policies",
    "v2.generate_impl",
    "v2.generate_fanin",
)

_SUBCOMPARCH_DOWNSTREAM_JOB_TYPES: tuple[str, ...] = (
    "v2.generate_subcomparch",
    "v2.generate_impl",
    "v2.generate_fanin",
)

_IMPL_DOWNSTREAM_JOB_TYPES: tuple[str, ...] = (
    "v2.generate_impl",
    "v2.generate_fanin",
)


def subreqs_downstream_job_types() -> tuple[str, ...]:
    return _SUBREQS_DOWNSTREAM_JOB_TYPES


def comparch_downstream_job_types() -> tuple[str, ...]:
    return _COMPARCH_DOWNSTREAM_JOB_TYPES


def subcomparch_downstream_job_types() -> tuple[str, ...]:
    return _SUBCOMPARCH_DOWNSTREAM_JOB_TYPES


def impl_downstream_job_types() -> tuple[str, ...]:
    return _IMPL_DOWNSTREAM_JOB_TYPES


# ── Downstream node collection ───────────────────────────────────


def _descendants_under_comp(session: Session, project_id: str, comp_id: str) -> list[Node]:
    """Nodes minted under a top-level comp by comparch / subreqs and beyond.

    Returns: subcomp ``comp_*`` children, their ``impl_*`` leaves,
    the comp's direct ``impl_*`` (un-fanned-out), ``fanin_*``, and
    ``policy_*`` children (local policies). Subresps aren't
    included — callers add them explicitly when resetting subreqs.
    """
    out: list[Node] = []
    subcomps = list(
        session.execute(
            select(Node).where(
                Node.project_id == project_id,
                Node.tier == "comp",
                Node.parent_id == comp_id,
            )
        ).scalars()
    )
    subcomp_ids = [n.id for n in subcomps]
    out.extend(subcomps)

    # Local policies parented to this comp.
    out.extend(
        session.execute(
            select(Node).where(
                Node.project_id == project_id,
                Node.tier == "policy",
                Node.parent_id == comp_id,
            )
        ).scalars()
    )
    # Fan-in + top-level impl directly under the comp.
    out.extend(
        session.execute(
            select(Node).where(
                Node.project_id == project_id,
                Node.tier.in_(("fanin", "impl")),
                Node.parent_id == comp_id,
            )
        ).scalars()
    )
    # Impls under subcomps.
    if subcomp_ids:
        out.extend(
            session.execute(
                select(Node).where(
                    Node.project_id == project_id,
                    Node.tier == "impl",
                    Node.parent_id.in_(subcomp_ids),
                )
            ).scalars()
        )
    return out


def collect_downstream_nodes_subreqs(session: Session, project_id: str, comp_id: str) -> list[Node]:
    """Downstream of a subreqs reset: subresps + everything comparch
    cascades produce under this comp."""
    out: list[Node] = []
    # Subresps parented to this comp.
    out.extend(
        session.execute(
            select(Node).where(
                Node.project_id == project_id,
                Node.tier == "resp",
                Node.parent_id == comp_id,
            )
        ).scalars()
    )
    out.extend(_descendants_under_comp(session, project_id, comp_id))
    return out


def collect_downstream_nodes_comparch(
    session: Session, project_id: str, comp_id: str
) -> list[Node]:
    """Downstream of a comparch reset: subcomps + local policies +
    subcomparch/impl/fanin under this comp. Subresps survive (they
    belong to subreqs)."""
    return _descendants_under_comp(session, project_id, comp_id)


def collect_downstream_nodes_subcomparch(
    session: Session, project_id: str, sub_id: str
) -> list[Node]:
    """Downstream of a subcomparch reset: the sub's impl leaf, if
    one exists."""
    return list(
        session.execute(
            select(Node).where(
                Node.project_id == project_id,
                Node.tier == "impl",
                Node.parent_id == sub_id,
            )
        ).scalars()
    )


def collect_downstream_nodes_impl(session: Session, project_id: str, owner_id: str) -> list[Node]:
    """Impl is a leaf — nothing structural downstream. Return empty.

    The impl node's own content gets cleared by the generic
    ``BootstrapNodeContentCleared`` event the reset route emits;
    downstream-of-impl regen (fanin) is triggered naturally by the
    next approved impl. We don't cascade-delete fanin here — see
    the plan doc for the rationale.
    """
    return []


# ── Pending-draft collection (shared across per-comp tiers) ─────


def collect_pending_drafts_for_nodes(
    session: Session, project_id: str, node_ids: list[str]
) -> list[Draft]:
    """Mirror of :func:`backend.graph.sysarch.collect_pending_drafts_for_nodes`.

    Drafts carry an unconstrained string ``target_id`` (no FK
    cascade), so a ``NodeDeleted`` leaves their target dangling.
    Explicitly discard drafts pointing at a to-be-deleted node or
    a fragment owned by one before the reducer sees the
    ``NodeDeleted`` event.
    """
    if not node_ids:
        return []
    drafts: list[Draft] = []
    drafts.extend(
        session.execute(
            select(Draft).where(
                Draft.project_id == project_id,
                Draft.target_type == "node",
                Draft.target_id.in_(node_ids),
                Draft.status == "pending",
            )
        )
        .scalars()
        .all()
    )
    fragment_ids = list(
        session.execute(
            select(Fragment.id).where(
                Fragment.project_id == project_id,
                Fragment.owner_id.in_(node_ids),
            )
        ).scalars()
    )
    if fragment_ids:
        drafts.extend(
            session.execute(
                select(Draft).where(
                    Draft.project_id == project_id,
                    Draft.target_type == "fragment",
                    Draft.target_id.in_(fragment_ids),
                    Draft.status == "pending",
                )
            )
            .scalars()
            .all()
        )
    return drafts


# ── Additional nodes to clear (non-deleted singletons) ──────────


def additional_nodes_to_clear_subreqs(
    session: Session, project_id: str, comp_id: str
) -> list[Node | None]:
    """Subreqs reset clears the comp_*'s own content (comparch XML)
    since comparch derived from subreqs and is now stale."""
    node = session.get(Node, comp_id)
    if node is None or node.project_id != project_id:
        return []
    return [node]
