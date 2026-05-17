"""Tier-wide bulk operations.

Two project-level endpoints per tier — reset every node in the
tier and re-enqueue generation, or sweep every node with content
through a fresh AI self-review pass. Both wrap the existing
per-node primitives in :mod:`backend.graph.bootstrap_routes` so
the cancellation cascade and the review enqueue logic stay in
one place.

The seven tiers exposed are the BootstrapTierConfig-driven
generation tiers: ``expansion``, ``requirements``, ``sysarch``,
``comparch``, ``subcomparch``, ``impl``. Fanin uses
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
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.auth.routes import get_current_user
from backend.database import get_db
from backend.graph.bootstrap_routes import (
    BootstrapTierConfig,
    bootstrap_feedback,
    bootstrap_reset,
    build_job_payload,
)
from backend.graph.queries import (
    list_edges,
    list_top_level_components,
    topo_sort_comps,
)
from backend.models import Project, User
from backend.models.job import Job
from backend.models.node import Node
from backend.pipeline import queue as pipeline_queue

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
# driven Reset / Review-sweep ops but benefit from the same
# per-tier metadata view. The structure-summary endpoint accepts
# this superset.
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

    Uses ``topo_sort_comps`` so the enqueue order matches
    the sidebar's render order — dependencies and domain parents
    enqueue before the comps that depend on them.
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

    Scope tuple is ``(sub_id,)`` — single element, matching
    ``SUBCOMPARCH_CONFIG.get_node`` (``_get_sub_node(db, project_id,
    sub_id)``) and the per-node-route convention. Subcomps are
    ``tier="comp", parent_id=top_comp_id``; the parent isn't part
    of the scope tuple because every per-node helper looks the
    parent up via ``Node.parent_id`` when needed.

    Order: top-level parents in topo order, and within each parent
    the subcomps are topo-sorted by their ``dependency`` edges
    (and ``domain_parent`` if present, though sibling subs rarely
    have those). Project-wide edges are passed to each per-parent
    sort; ``topo_sort_comps`` filters to edges whose endpoints are
    in the input list, so cross-parent edges are silently ignored.
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
    """Impl tier scope is ``(owner_id,)`` for each impl-bearing node.

    An impl node lives under either a foundation top-level comp or
    a subcomp. Owners are emitted in dispatch order: top-level
    comps in topo order, with each top-level's subcomps interleaved
    in subcomp topo order so a foundation's impl runs before
    anything that depends on it.
    """
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
        "comparch": (_routes.COMPARCH_CONFIG, _top_level_comp_scope),
        "subcomparch": (_routes.SUBCOMPARCH_CONFIG, _subcomp_scope),
        "impl": (_routes.IMPL_CONFIG, _impl_scope),
    }


def _resolve(tier: str) -> tuple[BootstrapTierConfig, _ScopeIter]:
    reg = _registry()
    if tier not in reg:
        raise HTTPException(status_code=404, detail=f"Unknown tier: {tier}")
    return reg[tier]


# ── Batch routes ──────────────────────────────────────────────────


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
    ``cohort_id`` + ``op_type="cohort_regenerate"``). ``cohort_id``
    matches against ``scope_keys.cohort_id`` JSON-side, since
    that's where cohort-regenerate batches stash the cohort
    reference. Newest first.
    """
    from backend.graph.batches import list_batches_for_tier

    _require_project(db, project_id)
    # Pull a wider window when filtering on cohort or op_type so
    # the post-filter still gives the user a useful list. The
    # cohort_id filter happens after the SQL fetch because
    # scope_keys is JSON.
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


