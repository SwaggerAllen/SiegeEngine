"""Cohort + sampler-config routes (Phase 14 follow-up).

CRUD on saved cohorts; auto-suggest preview that runs the
stratified sampler against the per-tier structure-summary; per-tier
sampler-config read/write so axis weights can be tuned without a
deploy.

The campaign workflow (see plan):
1. Browse the per-tier structure-summary.
2. Hit auto-suggest or hand-pick comp IDs.
3. POST a Cohort.
4. (Phase 3b) POST regenerate to start an iteration cycle.

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
from backend.graph.cohort_sampler import suggest_cohort
from backend.graph.tier_structure import gather_tier_structure_summary
from backend.models import Project, User
from backend.models.cohort import Cohort
from backend.models.cohort_sampler_config import (
    CohortSamplerConfig,
    default_axes_for_tier,
    mint_cohort_sampler_config_id,
)

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


# ── Type marker ──────────────────────────────────────────────────


# Use Literal for shared enum-ish values to keep route params typed
# in OpenAPI but otherwise unused at this level.
RegenerateMode = Literal["fresh", "review"]
