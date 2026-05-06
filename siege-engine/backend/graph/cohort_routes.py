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
from backend.graph.bootstrap_routes import bootstrap_feedback
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
        "experimental_comp_ids": list(c.experimental_comp_ids or []),
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


# fresh = wipe content for every node at the tier project-wide,
#         pick a new experimental set, regen cohort + experimental.
#         The new experimental set is stored on cohort.experimental_comp_ids
#         and replaces whatever was there.
# review = regen the cohort + experimental from the most recent fresh
#          via bootstrap_feedback(force=True), threading prior_review_text
#          forward. Working set is stable across reviews.
RegenerateMode = Literal["fresh", "review"]


class RegenerateCohortRequest(BaseModel):
    mode: RegenerateMode
    # Fresh-mode only. Number of new experimental comps to pick from
    # the exclusion pool (cohort.comp_ids ∪ previously-sampled). Set
    # to 0 to fresh-regen canonical only. Ignored for review mode.
    exploration_count: int = Field(default=0, ge=0, le=50)


def _working_set_comp_ids(cohort: Cohort) -> list[str]:
    """Canonical ∪ current experimental — the set that fresh + review
    operate on.

    Order: canonical first, then experimental, deduplicated.
    """
    out: list[str] = []
    seen: set[str] = set()
    for cid in cohort.comp_ids or []:
        if isinstance(cid, str) and cid not in seen:
            seen.add(cid)
            out.append(cid)
    for cid in cohort.experimental_comp_ids or []:
        if isinstance(cid, str) and cid not in seen:
            seen.add(cid)
            out.append(cid)
    return out


def _scope_ids_for_cohort(db: Session, project_id: str, cohort: Cohort) -> list[tuple[str, ...]]:
    """Walk canonical ∪ experimental into scope tuples per cohort.tier."""
    from backend.graph.tier_ops_routes import scope_ids_from_comp

    out: list[tuple[str, ...]] = []
    for cid in _working_set_comp_ids(cohort):
        out.extend(scope_ids_from_comp(db, project_id, cohort.tier, cid))
    return out


def _all_top_level_comp_ids_for_tier(db: Session, project_id: str, tier: str) -> list[str]:
    """Every top-level node-id at the cohort's target tier.

    For ``comparch`` / ``subcomparch`` the unit is top-level
    ``comp_*`` rows. (Subcomparch's scope unit is sub_id but the
    walk starts from a top-level comp via
    ``scope_ids_from_comp``, so the wipe iterator stays at top
    level here too.) Future tiers extend this.
    """
    from backend.graph.queries import list_top_level_components

    if tier in ("comparch", "subcomparch"):
        comps = list_top_level_components(db, project_id)
        return [c.id for c in comps]
    raise HTTPException(
        status_code=501,
        detail=f"cohort fresh-wipe not configured for tier {tier!r}",
    )


def _pick_experimental_comp_ids(
    db: Session,
    project_id: str,
    cohort: Cohort,
    count: int,
) -> list[str]:
    """Pick ``count`` random comps not in cohort.comp_ids and not
    previously sampled at this tier. Returns sorted IDs for
    deterministic test output (rng.shuffle then sort by ID)."""
    import random

    from backend.graph.queries import list_top_level_components
    from backend.graph.tier_ops_routes import _previously_sampled_comp_ids

    if count <= 0:
        return []
    exclude: set[str] = set(_previously_sampled_comp_ids(db, project_id, cohort.tier))
    for cid in cohort.comp_ids or []:
        if isinstance(cid, str):
            exclude.add(cid)
    candidates = [c for c in list_top_level_components(db, project_id) if c.id not in exclude]
    if not candidates:
        return []
    rng = random.Random()
    pool = list(candidates)
    rng.shuffle(pool)
    picked = pool[:count]
    return sorted(c.id for c in picked)