@router.post("/{project_id}/batches/{batch_id}/resume")
def resume_batch(
    project_id: str,
    batch_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Re-enqueue jobs from this batch that haven't completed.

    Resume-mode restart: walks the batch's jobs and re-enqueues only
    the ones whose status is not ``completed`` (failed, cancelled,
    or status==queued/running carried over from a worker that died
    mid-flight before status flipped). Deliberately preserves
    completed work — the principle here is "fill the gaps, don't
    throw out partial data".

    The new jobs are stamped with the same ``batch_id`` so a
    subsequent resume sees them as part of the same batch.

    Returns ``{requeued, skipped, total_in_batch}``.
    """
    from backend.graph.batches import gaps_in_batch, get_batch, jobs_in_batch

    _require_project(db, project_id)
    batch = get_batch(db, batch_id)
    if batch is None or batch.project_id != project_id:
        raise HTTPException(status_code=404, detail="Batch not found")
    gaps = gaps_in_batch(db, batch_id)
    total_in_batch = len(jobs_in_batch(db, batch_id))
    requeued: list[str] = []
    for gap in gaps:
        # Re-enqueue with the same payload + batch_id. Drop the
        # parse-validate progress fields (``_current_attempt`` /
        # ``_failed_raw_output``) so the new run starts clean —
        # they live on the prior failed job row for diagnostics.
        clean_payload = {k: v for k, v in (gap.payload or {}).items() if not k.startswith("_")}
        # Keep batch_id in the payload (already there from the
        # original enqueue). The resume's own enqueue passes it
        # through too as the kwarg.
        new_id = pipeline_queue.enqueue(
            db,
            job_type=gap.job_type,
            payload=clean_payload,
            priority=gap.priority,
            max_retries=gap.max_retries,
            batch_id=batch_id,
        )
        requeued.append(new_id)
    logger.info(
        "tier_ops.resume_batch project=%s batch=%s requeued=%d total=%d",
        project_id,
        batch_id,
        len(requeued),
        total_in_batch,
    )
    return {
        "ok": True,
        "batch_id": batch_id,
        "requeued": len(requeued),
        "skipped": total_in_batch - len(requeued),
        "total_in_batch": total_in_batch,
    }


# ── Cohort campaign tier-ops (exploration + full-corpus) ──────────


def scope_ids_from_comp(
    db: Session, project_id: str, target_tier: str, comp_id: str
) -> list[tuple[str, ...]]:
    """Walk from a top-level comp ID to scope tuples for the target tier.

    Mirrors the same walk strategy used by cohort regenerate so all
    three campaign endpoints (regenerate / exploration-sample /
    full-corpus) agree on what "running tier T against comp C" means:

    - ``comparch`` — no walk; ``[(comp_id,)]``.
    - ``subcomparch`` — walk to comp's subs; ``[(sub_id,) per sub]``.
    - ``impl`` — not implemented yet (scaffolded; raises 501).
    """
    if target_tier == "comparch":
        return [(comp_id,)]
    if target_tier == "subcomparch":
        rows = list(
            db.execute(
                select(Node).where(
                    Node.project_id == project_id,
                    Node.tier == "comp",
                    Node.parent_id == comp_id,
                )
            ).scalars()
        )
        return [(s.id,) for s in rows]
    if target_tier == "impl":
        raise HTTPException(
            status_code=501,
            detail="impl tier campaign ops not implemented yet",
        )
    raise HTTPException(
        status_code=400,
        detail=f"Tier {target_tier!r} has no scope walk configured",
    )


def _previously_sampled_comp_ids(db: Session, project_id: str, target_tier: str) -> set[str]:
    """Union of ``scope_keys.comp_ids`` across prior exploration batches at this tier."""
    from backend.models.batch import Batch

    rows = db.execute(
        select(Batch).where(
            Batch.project_id == project_id,
            Batch.op_type == "generate_exploration_sample",
            Batch.tier == target_tier,
        )
    ).scalars()
    out: set[str] = set()
    for b in rows:
        for cid in (b.scope_keys or {}).get("comp_ids") or []:
            if isinstance(cid, str):
                out.add(cid)
    return out


CampaignTier = Literal["comparch", "subcomparch", "impl"]


class ExplorationSampleRequest(BaseModel):
    count: int = Field(ge=1, le=50)
    exclude_cohort_id: str | None = None


def run_exploration_sample(
    db: Session,
    project_id: str,
    tier: str,
    *,
    count: int,
    exclude_cohort_id: str | None,
) -> dict[str, Any]:
    """Pick N random top-level comps and run ``tier``-tier gen on each.

    Shared by the standalone ``/tiers/:tier/exploration-sample``
    endpoint and the fresh-mode cohort regenerate path that runs an
    exploration sample alongside the canonical wipe-and-regen.

    Mints one Batch (``op_type="generate_exploration_sample"``,
    ``Batch.tier`` records the target tier, ``scope_keys.comp_ids``
    records the picks, ``scope_keys.parent_cohort_id`` links to the
    cohort when ``exclude_cohort_id`` is supplied). Returns a
    response dict identical to the route's response payload.
    """
    from backend.graph.batches import mint_batch
    from backend.graph.bootstrap_routes import bootstrap_reset
    from backend.models.cohort import Cohort

    if count < 1:
        raise HTTPException(status_code=400, detail="exploration count must be >= 1")
    config, _iter = _resolve(tier)

    # Build the exclusion pool: prior same-tier exploration batches +
    # the canonical cohort.
    exclude: set[str] = _previously_sampled_comp_ids(db, project_id, tier)
    if exclude_cohort_id is not None:
        cohort = db.get(Cohort, exclude_cohort_id)
        if cohort is not None and cohort.project_id == project_id:
            for cid in cohort.comp_ids or []:
                if isinstance(cid, str):
                    exclude.add(cid)

    # Candidate pool: all top-level comps minus exclusions.
    top_comps = list_top_level_components(db, project_id)
    candidates = [c for c in top_comps if c.id not in exclude]
    if not candidates:
        raise HTTPException(
            status_code=409,
            detail="No candidate comps left — exclusion pool covers every top-level comp",
        )
    # Random pick. Use system random for unpredictability across
    # cycles; tie-break by id deterministic when count >= len(pool).
    import random

    rng = random.Random()
    pool = list(candidates)
    rng.shuffle(pool)
    picked = pool[:count]
    picked_ids = sorted(c.id for c in picked)

    # Stamp parent_cohort_id into scope_keys when called with
    # exclude_cohort_id — that's the link that ties this exploration
    # sample's comps into the cohort's effective working set so
    # subsequent review-mode regens cover the explored comps too.
    scope_keys: dict[str, Any] = {"comp_ids": picked_ids}
    if exclude_cohort_id is not None:
        scope_keys["parent_cohort_id"] = exclude_cohort_id

    op_batch_id = mint_batch(
        db,
        project_id,
        op_type="generate_exploration_sample",
        tier=tier,
        scope_keys=scope_keys,
        params={"count": count, "exclude_cohort_id": exclude_cohort_id},
    )
    # For each picked comp, walk to scope tuples per the target tier
    # and enqueue gen via bootstrap_reset(force=True) — exploration is
    # fresh-mode by design.
    succeeded = 0
    skipped: list[dict[str, Any]] = []
    for comp in picked:
        for scope_ids in scope_ids_from_comp(db, project_id, tier, comp.id):
            try:
                bootstrap_reset(
                    db,
                    project_id,
                    scope_ids,
                    config,
                    _require_project,
                    force=True,
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
    logger.info(
        "tier_ops.exploration_sample project=%s tier=%s picked=%d succeeded=%d skipped=%d",
        project_id,
        tier,
        len(picked_ids),
        succeeded,
        len(skipped),
    )
    return {
        "ok": True,
        "batch_id": op_batch_id,
        "tier": tier,
        "picked_comp_ids": picked_ids,
        "scopes_total": succeeded + len(skipped),
        "scopes_succeeded": succeeded,
        "scopes_skipped": skipped,
    }


@router.post("/{project_id}/tiers/{tier}/exploration-sample")
def generate_exploration_sample(
    project_id: str,
    tier: CampaignTier,
    req: ExplorationSampleRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Pick N random top-level comps not in the cohort and not previously
    sampled, then enqueue ``tier``-tier generation walking from each
    picked comp.

    Thin route wrapper around :func:`run_exploration_sample` —
    fresh-mode cohort regenerate calls the helper directly so the
    same picking + batch-minting + bootstrap_reset machinery runs
    inline alongside the canonical wipe-and-regen.

    ``exclude_cohort_id`` (optional) — comps in this cohort are
    excluded from the candidate pool too. The standard flow passes
    the active canonical cohort's id so exploration never collides
    with the canonical sample.
    """
    _require_project(db, project_id)
    return run_exploration_sample(
        db,
        project_id,
        tier,
        count=req.count,
        exclude_cohort_id=req.exclude_cohort_id,
    )


@router.post("/{project_id}/tiers/{tier}/full-corpus")
def generate_full_corpus(
    project_id: str,
    tier: CampaignTier,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Final-sweep escape hatch — regenerate every entity at the target tier.

    Mints one Batch (``op_type="generate_full_corpus"``, ``Batch.tier``
    records the target tier) and walks every top-level comp's scope
    tuples for the target tier, calling ``bootstrap_reset(force=True)``
    per scope. Intended for use after canonical-cohort cycles plateau
    and the user wants to cover the long tail before declaring the
    campaign done.
    """
    from backend.graph.batches import mint_batch
    from backend.graph.bootstrap_routes import bootstrap_reset

    _require_project(db, project_id)
    config, _iter = _resolve(tier)
    top_comps = list_top_level_components(db, project_id)
    all_scopes: list[tuple[str, ...]] = []
    for comp in top_comps:
        all_scopes.extend(scope_ids_from_comp(db, project_id, tier, comp.id))

    op_batch_id = mint_batch(
        db,
        project_id,
        op_type="generate_full_corpus",
        tier=tier,
        scope_keys={"scope_count": len(all_scopes)},
    )
    succeeded = 0
    skipped: list[dict[str, Any]] = []
    for scope_ids in all_scopes:
        try:
            bootstrap_reset(
                db,
                project_id,
                scope_ids,
                config,
                _require_project,
                force=True,
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
    logger.info(
        "tier_ops.full_corpus project=%s tier=%s succeeded=%d skipped=%d",
        project_id,
        tier,
        succeeded,
        len(skipped),
    )
    return {
        "ok": True,
        "batch_id": op_batch_id,
        "tier": tier,
        "scopes_total": len(all_scopes),
        "scopes_succeeded": succeeded,
        "scopes_skipped": skipped,
    }


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
    #
    # ``reviewable_count`` is the gate for the Review All and
    # Review summary buttons. A scope counts iff it has a pending
    # draft (in-flight regen) or non-empty approved content. The
    # Review summary button reads existing ``review_text`` for both
    # cases. The Review All button now wraps per-scope
    # ``bootstrap_feedback`` and only the pending-draft cases will
    # actually fire a regen — approved-only scopes will 409-skip
    # and report as such in the result line. We keep the broader
    # count here so the button is enabled for the same set the
    # summary button is, and let the per-scope skip messaging
    # explain the partial sweep.
    from backend.models.job import Job
    from backend.models.node import Draft

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
        if node_has_content:
            reviewable += 1
            continue
        # No approved content; check for a pending draft.
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
    # the number reflects actual generation work, not load-induced
    # backpressure). Jobs without both timestamps — historically
    # unusual but possible from older event-log replays — are
    # skipped. Project filtering happens payload-side because the
    # jobs table has no project_id column.
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
    parses each currently-approved draft's ``review_text`` via
    :func:`backend.graph.parsers.review_xml.parse_review`, and
    returns a panel-ready bundle: aggregate stats (min / mean /
    median / max + 4-bucket score distribution), a per-review
    list ordered worst-first, and a "missing" list naming the
    scopes whose review couldn't be summarised + why.

    Pass ``?batch_id=<id>`` to scope the aggregation to drafts
    produced as part of a specific operation (canonical-cohort
    generation cycle, Reset All sweep, etc). Without it, the
    summary spans every draft of the tier.

    The reviews list is what the user copy-pastes into a
    workshop conversation to iterate the tier's prompt: each
    entry has the scope label, score, and intro paragraph.
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
    """Per-tier projection-state summary: per-node metrics + aggregates.

    Read-only dashboard endpoint that surfaces what the tier *looks
    like* — counts, distributions, kind/foundation ratios, multi-
    owner prevalence, content-presence — without parsing review
    text. Used to inform sample / cohort selection and to give each
    tier a "what does this tier currently contain" pane on the
    tier-ops dashboard.

    Eight tiers exposed (the six BootstrapTierConfig tiers plus
    ``fanin`` and ``references``); see
    :mod:`backend.graph.tier_structure` for the per-tier extractors.
    """
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


class RegenBelowThresholdRequest(BaseModel):
    threshold: int = Field(ge=0, le=100)
    mode: Literal["fresh", "review"] = "review"


@router.post("/{project_id}/tiers/{tier}/regen-below-threshold")
def regen_below_threshold(
    project_id: str,
    tier: TierName,
    req: RegenBelowThresholdRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Regen every scope in this tier whose last AI-review score is
    below ``threshold``. Scopes with no parseable review (missing /
    unparsed) are skipped — use Resume Tier or per-node Retry for
    those. The most useful workflow when iterating a prompt is to
    do one full-tier regen + review pass, then target the bottom
    of the score distribution with this endpoint rather than
    burning LLM cost regenerating the whole tier again.

    ``mode``:

    - ``"review"`` (default) — ``bootstrap_feedback("", force=True)``
      per scope. Discards pending, threads ``prior_review_text``
      forward. Use after a full regen + review to iterate the
      bottom of the distribution with the prior critique riding
      forward.
    - ``"fresh"`` — ``bootstrap_reset(force=True)`` per scope.
      Wipes content + downstream cascade. Use when the prior
      output is too far gone to iterate on and you'd rather start
      from scratch.

    Mints one batch (``op_type="regen_below_threshold"``,
    ``params={threshold, mode}``) so the resulting drafts share
    one batch_id and the next review summary can scope to it via
    ``?batch_id=``.
    """
    from backend.graph.batches import mint_batch
    from backend.graph.review_summary import gather_tier_review_summary

    _require_project(db, project_id)
    config, iter_scope_ids = _resolve(tier)

    summary = gather_tier_review_summary(db, project_id, tier)
    score_by_scope_id = {r.scope_id: r.score for r in summary.reviews}

    all_scopes = iter_scope_ids(db, project_id)
    # scope_ids[-1] matches the review-entry's scope_id (see
    # review_summary._scope_id_for, same convention). For singleton
    # tiers scope_ids is empty and the node id falls back; threshold
    # filtering on a singleton tier doesn't apply, so we just skip.
    target_scopes: list[tuple[str, ...]] = []
    skipped_no_review: list[dict[str, Any]] = []
    for scope_ids in all_scopes:
        if not scope_ids:
            continue
        sid = scope_ids[-1]
        if sid not in score_by_scope_id:
            skipped_no_review.append(
                {"scope_ids": list(scope_ids), "reason": "no parseable review"}
            )
            continue
        if score_by_scope_id[sid] < req.threshold:
            target_scopes.append(scope_ids)

    if not target_scopes:
        return {
            "ok": True,
            "tier": tier,
            "threshold": req.threshold,
            "mode": req.mode,
            "scopes_total": 0,
            "scopes_succeeded": 0,
            "scopes_skipped": [],
            "skipped_no_review": skipped_no_review,
            "batch_id": None,
            "detail": "no scopes below threshold",
        }

    op_batch_id = mint_batch(
        db,
        project_id,
        op_type="regen_below_threshold",
        tier=tier,
        scope_keys={"scope_count": len(target_scopes)},
        params={"threshold": req.threshold, "mode": req.mode},
    )

    succeeded = 0
    skipped: list[dict[str, Any]] = []
    for scope_ids in target_scopes:
        try:
            if req.mode == "fresh":
                bootstrap_reset(
                    db,
                    project_id,
                    scope_ids,
                    config,
                    _require_project,
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
                    require_project=_require_project,
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
        "tier_ops.regen_below_threshold project=%s tier=%s threshold=%d mode=%s "
        "targets=%d succeeded=%d skipped=%d no_review=%d",
        project_id,
        tier,
        req.threshold,
        req.mode,
        len(target_scopes),
        succeeded,
        len(skipped),
        len(skipped_no_review),
    )
    return {
        "ok": True,
        "tier": tier,
        "batch_id": op_batch_id,
        "threshold": req.threshold,
        "mode": req.mode,
        "scopes_total": len(target_scopes),
        "scopes_succeeded": succeeded,
        "scopes_skipped": skipped,
        "skipped_no_review": skipped_no_review,
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
    from backend.graph.batches import mint_batch

    op_batch_id = mint_batch(
        db,
        project_id,
        op_type="reset_tier",
        tier=tier,
        scope_keys={"scope_count": len(scopes)},
        params={"force": True},
    )
    succeeded = 0
    succeeded_scopes: list[tuple[str, ...]] = []
    skipped: list[dict[str, Any]] = []
    total_jobs_cancelled = 0
    total_drafts_discarded = 0
    total_nodes_deleted = 0
    for scope_ids in scopes:
        try:
            result = bootstrap_reset(
                db,
                project_id,
                scope_ids,
                config,
                _require_project,
                force=True,
                batch_id=op_batch_id,
            )
        except HTTPException as exc:
            skipped.append(
                {"scope_ids": list(scope_ids), "status": exc.status_code, "detail": exc.detail}
            )
            continue
        succeeded += 1
        succeeded_scopes.append(scope_ids)
        total_jobs_cancelled += int(result.get("jobs_cancelled", 0))
        total_drafts_discarded += int(result.get("drafts_discarded", 0))
        total_nodes_deleted += int(result.get("nodes_deleted", 0))

    # Each per-scope ``bootstrap_reset`` cancels every job of every
    # ``downstream_job_types`` (project-wide) and then enqueues this
    # tier's generate. Some tiers' downstream tuples include their
    # own generate job type, so the next iteration's cancel-pass
    # wipes the previous scope's just-enqueued generate. After the
    # loop only the final scope has a generate queued. Fix: cancel
    # this tier's generate once at the end, then re-enqueue per
    # succeeded scope.
    if succeeded_scopes and config.generate_job_type:
        pipeline_queue.cancel_jobs_by_type(
            db,
            config.generate_job_type,
            project_id=project_id,
        )
        jobs_enqueued = 0
        for scope_ids in succeeded_scopes:
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
            jobs_enqueued += 1
    else:
        jobs_enqueued = 0

    logger.info(
        "tier_ops.reset_tier project=%s tier=%s succeeded=%d skipped=%d enqueued=%d",
        project_id,
        tier,
        succeeded,
        len(skipped),
        jobs_enqueued,
    )
    return {
        "ok": True,
        "tier": tier,
        "scopes_total": len(scopes),
        "scopes_succeeded": succeeded,
        "scopes_skipped": skipped,
        "jobs_cancelled": total_jobs_cancelled,
        "jobs_enqueued": jobs_enqueued,
        "drafts_discarded": total_drafts_discarded,
        "nodes_deleted": total_nodes_deleted,
    }


@router.post("/{project_id}/tiers/{tier}/resume")
def resume_tier(
    project_id: str,
    tier: TierName,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Re-enqueue generation + missing reviews for every unfinished
    scope in this tier.

    Designed for the iterate-on-the-engine workflow: while editing
    SiegeEngine itself, the user kills in-flight jobs to redeploy,
    then wants a single click to pick up unfinished scopes without
    resetting (and discarding) work that did land.

    Two passes per scope:

    1. **Generation.** Fire if the scope has no approved content,
       no pending draft awaiting review, and no active gen job.
       Skips approved + pending-draft scopes (those landed work
       worth keeping).
    2. **Review.** Fire if the tier has a configured ``review_job_type``,
       the scope has reviewable content (approved or pending draft),
       no active review job, and the latest review job either never
       ran or was cancelled. Failed reviews are left alone — those
       have their own per-tier Retry button.

    The two passes are mutually exclusive in practice: a scope
    that needs generation has no content for review to chew on.

    The queue's payload-level dedup makes this safe to spam — a
    second click while the first batch is still queued is a no-op.
    """
    _require_project(db, project_id)
    config, iter_scope_ids = _resolve(tier)

    scopes = iter_scope_ids(db, project_id)
    from backend.graph.batches import mint_batch

    op_batch_id = mint_batch(
        db,
        project_id,
        op_type="resume_tier",
        tier=tier,
        scope_keys={"scope_count": len(scopes)},
    )
    generations_enqueued: list[str] = []
    reviews_enqueued: list[str] = []
    skipped: list[dict[str, Any]] = []
    for scope_ids in scopes:
        node = config.get_node(db, project_id, *scope_ids)
        if node is None:
            skipped.append({"scope_ids": list(scope_ids), "status": 404, "detail": "node missing"})
            continue
        pending = config.get_pending_draft(db, project_id, *scope_ids)
        has_content = bool((node.content or "").strip())

        # ── Generation pass ─────────────────────────────────────
        if not has_content and pending is None:
            payload_filters: dict[str, Any] = {"project_id": project_id}
            for idx, sid in enumerate(scope_ids):
                if idx < len(config.scope_payload_keys):
                    payload_filters[config.scope_payload_keys[idx]] = sid
            active_gen = pipeline_queue.find_active_job(
                db,
                config.generate_job_type,
                payload_filters=payload_filters,
            )
            if active_gen is not None:
                skipped.append(
                    {
                        "scope_ids": list(scope_ids),
                        "status": 409,
                        "detail": f"active gen job {active_gen.id}",
                    }
                )
                continue
            job_id = pipeline_queue.enqueue(
                db,
                job_type=config.generate_job_type,
                payload=build_job_payload(
                    project_id,
                    scope_ids,
                    scope_payload_keys=config.scope_payload_keys,
                ),
                batch_id=op_batch_id,
            )
            generations_enqueued.append(job_id)
            continue

        # ── Review pass ─────────────────────────────────────────
        # Only meaningful for tiers with an AI-review handler.
        if not config.review_job_type:
            skipped.append(
                {
                    "scope_ids": list(scope_ids),
                    "status": 409,
                    "detail": "already approved",
                }
            )
            continue
        # Skip if a review is already in flight for this node.
        active_review = pipeline_queue.find_active_job(
            db,
            config.review_job_type,
            payload_filters={"project_id": project_id, "node_id": node.id},
        )
        if active_review is not None:
            skipped.append(
                {
                    "scope_ids": list(scope_ids),
                    "status": 409,
                    "detail": f"active review job {active_review.id}",
                }
            )
            continue
        # Look up the most recent review job for this node, scanning
        # the recent tail. We treat "never ran" and "last was
        # cancelled" as resume-eligible. A "completed" review is
        # also resume-eligible if its review_text was wiped to empty
        # — that happens when a regen sweep clears the prior review
        # on the pending draft and the follow-up gen job got
        # deferred (so no new draft committed and no new review
        # auto-fired). Failed reviews are always left alone — they
        # have their own per-tier Retry button.
        recent_review_jobs = list(
            db.execute(
                select(Job)
                .where(Job.job_type == config.review_job_type)
                .order_by(Job.created_at.desc())
                .limit(50)
            ).scalars()
        )
        latest_for_node = next(
            (
                j
                for j in recent_review_jobs
                if (j.payload or {}).get("project_id") == project_id
                and (j.payload or {}).get("node_id") == node.id
            ),
            None,
        )
        # Where the current review_text actually lives — on the
        # pending draft for draft-bearing tiers (the wipe-on-regen
        # path leaves an empty string here), or on the node row for
        # fanin (no draft lifecycle).
        if pending is not None:
            current_review_text = pending.review_text or ""
        else:
            current_review_text = getattr(node, "review_text", "") or ""
        review_text_present = bool(current_review_text.strip())
        if (
            latest_for_node is not None
            and latest_for_node.status != "cancelled"
            and (latest_for_node.status == "failed" or review_text_present)
        ):
            # completed-with-content or failed — leave alone
            # (failed has its own per-tier Retry button; completed
            # with non-empty review_text means the result actually
            # landed). completed-with-empty-text falls through to
            # the re-enqueue below — that's the wiped-and-deferred
            # case described above.
            skipped.append(
                {
                    "scope_ids": list(scope_ids),
                    "status": 409,
                    "detail": f"latest review {latest_for_node.status}",
                }
            )
            continue
        # Resolve the draft target — pending draft if present,
        # else None (fanin / approved-only style).
        draft_id = pending.id if pending is not None else None
        review_job_id = pipeline_queue.enqueue(
            db,
            job_type=config.review_job_type,
            payload={
                "project_id": project_id,
                "node_id": node.id,
                "draft_id": draft_id,
            },
            priority=pipeline_queue.REVIEW_JOB_PRIORITY,
            batch_id=op_batch_id,
        )
        reviews_enqueued.append(review_job_id)

    logger.info(
        "tier_ops.resume_tier project=%s tier=%s gens=%d reviews=%d skipped=%d",
        project_id,
        tier,
        len(generations_enqueued),
        len(reviews_enqueued),
        len(skipped),
    )
    return {
        "ok": True,
        "tier": tier,
        "scopes_total": len(scopes),
        "generations_enqueued": len(generations_enqueued),
        "reviews_enqueued": len(reviews_enqueued),
        "jobs_enqueued": len(generations_enqueued) + len(reviews_enqueued),
        "scopes_skipped": skipped,
    }


@router.post("/{project_id}/tiers/{tier}/review-sweep")
def review_sweep_tier(
    project_id: str,
    tier: TierName,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Sweep "Reject & Regenerate" across every scope in this tier.

    Replaces the prior fresh-AI-review behavior. The button now
    behaves identically to clicking the per-node "Reject &
    Regenerate" affordance on each scope: each pending draft's
    ``review_text`` rides forward as ``prior_review_text`` on the
    regen payload, the stale review row gets cleared, any in-
    flight review job for that draft is cancelled, and a fresh
    generation job is enqueued. The post-commit hook on the new
    draft fires the next AI review automatically — no separate
    review enqueue is needed.

    Scopes without a pending draft (already approved + no in-
    flight regen, or never reached pending) raise 409 from
    ``bootstrap_feedback`` and are reported as skipped. Use the
    Reset All button for those — that path forces through the
    approval gate and cascades.
    """
    _require_project(db, project_id)
    config, iter_scope_ids = _resolve(tier)
    if not config.review_job_type:
        raise HTTPException(
            status_code=501,
            detail=f"AI review not supported for tier {tier}",
        )

    scopes = iter_scope_ids(db, project_id)
    from backend.graph.batches import mint_batch

    op_batch_id = mint_batch(
        db,
        project_id,
        op_type="review_sweep_tier",
        tier=tier,
        scope_keys={"scope_count": len(scopes)},
    )
    enqueued: list[str] = []
    skipped: list[dict[str, Any]] = []
    for scope_ids in scopes:
        try:
            result = bootstrap_feedback(
                db,
                project_id,
                scope_ids,
                feedback_text="",
                config=config,
                require_project=_require_project,
                batch_id=op_batch_id,
            )
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
