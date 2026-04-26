"""Tier-wide bulk operations.

Two project-level endpoints per tier — reset every node in the
tier and re-enqueue generation, or sweep every node with content
through a fresh AI self-review pass. Both wrap the existing
per-node primitives in :mod:`backend.graph.bootstrap_routes` so
the cancellation cascade and the review enqueue logic stay in
one place.

The seven tiers exposed are the BootstrapTierConfig-driven
generation tiers: ``expansion``, ``requirements``, ``sysarch``,
``subreqs``, ``comparch``, ``subcomparch``, ``impl``. Fanin uses
a bespoke reset path (no draft cycle) and reference has no reset
at all — both are deliberately out of scope here; they can be
added later by wrapping their bespoke handlers if a use case
materialises.

Mount: :mod:`backend.main` includes this router under
``/api/projects`` alongside the main graph router.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Literal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.auth.routes import get_current_user
from backend.database import get_db
from backend.graph.bootstrap_routes import (
    BootstrapTierConfig,
    bootstrap_reset,
    bootstrap_retry_review,
)
from backend.models import Project, User
from backend.models.node import Node

logger = logging.getLogger(__name__)

router = APIRouter()

# Literal type for the path parameter. Keep in sync with the
# registry below — adding a new tier means an entry in both places.
TierName = Literal[
    "expansion",
    "requirements",
    "sysarch",
    "subreqs",
    "comparch",
    "subcomparch",
    "impl",
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
    """Per-comp tiers (subreqs, comparch) iterate top-level comps."""
    rows = list(
        db.execute(
            select(Node.id)
            .where(
                Node.project_id == project_id,
                Node.tier == "comp",
                Node.parent_id.is_(None),
            )
            .order_by(Node.display_order.asc(), Node.id.asc())
        ).scalars()
    )
    return [(comp_id,) for comp_id in rows]


def _subcomp_scope(db: Session, project_id: str) -> list[tuple[str, ...]]:
    """Subcomparch iterates every subcomponent under every top-level comp.

    Scope tuple is ``(parent_comp_id, sub_id)`` so the per-node
    reset / review-retry handler sees the URL-style scope. Subcomps
    are ``tier="comp", parent_id=top_comp_id``.
    """
    rows = list(
        db.execute(
            select(Node.id, Node.parent_id)
            .where(
                Node.project_id == project_id,
                Node.tier == "comp",
                Node.parent_id.is_not(None),
            )
            .order_by(Node.parent_id.asc(), Node.display_order.asc(), Node.id.asc())
        )
    )
    return [(parent_id, sub_id) for sub_id, parent_id in rows]


def _impl_scope(db: Session, project_id: str) -> list[tuple[str, ...]]:
    """Impl tier scope is ``(owner_id,)`` for each impl-bearing node.

    An impl node lives under either a foundation top-level comp or
    a subcomp. Walk every impl_* node and emit its parent's id as
    the owner — matches IMPL_CONFIG.scope_payload_keys.
    """
    rows = list(
        db.execute(
            select(Node.parent_id)
            .where(
                Node.project_id == project_id,
                Node.tier == "impl",
                Node.parent_id.is_not(None),
            )
            .order_by(Node.parent_id.asc(), Node.id.asc())
        ).scalars()
    )
    # Dedup just in case (one impl per owner is the invariant).
    seen: set[str] = set()
    ordered: list[str] = []
    for owner_id in rows:
        if owner_id not in seen:
            seen.add(owner_id)
            ordered.append(owner_id)
    return [(owner_id,) for owner_id in ordered]


# ── Tier registry ──────────────────────────────────────────────────
#
# Pulled from routes.py at first use. Lazy import dodges the import
# cycle that would otherwise form: routes.py imports many handler
# modules; if this module imported routes.py at the top, those
# handlers would in turn pull this module while routes.py was still
# being defined.


_ScopeIter = Callable[[Session, str], list[tuple[str, ...]]]


def _registry() -> dict[str, tuple[BootstrapTierConfig, _ScopeIter]]:
    from backend.graph import routes as _routes

    return {
        "expansion": (_routes.EXPANSION_CONFIG, _singleton_scope),
        "requirements": (_routes.REQUIREMENTS_CONFIG, _singleton_scope),
        "sysarch": (_routes.SYSARCH_CONFIG, _singleton_scope),
        "subreqs": (_routes.SUBREQS_CONFIG, _top_level_comp_scope),
        "comparch": (_routes.COMPARCH_CONFIG, _top_level_comp_scope),
        "subcomparch": (_routes.SUBCOMPARCH_CONFIG, _subcomp_scope),
        "impl": (_routes.IMPL_CONFIG, _impl_scope),
    }


def _resolve(tier: TierName) -> tuple[BootstrapTierConfig, _ScopeIter]:
    reg = _registry()
    if tier not in reg:
        raise HTTPException(status_code=404, detail=f"Unknown tier: {tier}")
    return reg[tier]


# ── Routes ─────────────────────────────────────────────────────────


@router.get("/{project_id}/tiers/{tier}/info")
def get_tier_info(
    project_id: str,
    tier: TierName,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Return the count of nodes in this tier for the project.

    Drives the tier-ops panel's per-tier row — the count tells the
    user how many resets / reviews a sweep would dispatch.
    """
    _require_project(db, project_id)
    config, iter_scope_ids = _resolve(tier)
    scopes = iter_scope_ids(db, project_id)
    # Filter to scopes whose node actually exists; singleton tiers
    # may have a bootstrapped-but-empty node, which still counts as
    # "exists" so the user can sweep an in-flight tier.
    existing = 0
    has_content = 0
    for scope_ids in scopes:
        node = config.get_node(db, project_id, *scope_ids)
        if node is None:
            continue
        existing += 1
        if (node.content or "").strip():
            has_content += 1
    return {
        "tier": tier,
        "tier_name": config.tier_name,
        "node_count": existing,
        "nodes_with_content": has_content,
        "supports_reset": config.collect_downstream_nodes is not None,
        "supports_review": bool(config.review_job_type),
    }


