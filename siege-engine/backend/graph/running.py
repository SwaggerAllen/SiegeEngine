"""Compute which nodes have an active generation job.

Lifted from the nav-tree route handler so /structure can share
the logic. Returns a set of node ids that currently have a
queued or running job whose payload targets that node. Used to
set the ``generation_running`` badge flag for sidebar tree
entries and for the consolidated /structure read.

Layering: this module imports job-type constants from every
handler module that owns one. Handlers do not import this
module — they run inside their own asyncio tasks and have no
reason to query "what's running". Keeping the import direction
one-way avoids circular dependencies at package load.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.graph.handlers.comparch_generation import GENERATE_COMPARCH_JOB_TYPE
from backend.graph.handlers.fanin_generation import GENERATE_FANIN_JOB_TYPE
from backend.graph.handlers.feature_expansion import (
    GENERATE_FEATURE_EXPANSION_JOB_TYPE,
)
from backend.graph.handlers.generate_reference import GENERATE_REFERENCE_JOB_TYPE
from backend.graph.handlers.impl_generation import GENERATE_IMPL_JOB_TYPE
from backend.graph.handlers.requirements_generation import (
    GENERATE_REQUIREMENTS_JOB_TYPE,
)
from backend.graph.handlers.subcomparch_generation import (
    GENERATE_SUBCOMPARCH_JOB_TYPE,
)
from backend.graph.handlers.subreqs_generation import GENERATE_SUBREQS_JOB_TYPE
from backend.graph.handlers.sysarch_generation import GENERATE_SYSARCH_JOB_TYPE
from backend.models.job import Job
from backend.models.node import Node

_TIER_JOB_TYPES = frozenset(
    {
        GENERATE_FEATURE_EXPANSION_JOB_TYPE,
        GENERATE_REQUIREMENTS_JOB_TYPE,
        GENERATE_SYSARCH_JOB_TYPE,
        GENERATE_SUBREQS_JOB_TYPE,
        GENERATE_COMPARCH_JOB_TYPE,
        GENERATE_SUBCOMPARCH_JOB_TYPE,
        GENERATE_FANIN_JOB_TYPE,
        GENERATE_IMPL_JOB_TYPE,
        GENERATE_REFERENCE_JOB_TYPE,
    }
)


def running_node_ids(db: Session, project_id: str) -> set[str]:
    """Return the ids of every node with an active generation job.

    Queries the job queue once for every tier-relevant job type
    then resolves each job's target node via its payload shape.
    Different tiers key their payload differently:

    - ``expansion`` / ``reqs`` / ``sysarch`` — project-level
      singletons, no scope key; we look up the project's
      singleton node of that tier.
    - ``subreqs`` — ``payload.component_id`` is the owning
      comp; the subreqs node is that comp's singleton child.
    - ``comp`` (top-level) — ``payload.component_id`` is the
      comp itself.
    - ``comp`` (subcomponent) — generate_subcomparch with
      ``payload.component_id`` equal to the sub's id.
    - ``fanin`` — ``payload.owner_comp_id`` is the owning
      comp; the fanin node is that comp's singleton child.
    - ``impl`` — ``payload.owner_id`` is the parent comp/sub;
      the impl node is that parent's singleton child.
    - ``reference`` — ``payload.ref_id`` is the ref node
      itself.

    The resolver looks up singleton children via a single
    query per tier-bucket so the caller gets a flat
    ``set[node_id]``.
    """
    active_jobs = list(
        db.execute(
            select(Job).where(
                Job.job_type.in_(_TIER_JOB_TYPES),
                Job.status.in_(("queued", "running")),
            )
        ).scalars()
    )
    if not active_jobs:
        return set()

    # Filter to this project only and bucket by job type so the
    # resolver works in one pass per bucket.
    by_type: dict[str, list[dict]] = {}
    for job in active_jobs:
        payload = job.payload or {}
        if payload.get("project_id") != project_id:
            continue
        by_type.setdefault(job.job_type, []).append(payload)

    if not by_type:
        return set()

    running: set[str] = set()

    # ── Singletons: one node per project per tier ─────────────────
    for job_type, tier in (
        (GENERATE_FEATURE_EXPANSION_JOB_TYPE, "expansion"),
        (GENERATE_REQUIREMENTS_JOB_TYPE, "reqs"),
        (GENERATE_SYSARCH_JOB_TYPE, "sysarch"),
    ):
        if not by_type.get(job_type):
            continue
        node = db.execute(
            select(Node.id).where(
                Node.project_id == project_id,
                Node.tier == tier,
            )
        ).scalar_one_or_none()
        if node is not None:
            running.add(node)

    # ── subreqs: payload.component_id points at owning comp;
    #    subreqs node is that comp's singleton subreqs child.
    subreqs_comp_ids = [
        p.get("component_id")
        for p in by_type.get(GENERATE_SUBREQS_JOB_TYPE, [])
        if isinstance(p.get("component_id"), str)
    ]
    if subreqs_comp_ids:
        rows = db.execute(
            select(Node.id, Node.parent_id).where(
                Node.project_id == project_id,
                Node.tier == "subreqs",
                Node.parent_id.in_(subreqs_comp_ids),
            )
        ).all()
        for node_id, _parent in rows:
            running.add(node_id)

    # ── top-level comp: payload.component_id IS the comp ──────────
    for p in by_type.get(GENERATE_COMPARCH_JOB_TYPE, []):
        cid = p.get("component_id")
        if isinstance(cid, str):
            running.add(cid)

    # ── subcomp: payload.component_id IS the sub ──────────────────
    for p in by_type.get(GENERATE_SUBCOMPARCH_JOB_TYPE, []):
        cid = p.get("component_id")
        if isinstance(cid, str):
            running.add(cid)

    # ── fanin: payload.owner_comp_id points at owning domain comp;
    #    fanin node is that comp's singleton fanin child.
    fanin_comp_ids = [
        p.get("owner_comp_id")
        for p in by_type.get(GENERATE_FANIN_JOB_TYPE, [])
        if isinstance(p.get("owner_comp_id"), str)
    ]
    if fanin_comp_ids:
        rows = db.execute(
            select(Node.id).where(
                Node.project_id == project_id,
                Node.tier == "fanin",
                Node.parent_id.in_(fanin_comp_ids),
            )
        ).scalars()
        for node_id in rows:
            running.add(node_id)

    # ── impl: payload.owner_id points at parent comp/sub;
    #    impl node is that parent's singleton impl child.
    impl_owner_ids = [
        p.get("owner_id")
        for p in by_type.get(GENERATE_IMPL_JOB_TYPE, [])
        if isinstance(p.get("owner_id"), str)
    ]
    if impl_owner_ids:
        rows = db.execute(
            select(Node.id).where(
                Node.project_id == project_id,
                Node.tier == "impl",
                Node.parent_id.in_(impl_owner_ids),
            )
        ).scalars()
        for node_id in rows:
            running.add(node_id)

    # ── reference: payload.ref_id IS the ref node ─────────────────
    for p in by_type.get(GENERATE_REFERENCE_JOB_TYPE, []):
        rid = p.get("ref_id")
        if isinstance(rid, str):
            running.add(rid)

    return running


def errored_node_ids(db: Session, project_id: str) -> set[str]:
    """Return the ids of every node whose latest generation job is failed.

    Parallel to :func:`running_node_ids`. For each tier-relevant
    job type, groups the project's jobs by scope key, takes the
    most recent job per scope, and includes the resolved node if
    that latest job's status is ``"failed"``. A subsequent retry
    (feedback → new queued job) flips the latest status back to
    queued/running and the scope drops out of the errored set —
    so the tree badge clears automatically.
    """
    all_jobs = list(
        db.execute(
            select(Job).where(Job.job_type.in_(_TIER_JOB_TYPES)).order_by(Job.created_at.desc())
        ).scalars()
    )
    by_type: dict[str, list[Job]] = {}
    for job in all_jobs:
        if (job.payload or {}).get("project_id") != project_id:
            continue
        by_type.setdefault(job.job_type, []).append(job)
    if not by_type:
        return set()

    def latest_failed_scopes(jobs: list[Job], scope_key: str) -> set[str]:
        """Walk jobs in desc order; return scope values where the first-seen (latest) job failed."""
        seen: set[str] = set()
        failed: set[str] = set()
        for job in jobs:
            scope = (job.payload or {}).get(scope_key)
            if not isinstance(scope, str):
                continue
            if scope in seen:
                continue
            seen.add(scope)
            if job.status == "failed":
                failed.add(scope)
        return failed

    errored: set[str] = set()

    # ── Singletons: latest job for the type wins (no scope key) ──
    for job_type, tier in (
        (GENERATE_FEATURE_EXPANSION_JOB_TYPE, "expansion"),
        (GENERATE_REQUIREMENTS_JOB_TYPE, "reqs"),
        (GENERATE_SYSARCH_JOB_TYPE, "sysarch"),
    ):
        jobs = by_type.get(job_type, [])
        if not jobs or jobs[0].status != "failed":
            continue
        node_id = db.execute(
            select(Node.id).where(
                Node.project_id == project_id,
                Node.tier == tier,
            )
        ).scalar_one_or_none()
        if node_id is not None:
            errored.add(node_id)

    # ── subreqs: scope=component_id; node = subreqs child of comp
    subreqs_comp_ids = latest_failed_scopes(
        by_type.get(GENERATE_SUBREQS_JOB_TYPE, []), "component_id"
    )
    if subreqs_comp_ids:
        rows = db.execute(
            select(Node.id).where(
                Node.project_id == project_id,
                Node.tier == "subreqs",
                Node.parent_id.in_(subreqs_comp_ids),
            )
        ).scalars()
        for nid in rows:
            errored.add(nid)

    # ── comparch / subcomparch: scope=component_id; node IS the comp
    for cid in latest_failed_scopes(by_type.get(GENERATE_COMPARCH_JOB_TYPE, []), "component_id"):
        errored.add(cid)
    for cid in latest_failed_scopes(by_type.get(GENERATE_SUBCOMPARCH_JOB_TYPE, []), "component_id"):
        errored.add(cid)

    # ── fanin: scope=owner_comp_id; node = fanin child
    fanin_owner_ids = latest_failed_scopes(
        by_type.get(GENERATE_FANIN_JOB_TYPE, []), "owner_comp_id"
    )
    if fanin_owner_ids:
        rows = db.execute(
            select(Node.id).where(
                Node.project_id == project_id,
                Node.tier == "fanin",
                Node.parent_id.in_(fanin_owner_ids),
            )
        ).scalars()
        for nid in rows:
            errored.add(nid)

    # ── impl: scope=owner_id; node = impl child
    impl_owner_ids = latest_failed_scopes(by_type.get(GENERATE_IMPL_JOB_TYPE, []), "owner_id")
    if impl_owner_ids:
        rows = db.execute(
            select(Node.id).where(
                Node.project_id == project_id,
                Node.tier == "impl",
                Node.parent_id.in_(impl_owner_ids),
            )
        ).scalars()
        for nid in rows:
            errored.add(nid)

    # ── reference: scope=ref_id; node IS the ref
    for rid in latest_failed_scopes(by_type.get(GENERATE_REFERENCE_JOB_TYPE, []), "ref_id"):
        errored.add(rid)

    return errored


def cancelled_node_ids(db: Session, project_id: str) -> set[str]:
    """Return the ids of every node whose latest generation job was cancelled.

    Parallel to :func:`errored_node_ids` but filters on
    ``Job.status == "cancelled"``. Surfaces nodes the user (or a
    cascade) explicitly cancelled without a replacement job yet
    — idle, no pending draft, but explicitly waiting on a user
    retry. Drives the blue dot in the sidebar tree.

    Returns empty for nodes whose latest job is queued, running,
    failed, or completed — those live under different badges.
    """
    all_jobs = list(
        db.execute(
            select(Job).where(Job.job_type.in_(_TIER_JOB_TYPES)).order_by(Job.created_at.desc())
        ).scalars()
    )
    by_type: dict[str, list[Job]] = {}
    for job in all_jobs:
        if (job.payload or {}).get("project_id") != project_id:
            continue
        by_type.setdefault(job.job_type, []).append(job)
    if not by_type:
        return set()

    def latest_cancelled_scopes(jobs: list[Job], scope_key: str) -> set[str]:
        seen: set[str] = set()
        cancelled: set[str] = set()
        for job in jobs:
            scope = (job.payload or {}).get(scope_key)
            if not isinstance(scope, str):
                continue
            if scope in seen:
                continue
            seen.add(scope)
            if job.status == "cancelled":
                cancelled.add(scope)
        return cancelled

    cancelled: set[str] = set()

    for job_type, tier in (
        (GENERATE_FEATURE_EXPANSION_JOB_TYPE, "expansion"),
        (GENERATE_REQUIREMENTS_JOB_TYPE, "reqs"),
        (GENERATE_SYSARCH_JOB_TYPE, "sysarch"),
    ):
        jobs = by_type.get(job_type, [])
        if not jobs or jobs[0].status != "cancelled":
            continue
        node_id = db.execute(
            select(Node.id).where(
                Node.project_id == project_id,
                Node.tier == tier,
            )
        ).scalar_one_or_none()
        if node_id is not None:
            cancelled.add(node_id)

    subreqs_comp_ids = latest_cancelled_scopes(
        by_type.get(GENERATE_SUBREQS_JOB_TYPE, []), "component_id"
    )
    if subreqs_comp_ids:
        rows = db.execute(
            select(Node.id).where(
                Node.project_id == project_id,
                Node.tier == "subreqs",
                Node.parent_id.in_(subreqs_comp_ids),
            )
        ).scalars()
        for nid in rows:
            cancelled.add(nid)

    for cid in latest_cancelled_scopes(by_type.get(GENERATE_COMPARCH_JOB_TYPE, []), "component_id"):
        cancelled.add(cid)
    for cid in latest_cancelled_scopes(
        by_type.get(GENERATE_SUBCOMPARCH_JOB_TYPE, []), "component_id"
    ):
        cancelled.add(cid)

    fanin_owner_ids = latest_cancelled_scopes(
        by_type.get(GENERATE_FANIN_JOB_TYPE, []), "owner_comp_id"
    )
    if fanin_owner_ids:
        rows = db.execute(
            select(Node.id).where(
                Node.project_id == project_id,
                Node.tier == "fanin",
                Node.parent_id.in_(fanin_owner_ids),
            )
        ).scalars()
        for nid in rows:
            cancelled.add(nid)

    impl_owner_ids = latest_cancelled_scopes(by_type.get(GENERATE_IMPL_JOB_TYPE, []), "owner_id")
    if impl_owner_ids:
        rows = db.execute(
            select(Node.id).where(
                Node.project_id == project_id,
                Node.tier == "impl",
                Node.parent_id.in_(impl_owner_ids),
            )
        ).scalars()
        for nid in rows:
            cancelled.add(nid)

    for rid in latest_cancelled_scopes(by_type.get(GENERATE_REFERENCE_JOB_TYPE, []), "ref_id"):
        cancelled.add(rid)

    return cancelled
