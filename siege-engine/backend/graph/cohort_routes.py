"""Cohort + sampler-config routes (Phase 14 follow-up).

CRUD on saved cohorts; auto-suggest preview that runs the
stratified sampler against the per-tier structure-summary; per-tier
sampler-config read/write so axis weights can be tuned without a
deploy. Cohort regenerate (Phase 3b) drives iteration cycles by
walking the cohort's parent comps' children at the target tier
under one batch.

The campaign workflow:
1. Browse the per-tier structure-summary.
2. Hit auto-suggest or hand-pick comp IDs.
3. POST a Cohort.
4. POST regenerate to start an iteration cycle (mode=fresh wipes,
   mode=review threads prior_review_text forward).

Mounted under ``/api/projects`` from :mod:`backend.main`.
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.auth.routes import get_current_user
from backend.database import get_db
from backend.graph.batches import mint_batch
from backend.graph.bootstrap_routes import bootstrap_feedback, bootstrap_reset
from backend.graph.cohort_sampler import suggest_cohort
from backend.graph.tier_structure import gather_tier_structure_summary
from backend.models import Project, User
from backend.models.cohort import Cohort
from backend.models.cohort_sampler_config import (
    CohortSamplerConfig,
    default_axes_for_tier,
    mint_cohort_sampler_config_id,
)
from backend.models.node import Node

logger = logging.getLogger(__name__)
router = APIRouter()


def _require_project(db: Session, project_id: str) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def _require_cohort(db: Session, project_id: str, cohort_id: str) -> Cohort:
    cohort = db.get(Cohort, cohort_id)
    if cohort is None or cohort.project_id != project_id:
        raise HTTPException(status_code=404, detail="Cohort not found")
    return cohort


def _serialize_cohort(c: Cohort) -> dict[str, Any]:
    return {
        "id": c.id,
        "project_id": c.project_id,
        "tier": c.tier,
        "name": c.name,
        "comp_ids": list(c.comp_ids or []),
        "version": c.version,
        "archived": c.archived,
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "updated_at": c.updated_at.isoformat() if c.updated_at else None,
    }


def _serialize_sampler_config(cfg: CohortSamplerConfig) -> dict[str, Any]:
    return {
        "id": cfg.id,
        "project_id": cfg.project_id,
        "tier": cfg.tier,
        "axes": cfg.axes or {"axes": []},
        "updated_at": cfg.updated_at.isoformat() if cfg.updated_at else None,
    }


# ── Cohort CRUD ────────────────────────────────────────────────────


class CreateCohortRequest(BaseModel):
    tier: str
    name: str = "canonical"
    comp_ids: list[str] = Field(default_factory=list)


class PatchCohortRequest(BaseModel):
    name: str | None = None
    comp_ids: list[str] | None = None
    archived: bool | None = None


@router.get("/{project_id}/cohorts")
def list_cohorts(
    project_id: str,
    tier: str | None = None,
    archived: bool | None = None,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """List cohorts for a project, optionally filtered by tier + archive."""
    _require_project(db, project_id)
    stmt = select(Cohort).where(Cohort.project_id == project_id)
    if tier is not None:
        stmt = stmt.where(Cohort.tier == tier)
    if archived is not None:
        stmt = stmt.where(Cohort.archived == archived)
    stmt = stmt.order_by(Cohort.archived.asc(), Cohort.created_at.desc())
    rows = list(db.execute(stmt).scalars())
    return {"cohorts": [_serialize_cohort(c) for c in rows]}


@router.post("/{project_id}/cohorts")
def create_cohort(
    project_id: str,
    req: CreateCohortRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> dict[str, Any]:
    _require_project(db, project_id)
    cohort = Cohort(
        project_id=project_id,
        tier=req.tier,
        name=req.name or "canonical",
        comp_ids=list(req.comp_ids or []),
    )
    db.add(cohort)
    db.commit()
    db.refresh(cohort)
    logger.info(
        "cohort.create project=%s tier=%s id=%s comp_count=%d",
        project_id,
        cohort.tier,
        cohort.id,
        len(cohort.comp_ids or []),
    )
    return _serialize_cohort(cohort)


@router.get("/{project_id}/cohorts/{cohort_id}")
def get_cohort(
    project_id: str,
    cohort_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> dict[str, Any]:
    _require_project(db, project_id)
    return _serialize_cohort(_require_cohort(db, project_id, cohort_id))


@router.patch("/{project_id}/cohorts/{cohort_id}")
def patch_cohort(
    project_id: str,
    cohort_id: str,
    req: PatchCohortRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> dict[str, Any]:
    _require_project(db, project_id)
    cohort = _require_cohort(db, project_id, cohort_id)
    if req.name is not None:
        cohort.name = req.name
    if req.comp_ids is not None:
        cohort.comp_ids = list(req.comp_ids)
    if req.archived is not None:
        cohort.archived = req.archived
    db.commit()
    db.refresh(cohort)
    return _serialize_cohort(cohort)


# ── Auto-suggest preview ──────────────────────────────────────────


class AutoSuggestRequest(BaseModel):
    target_size: int = Field(ge=1, le=100)
    exclude_ids: list[str] = Field(default_factory=list)


@router.post("/{project_id}/cohorts/auto-suggest")
def auto_suggest(
    project_id: str,
    tier: str,
    req: AutoSuggestRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Preview suggested comp IDs from the stratified sampler.

    Read-only — does not persist a cohort. ``tier`` is a query
    parameter (e.g. ``?tier=comparch``) since this is a preview
    and isn't tied to an existing cohort row yet. The campaign
    flow is: open structure-summary → preview suggestion → tweak
    → POST the cohort with the picked ids.
    """
    _require_project(db, project_id)
    try:
        summary = gather_tier_structure_summary(db, project_id, tier)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Unknown tier: {tier}") from exc
    cfg = _get_or_create_sampler_config(db, project_id, tier)
    suggestion = suggest_cohort(
        summary,
        cfg,
        target_size=req.target_size,
        exclude_ids=frozenset(req.exclude_ids),
    )
    return {
        "tier": tier,
        "target_size": req.target_size,
        "suggested_ids": suggestion,
        "axes_used": [a.get("key") for a in (cfg.axes or {}).get("axes") or []],
    }


