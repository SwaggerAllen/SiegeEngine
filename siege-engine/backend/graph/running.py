"""Compute which nodes have an active generation job.

Used by ``/structure`` to set the ``generation_running`` /
``has_error`` / ``needs_user_action`` badge flags on the sidebar
tree. After the per-tier generation handlers retired, the only
job type the worker still serves from the dashboard is
``v2.generate_reference`` (refs are mid-migration to skills); all
other tier nodes report ``False`` for these flags — the dashboard
is read-only for them.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.graph.handlers.generate_reference import GENERATE_REFERENCE_JOB_TYPE
from backend.models.job import Job
from backend.models.node import Node

# Retained for any caller still iterating; per-tier reviews retired.
REVIEW_JOB_TYPES: frozenset[str] = frozenset()

_TIER_JOB_TYPES = frozenset({GENERATE_REFERENCE_JOB_TYPE})


def _refs_with_latest_status(db: Session, project_id: str, status: str) -> set[str]:
    """Return ref ids whose latest generate_reference job has the given status."""
    all_jobs = list(
        db.execute(
            select(Job)
            .where(Job.job_type == GENERATE_REFERENCE_JOB_TYPE)
            .order_by(Job.created_at.desc())
        ).scalars()
    )
    seen: set[str] = set()
    out: set[str] = set()
    for job in all_jobs:
        payload = job.payload or {}
        if payload.get("project_id") != project_id:
            continue
        rid = payload.get("ref_id")
        if not isinstance(rid, str) or rid in seen:
            continue
        seen.add(rid)
        if job.status == status:
            out.add(rid)
    return out


def running_node_ids(db: Session, project_id: str) -> set[str]:
    """Ref ids with a queued or running v2.generate_reference job."""
    active = db.execute(
        select(Job).where(
            Job.job_type == GENERATE_REFERENCE_JOB_TYPE,
            Job.status.in_(("queued", "running")),
        )
    ).scalars()
    out: set[str] = set()
    for job in active:
        payload = job.payload or {}
        if payload.get("project_id") != project_id:
            continue
        rid = payload.get("ref_id")
        if isinstance(rid, str):
            out.add(rid)
    return out


def errored_node_ids(db: Session, project_id: str) -> set[str]:
    """Ref ids whose latest v2.generate_reference job failed."""
    return _refs_with_latest_status(db, project_id, "failed")


def user_action_needed_node_ids(db: Session, project_id: str) -> set[str]:
    """Ref ids that are idle and waiting on a user kick.

    Surfaces as the blue dot in the sidebar tree. A ref is here
    when its latest generate_reference job was cancelled with no
    replacement queued.
    """
    cancelled = _refs_with_latest_status(db, project_id, "cancelled")
    # Strip ones that have content or a pending draft.
    from backend.models.node import Draft

    pending_target_ids: set[str] = set(
        db.execute(
            select(Draft.target_id).where(
                Draft.project_id == project_id,
                Draft.target_type == "node",
                Draft.status == "pending",
            )
        ).scalars()
    )
    nodes_by_id = {
        n.id: n
        for n in db.execute(
            select(Node).where(Node.project_id == project_id, Node.id.in_(cancelled))
        ).scalars()
    }
    out: set[str] = set()
    for rid in cancelled:
        if rid in pending_target_ids:
            continue
        node = nodes_by_id.get(rid)
        if node is None:
            continue
        if (node.content or "").strip():
            continue
        out.add(rid)
    return out
