"""Tier-wide read-only dashboards (info, batches, review/structure summary).

The write surface for these tiers (reset-all, review-sweep, resume,
regen-below-threshold, exploration-sample, full-corpus, batch resume)
was deleted alongside the cohort regenerate endpoint when the v3
authoring skills took over those flows. The read endpoints stay alive
to drive the dashboard's Tier Ops panel, the Cohorts panel's batch
filter, and the per-tier summary panels.

Mount: :mod:`backend.main` includes this router under
``/api/projects``.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Literal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.auth.routes import get_current_user
from backend.database import get_db
from backend.graph.bootstrap_routes import BootstrapTierConfig
from backend.graph.queries import (
    list_edges,
    list_top_level_components,
    topo_sort_comps,
)
from backend.models import Project, User
from backend.models.job import Job
from backend.models.node import Node

logger = logging.getLogger(__name__)

router = APIRouter()

# Literal type for the path parameter. Keep in sync with the
# registry below — adding a new tier means an entry in both places.
TierName = Literal[
    "expansion",
    "requirements",
    "sysarch",
    "comparch",
    "subcomparch",
    "impl",
]

# Structure-summary covers two extra read-only tiers
# (``fanin``, ``references``) that don't have BootstrapTierConfig-
# driven generation but benefit from the same per-tier metadata view.
StructureTierName = Literal[
    "expansion",
    "requirements",
    "sysarch",
    "comparch",
    "subcomparch",
    "impl",
    "fanin",
    "references",
]


def _require_project(db: Session, project_id: str) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


# ── Scope-iterator helpers ─────────────────────────────────────────


def _singleton_scope(_db: Session, _project_id: str) -> list[tuple[str, ...]]:
    """Singleton tier — one node per project, no scope params."""
    return [()]


def _top_level_comp_scope(db: Session, project_id: str) -> list[tuple[str, ...]]:
    """Per-comp tiers (comparch) iterate top-level comps in topo order.

    Uses ``topo_sort_comps`` so the enumeration order matches the
    sidebar's render order.
    """
    comps = list_top_level_components(db, project_id)
    edges = list_edges(db, project_id)
    return [(c.id,) for c in topo_sort_comps(comps, edges)]


def _subcomps_by_parent(db: Session, project_id: str) -> dict[str, list[Node]]:
    """Return all subcomponents grouped by parent top-level comp id."""
    subs = list(
        db.execute(
            select(Node).where(
                Node.project_id == project_id,
                Node.tier == "comp",
                Node.parent_id.is_not(None),
            )
        ).scalars()
    )
    by_parent: dict[str, list[Node]] = {}
    for sub in subs:
        if sub.parent_id is None:
            continue
        by_parent.setdefault(sub.parent_id, []).append(sub)
    return by_parent


def _subcomp_scope(db: Session, project_id: str) -> list[tuple[str, ...]]:
    """Subcomparch iterates every subcomponent under every top-level comp.

    Scope tuple is ``(sub_id,)`` matching ``SUBCOMPARCH_CONFIG.get_node``.
    Ordering: top-level parents in topo order; within each parent the
    subcomps are topo-sorted by their dependency edges.
    """
    edges = list_edges(db, project_id)
    top_levels = topo_sort_comps(list_top_level_components(db, project_id), edges)
    subs_by_parent = _subcomps_by_parent(db, project_id)

    out: list[tuple[str, ...]] = []
    for top in top_levels:
        children = subs_by_parent.get(top.id, [])
        for sub in topo_sort_comps(children, edges):
            out.append((sub.id,))
    return out


def _impl_scope(db: Session, project_id: str) -> list[tuple[str, ...]]:
    """Impl tier scope is ``(owner_id,)`` for each impl-bearing node."""
    impl_owners = set(
        db.execute(
            select(Node.parent_id)
            .where(
                Node.project_id == project_id,
                Node.tier == "impl",
                Node.parent_id.is_not(None),
            )
            .distinct()
        ).scalars()
    )
    edges = list_edges(db, project_id)
    top_levels = topo_sort_comps(list_top_level_components(db, project_id), edges)
    subs_by_parent = _subcomps_by_parent(db, project_id)

    out: list[tuple[str, ...]] = []
    for top in top_levels:
        if top.id in impl_owners:
            out.append((top.id,))
        for sub in topo_sort_comps(subs_by_parent.get(top.id, []), edges):
            if sub.id in impl_owners:
                out.append((sub.id,))
    return out


# ── Tier registry ──────────────────────────────────────────────────
#
# Pulled from routes.py at first use. Lazy import dodges the import
# cycle that would otherwise form.

_ScopeIter = Callable[[Session, str], list[tuple[str, ...]]]


def _registry() -> dict[str, tuple[BootstrapTierConfig, _ScopeIter]]:
    from backend.graph import routes as _routes

    return {
        "expansion": (_routes.EXPANSION_CONFIG, _singleton_scope),
        "requirements": (_routes.REQUIREMENTS_CONFIG, _singleton_scope),
        "sysarch": (_routes.SYSARCH_CONFIG, _singleton_scope),
        "comparch": (_routes.COMPARCH_CONFIG, _top_level_comp_scope),
        "subcomparch": (_routes.SUBCOMPARCH_CONFIG, _subcomp_scope),
        "impl": (_routes.IMPL_CONFIG, _impl_scope),
    }


def _resolve(tier: str) -> tuple[BootstrapTierConfig, _ScopeIter]:
    reg = _registry()
    if tier not in reg:
        raise HTTPException(status_code=404, detail=f"Unknown tier: {tier}")
    return reg[tier]


# ── Batch listing ──────────────────────────────────────────────────


@router.get("/{project_id}/batches")
def list_batches(
    project_id: str,
    tier: str | None = None,
    cohort_id: str | None = None,
    op_type: str | None = None,
    limit: int = 25,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """List recent batches for a project with optional filters.

    Used by the review-summary panel's batch dropdown (filter by
    ``tier``) and by the cohort cycle-history view (filter by
    ``cohort_id`` + ``op_type``). ``cohort_id`` matches against
    ``scope_keys.cohort_id`` JSON-side. Newest first.
    """
    from backend.graph.batches import list_batches_for_tier

    _require_project(db, project_id)
    fetch_limit = limit if cohort_id is None else max(limit, 100)
    rows = list_batches_for_tier(db, project_id, tier, limit=fetch_limit)
    if op_type is not None:
        rows = [b for b in rows if b.op_type == op_type]
    if cohort_id is not None:
        rows = [b for b in rows if (b.scope_keys or {}).get("cohort_id") == cohort_id]
    rows = rows[:limit]
    return {
        "batches": [
            {
                "id": b.id,
                "op_type": b.op_type,
                "tier": b.tier,
                "scope_keys": b.scope_keys,
                "params": b.params,
                "started_at": b.started_at.isoformat() if b.started_at else None,
                "status": b.status,
            }
            for b in rows
        ]
    }


# ── Per-tier read dashboards ───────────────────────────────────────


@router.get("/{project_id}/tiers/{tier}/info")
def get_tier_info(
    project_id: str,
    tier: TierName,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Return the count of nodes in this tier for the project."""
    from backend.models.node import Draft

    _require_project(db, project_id)
    config, iter_scope_ids = _resolve(tier)
    scopes = iter_scope_ids(db, project_id)

    existing = 0
    has_content = 0
    reviewable = 0
    for scope_ids in scopes:
        node = config.get_node(db, project_id, *scope_ids)
        if node is None:
            continue
        existing += 1
        node_has_content = bool((node.content or "").strip())
        if node_has_content:
            has_content += 1
            reviewable += 1
            continue
        pending = (
            db.execute(
                select(Draft.id)
                .where(
                    Draft.project_id == project_id,
                    Draft.target_id == node.id,
                    Draft.status == "pending",
                )
                .limit(1)
            )
            .scalars()
            .first()
        )
        if pending is not None:
            reviewable += 1

    # Average run-time per completed generation job for this tier.
    # Run-time = completed_at - locked_at (excludes queue wait so
    # the number reflects actual generation work). Jobs without
    # both timestamps are skipped. Project filtering happens
    # payload-side because the jobs table has no project_id column.
    completed_gens = list(
        db.execute(
            select(Job).where(
                Job.job_type == config.generate_job_type,
                Job.status == "completed",
            )
        ).scalars()
    )
    durations: list[float] = []
    for j in completed_gens:
        if (j.payload or {}).get("project_id") != project_id:
            continue
        if j.locked_at is None or j.completed_at is None:
            continue
        delta = (j.completed_at - j.locked_at).total_seconds()
        if delta >= 0:
            durations.append(delta)
    avg_seconds = sum(durations) / len(durations) if durations else None

    return {
        "tier": tier,
        "tier_name": config.tier_name,
        "node_count": existing,
        "nodes_with_content": has_content,
        "reviewable_count": reviewable,
        "supports_reset": config.collect_downstream_nodes is not None,
        "supports_review": bool(config.review_job_type),
        "avg_generation_seconds": avg_seconds,
        "generation_sample_size": len(durations),
    }