@router.post("/{project_id}/cohorts/{cohort_id}/regenerate")
def regenerate_cohort(
    project_id: str,
    cohort_id: str,
    req: RegenerateCohortRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Start a new iteration cycle for this cohort.

    Mints one Batch (op_type="cohort_regenerate") for the cycle.

    - ``mode="fresh"`` — picks ``exploration_count`` new experimental
      comps (replaces ``cohort.experimental_comp_ids``), wipes
      content for *every* comp at the cohort's tier project-wide
      via :func:`wipe_node` (drafts discarded, downstream nodes
      deleted, in-flight jobs cancelled), then enqueues regen
      jobs only for the cohort's working set
      (canonical ∪ new experimental). Off-working-set comps stay
      wiped until a separate Full Corpus / per-comp action
      repopulates them. Mints a generate_exploration_sample batch
      (no parent_cohort_id, just exclusion-pool history) when
      experimental picks land.
    - ``mode="review"`` — runs ``bootstrap_feedback(force=True)``
      per scope across the same working set. The set comes from
      ``cohort.experimental_comp_ids`` (set by the most recent
      fresh) so reviews thread their prior_review_text forward
      against a stable target.

    Returns the regen batch_id, working-set scope counts, the
    per-scope failure list, and an ``experimental`` block when a
    new experimental sample was picked.
    """
    _require_project(db, project_id)
    cohort = _require_cohort(db, project_id, cohort_id)
    target_tier = cohort.tier

    # Resolve the BootstrapTierConfig for the target tier via the
    # tier-ops registry so we reuse the existing per-scope helpers.
    from backend.graph.batches import mint_batch as _mint_batch
    from backend.graph.bootstrap_routes import build_job_payload, wipe_node
    from backend.graph.tier_ops_routes import _registry, scope_ids_from_comp
    from backend.graph.tier_ops_routes import _require_project as _rp
    from backend.pipeline import queue as pipeline_queue

    reg = _registry()
    if target_tier not in reg:
        raise HTTPException(
            status_code=500,
            detail=f"Internal: target tier {target_tier!r} not in tier-ops registry",
        )
    config, _iter = reg[target_tier]

    op_batch_id = mint_batch(
        db,
        project_id,
        op_type="cohort_regenerate",
        tier=target_tier,
        scope_keys={
            "cohort_id": cohort.id,
            "cohort_comp_ids": list(cohort.comp_ids or []),
        },
        params={"mode": req.mode, "exploration_count": req.exploration_count},
    )

    exploration_result: dict[str, Any] | None = None

    if req.mode == "fresh":
        # 1. Pick the new experimental set (random, post-exclusion).
        new_experimental = _pick_experimental_comp_ids(
            db, project_id, cohort, req.exploration_count
        )

        # 2. Wipe content for every comp at the cohort's tier.
        # bootstrap_reset's downstream-cancel sweep already excludes
        # batch_id from cancellation, so wipes within this fresh
        # batch don't kill the regen jobs we're about to enqueue.
        all_tier_comp_ids = _all_top_level_comp_ids_for_tier(db, project_id, target_tier)
        nodes_wiped = 0
        for comp_id in all_tier_comp_ids:
            for scope in scope_ids_from_comp(db, project_id, target_tier, comp_id):
                summary = wipe_node(db, project_id, scope, config, batch_id=op_batch_id)
                if not summary.get("skipped"):
                    nodes_wiped += 1

        # 3. Replace cohort.experimental_comp_ids with the new picks.
        cohort.experimental_comp_ids = new_experimental
        if new_experimental:
            expl_batch_id = _mint_batch(
                db,
                project_id,
                op_type="generate_exploration_sample",
                tier=target_tier,
                scope_keys={"comp_ids": new_experimental, "parent_cohort_id": cohort.id},
                params={"count": req.exploration_count, "from_cohort_fresh": True},
            )
            exploration_result = {
                "ok": True,
                "batch_id": expl_batch_id,
                "picked_comp_ids": list(new_experimental),
            }
        db.commit()

        # 4. Enqueue regen jobs for the new working set
        # (canonical ∪ new experimental).
        scopes = _scope_ids_for_cohort(db, project_id, cohort)
        succeeded = 0
        skipped: list[dict[str, Any]] = []
        for scope_ids in scopes:
            try:
                pipeline_queue.enqueue(
                    db,
                    job_type=config.generate_job_type,
                    payload=build_job_payload(
                        project_id,
                        scope_ids,
                        scope_payload_keys=config.scope_payload_keys,
                    ),
                    batch_id=op_batch_id,
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
        scopes_total = len(scopes)
    else:
        # Review mode — same working set, bootstrap_feedback per scope.
        scopes = _scope_ids_for_cohort(db, project_id, cohort)
        succeeded = 0
        skipped = []
        for scope_ids in scopes:
            try:
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
        scopes_total = len(scopes)
        nodes_wiped = 0

    logger.info(
        "cohort.regenerate project=%s cohort=%s mode=%s target_tier=%s "
        "succeeded=%d skipped=%d wiped=%d exploration=%s",
        project_id,
        cohort.id,
        req.mode,
        target_tier,
        succeeded,
        len(skipped),
        nodes_wiped,
        "yes" if exploration_result else "no",
    )
    return {
        "ok": True,
        "batch_id": op_batch_id,
        "cohort_id": cohort.id,
        "mode": req.mode,
        "target_tier": target_tier,
        "scopes_total": scopes_total,
        "scopes_succeeded": succeeded,
        "scopes_skipped": skipped,
        "nodes_wiped": nodes_wiped,
        "experimental": exploration_result,
        "experimental_comp_ids": list(cohort.experimental_comp_ids or []),
    }