@router.post("/{project_id}/tiers/{tier}/reset-all")
def reset_tier(
    project_id: str,
    tier: TierName,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Reset every node in this tier and re-enqueue generation.

    Iterates the tier's scope tuples and calls the per-node
    ``bootstrap_reset`` for each. The cancel-downstream-jobs
    primitive is project-scoped and idempotent, so the per-call
    cancellation work compounds harmlessly across iterations.

    Errors on individual scopes (missing node, not approved) are
    swallowed and reported in the response so a partial sweep
    still gets useful information back.
    """
    _require_project(db, project_id)
    config, iter_scope_ids = _resolve(tier)
    if config.collect_downstream_nodes is None:
        raise HTTPException(
            status_code=501,
            detail=f"Reset not supported for tier {tier}",
        )

    scopes = iter_scope_ids(db, project_id)
    succeeded = 0
    skipped: list[dict[str, Any]] = []
    total_jobs_cancelled = 0
    total_drafts_discarded = 0
    total_nodes_deleted = 0
    for scope_ids in scopes:
        try:
            result = bootstrap_reset(db, project_id, scope_ids, config, _require_project)
        except HTTPException as exc:
            skipped.append(
                {"scope_ids": list(scope_ids), "status": exc.status_code, "detail": exc.detail}
            )
            continue
        succeeded += 1
        total_jobs_cancelled += int(result.get("jobs_cancelled", 0))
        total_drafts_discarded += int(result.get("drafts_discarded", 0))
        total_nodes_deleted += int(result.get("nodes_deleted", 0))

    logger.info(
        "tier_ops.reset_tier project=%s tier=%s succeeded=%d skipped=%d",
        project_id,
        tier,
        succeeded,
        len(skipped),
    )
    return {
        "ok": True,
        "tier": tier,
        "scopes_total": len(scopes),
        "scopes_succeeded": succeeded,
        "scopes_skipped": skipped,
        "jobs_cancelled": total_jobs_cancelled,
        "drafts_discarded": total_drafts_discarded,
        "nodes_deleted": total_nodes_deleted,
    }


@router.post("/{project_id}/tiers/{tier}/review-sweep")
def review_sweep_tier(
    project_id: str,
    tier: TierName,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Enqueue a fresh AI self-review for every node in this tier.

    Wraps the existing per-node ``bootstrap_retry_review`` so the
    cancel-stale-review + enqueue logic stays in one place. Nodes
    with no content yet are skipped (the per-node handler raises
    409 in that case, which we report as a skip).
    """
    _require_project(db, project_id)
    config, iter_scope_ids = _resolve(tier)
    if not config.review_job_type:
        raise HTTPException(
            status_code=501,
            detail=f"AI review not supported for tier {tier}",
        )

    scopes = iter_scope_ids(db, project_id)
    enqueued: list[str] = []
    skipped: list[dict[str, Any]] = []
    for scope_ids in scopes:
        try:
            result = bootstrap_retry_review(db, project_id, scope_ids, config, _require_project)
        except HTTPException as exc:
            skipped.append(
                {"scope_ids": list(scope_ids), "status": exc.status_code, "detail": exc.detail}
            )
            continue
        job_id = result.get("job_id")
        if isinstance(job_id, str):
            enqueued.append(job_id)

    logger.info(
        "tier_ops.review_sweep_tier project=%s tier=%s enqueued=%d skipped=%d",
        project_id,
        tier,
        len(enqueued),
        len(skipped),
    )
    return {
        "ok": True,
        "tier": tier,
        "scopes_total": len(scopes),
        "jobs_enqueued": len(enqueued),
        "scopes_skipped": skipped,
    }