@router.get("/{project_id}/tiers/{tier}/review-summary")
def get_tier_review_summary(
    project_id: str,
    tier: TierName,
    batch_id: str | None = None,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Aggregate per-tier AI self-review intros + scores.

    Read-only dashboard endpoint. Walks every node in the tier,
    parses each currently-approved draft's ``review_text``, and
    returns a panel-ready bundle. Pass ``?batch_id=<id>`` to scope
    the aggregation to one operation; without it, the summary spans
    every draft of the tier.
    """
    from backend.graph.review_summary import gather_tier_review_summary

    _require_project(db, project_id)
    try:
        summary = gather_tier_review_summary(db, project_id, tier, batch_id=batch_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Unknown tier: {tier}") from exc

    return {
        "tier": summary.tier,
        "tier_name": summary.tier_name,
        "draft_count": summary.draft_count,
        "reviewed_count": summary.reviewed_count,
        "missing_count": summary.missing_count,
        "score_stats": (
            None
            if summary.score_stats is None
            else {
                "min": summary.score_stats.min,
                "max": summary.score_stats.max,
                "mean": summary.score_stats.mean,
                "median": summary.score_stats.median,
            }
        ),
        "score_buckets": {
            "band_0_50": summary.score_buckets.band_0_50,
            "band_51_70": summary.score_buckets.band_51_70,
            "band_71_80": summary.score_buckets.band_71_80,
            "band_81_90": summary.score_buckets.band_81_90,
            "band_91_100": summary.score_buckets.band_91_100,
        },
        "handles_count_mean": summary.handles_count_mean,
        "arch_count_mean": summary.arch_count_mean,
        "reviews": [
            {
                "scope_id": r.scope_id,
                "scope_label": r.scope_label,
                "score": r.score,
                "intro": r.intro,
                "handles_count": r.handles_count,
                "arch_count": r.arch_count,
                "approved_at": r.approved_at,
            }
            for r in summary.reviews
        ],
        "missing": [
            {
                "scope_id": m.scope_id,
                "scope_label": m.scope_label,
                "reason": m.reason,
            }
            for m in summary.missing
        ],
    }


@router.get("/{project_id}/tiers/{tier}/structure-summary")
def get_tier_structure_summary(
    project_id: str,
    tier: StructureTierName,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Per-tier projection-state summary: per-node metrics + aggregates."""
    from backend.graph.tier_structure import (
        gather_tier_structure_summary,
        serialize_summary,
    )

    _require_project(db, project_id)
    try:
        summary = gather_tier_structure_summary(db, project_id, tier)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Unknown tier: {tier}") from exc
    return serialize_summary(summary)