# ── Sampler config ────────────────────────────────────────────────


class PutSamplerConfigRequest(BaseModel):
    axes: dict[str, Any]


def _get_or_create_sampler_config(db: Session, project_id: str, tier: str) -> CohortSamplerConfig:
    """Return the row for (project, tier) or seed defaults + return."""
    cfg = db.execute(
        select(CohortSamplerConfig).where(
            CohortSamplerConfig.project_id == project_id,
            CohortSamplerConfig.tier == tier,
        )
    ).scalar_one_or_none()
    if cfg is not None:
        return cfg
    cfg = CohortSamplerConfig(
        id=mint_cohort_sampler_config_id(),
        project_id=project_id,
        tier=tier,
        axes=default_axes_for_tier(tier),
    )
    db.add(cfg)
    db.commit()
    db.refresh(cfg)
    return cfg


@router.get("/{project_id}/sampler-configs/{tier}")
def get_sampler_config(
    project_id: str,
    tier: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> dict[str, Any]:
    _require_project(db, project_id)
    cfg = _get_or_create_sampler_config(db, project_id, tier)
    return _serialize_sampler_config(cfg)


@router.put("/{project_id}/sampler-configs/{tier}")
def put_sampler_config(
    project_id: str,
    tier: str,
    req: PutSamplerConfigRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> dict[str, Any]:
    _require_project(db, project_id)
    cfg = _get_or_create_sampler_config(db, project_id, tier)
    cfg.axes = req.axes
    db.commit()
    db.refresh(cfg)
    return _serialize_sampler_config(cfg)


@router.post("/{project_id}/sampler-configs/{tier}/reset")
def reset_sampler_config(
    project_id: str,
    tier: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Overwrite this (project, tier) row with the seeded defaults."""
    _require_project(db, project_id)
    cfg = _get_or_create_sampler_config(db, project_id, tier)
    cfg.axes = default_axes_for_tier(tier)
    db.commit()
    db.refresh(cfg)
    return _serialize_sampler_config(cfg)


# ── Regenerate cohort ─────────────────────────────────────────────


# fresh = wipe content + downstream cascade + fresh gen (bootstrap_reset)
# review = discard pending + regen with prior_review_text feeding forward
#          (bootstrap_feedback with force=True)
RegenerateMode = Literal["fresh", "review"]


class RegenerateCohortRequest(BaseModel):
    mode: RegenerateMode


# Maps cohort tier → target tier we generate at when regenerating.
# A comparch cohort drives subcomparch generation; future cohort
# tiers extend this mapping.
TARGET_TIER_BY_COHORT_TIER: dict[str, str] = {
    "comparch": "subcomparch",
}


def _target_subs_for_cohort(db: Session, project_id: str, cohort: Cohort) -> list[Node]:
    """Return the comp child nodes the cohort regenerate operates on.

    For a comparch cohort: subcomponents (tier="comp", parent_id in
    cohort.comp_ids). Future cohort tiers add their own resolution.
    """
    if cohort.tier != "comparch":
        return []
    if not cohort.comp_ids:
        return []
    rows = list(
        db.execute(
            select(Node).where(
                Node.project_id == project_id,
                Node.tier == "comp",
                Node.parent_id.in_(list(cohort.comp_ids)),
            )
        ).scalars()
    )
    return rows


@router.post("/{project_id}/cohorts/{cohort_id}/regenerate")
def regenerate_cohort(
    project_id: str,
    cohort_id: str,
    req: RegenerateCohortRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Start a new iteration cycle for this cohort.

    Mints one Batch (op_type="cohort_regenerate", params records the
    mode + cohort_id) and walks each child of each cohort comp at
    the target tier:

    - ``mode="fresh"`` → ``bootstrap_reset(force=True, batch_id=...)``
      per child. Wipes content + downstream cascade + enqueues fresh
      gen. Tests "what does the prompt produce in isolation."
    - ``mode="review"`` → ``bootstrap_feedback("", force=True,
      batch_id=...)`` per child. Discards pending, keeps approved as
      seed, enqueues regen with prior_review_text. Tests "what does
      the prompt produce when iterating on its own prior critique."

    Skipped scopes (per-child failures) are reported in the result so
    the operator can spot a partial sweep.

    Returns ``{batch_id, mode, target_tier, scopes_total,
    scopes_succeeded, scopes_skipped[]}``.
    """
    _require_project(db, project_id)
    cohort = _require_cohort(db, project_id, cohort_id)
    target_tier = TARGET_TIER_BY_COHORT_TIER.get(cohort.tier)
    if target_tier is None:
        raise HTTPException(
            status_code=400,
            detail=f"Cohort tier {cohort.tier!r} has no regenerate target tier configured",
        )
    target_nodes = _target_subs_for_cohort(db, project_id, cohort)

    op_batch_id = mint_batch(
        db,
        project_id,
        op_type="cohort_regenerate",
        tier=target_tier,
        scope_keys={
            "cohort_id": cohort.id,
            "cohort_comp_ids": list(cohort.comp_ids or []),
            "target_node_count": len(target_nodes),
        },
        params={"mode": req.mode},
    )

    # Resolve the BootstrapTierConfig for the target tier via the
    # tier-ops registry so we reuse the existing per-node helpers.
    from backend.graph.tier_ops_routes import _registry
    from backend.graph.tier_ops_routes import _require_project as _rp

    reg = _registry()
    if target_tier not in reg:
        raise HTTPException(
            status_code=500,
            detail=f"Internal: target tier {target_tier!r} not in tier-ops registry",
        )
    config, _iter = reg[target_tier]

    succeeded = 0
    skipped: list[dict[str, Any]] = []
    for node in target_nodes:
        if node.parent_id is None:
            continue
        # Subcomparch's scope tuple is the single sub id; the parent
        # is reachable via Node.parent_id when needed.
        scope_ids = (node.id,)
        try:
            if req.mode == "fresh":
                bootstrap_reset(
                    db,
                    project_id,
                    scope_ids,
                    config,
                    _rp,
                    force=True,
                    batch_id=op_batch_id,
                )
            else:
                bootstrap_feedback(
                    db,
                    project_id,
                    scope_ids,
                    feedback_text="",
                    config=config,
                    require_project=_rp,
                    batch_id=op_batch_id,
                    force=True,
                )
            succeeded += 1
        except HTTPException as exc:
            skipped.append(
                {
                    "scope_ids": list(scope_ids),
                    "status": exc.status_code,
                    "detail": exc.detail,
                }
            )
    logger.info(
        "cohort.regenerate project=%s cohort=%s mode=%s target_tier=%s succeeded=%d skipped=%d",
        project_id,
        cohort.id,
        req.mode,
        target_tier,
        succeeded,
        len(skipped),
    )
    return {
        "ok": True,
        "batch_id": op_batch_id,
        "cohort_id": cohort.id,
        "mode": req.mode,
        "target_tier": target_tier,
        "scopes_total": len(target_nodes),
        "scopes_succeeded": succeeded,
        "scopes_skipped": skipped,
    }
