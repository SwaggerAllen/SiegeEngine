"""Generation-queue HTTP surface.

A view + manage layer over the ``jobs`` table. The pending-
instruction queue (``backend.graph.queue_routes``) is a different
concept — that's the *user-authored* change queue. This router
exposes the *generation* queue: every ``v2.*`` job the worker
loop is chewing through.

Endpoints (all scoped under ``/api/projects/{project_id}``):

  * ``GET    /jobs``                       — list jobs for the project
  * ``POST   /jobs/{job_id}/cancel``       — cancel queued or running
  * ``POST   /jobs/{job_id}/reprioritize`` — bump a queued job up/down
  * ``DELETE /jobs/{job_id}``              — remove a terminal/queued row

Project scoping is by payload — every generation job carries
``project_id`` in its payload — since the ``jobs`` table itself
has no FK column. A job is considered to belong to this project
iff ``payload["project_id"] == project_id``.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.auth.routes import get_current_user
from backend.database import get_db
from backend.models import Project, User
from backend.models.job import Job
from backend.pipeline import queue as pipeline_queue

logger = logging.getLogger(__name__)

router = APIRouter()


def _require_project(db: Session, project_id: str) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def _job_belongs_to_project(job: Job, project_id: str) -> bool:
    payload = job.payload or {}
    return payload.get("project_id") == project_id


def _serialize(job: Job) -> dict[str, Any]:
    return {
        "id": job.id,
        "job_type": job.job_type,
        "status": job.status,
        "priority": job.priority,
        "retry_count": job.retry_count,
        "max_retries": job.max_retries,
        "is_deferred": getattr(job, "is_deferred", False),
        "locked_by": job.locked_by,
        "locked_at": job.locked_at.isoformat() if job.locked_at else None,
        "error_message": job.error_message,
        "payload": job.payload,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
    }


@router.get("/{project_id}/jobs")
def list_project_jobs(
    project_id: str,
    status: str | None = None,
    job_type: str | None = None,
    limit: int = 200,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """List jobs for this project.

    Query parameters:

    - ``status`` — comma-separated subset of ``queued,running,
      completed,failed,cancelled``. Empty / unset means "all".
    - ``job_type`` — exact-match filter on ``job_type``.
    - ``limit`` — number of rows returned (default 200, capped at
      1000). Ordering is ``status`` priority (running > queued >
      terminal) then ``created_at`` desc within group.
    """
    _require_project(db, project_id)
    cap = max(1, min(limit, 1000))

    status_filter: set[str] | None = None
    if status:
        status_filter = {s.strip() for s in status.split(",") if s.strip()}

    # Pull a generous candidate set ordered by created_at desc so
    # we capture the most recent jobs across all statuses, then
    # filter project-side. The ``jobs`` table has no project_id
    # column — payload filtering is the only option.
    query = select(Job).order_by(Job.created_at.desc()).limit(cap * 5)
    if job_type:
        query = query.where(Job.job_type == job_type)
    if status_filter:
        query = query.where(Job.status.in_(list(status_filter)))

    rows = list(db.execute(query).scalars())
    matched = [j for j in rows if _job_belongs_to_project(j, project_id)]

    # Sort: running first, then queued in execution order (oldest first),
    # then terminal statuses newest-first as a history view.
    status_order = {
        "running": 0,
        "queued": 1,
        "failed": 2,
        "cancelled": 3,
        "completed": 4,
    }
    fifo_statuses = {"running", "queued"}

    def _sort_key(j: Job) -> tuple[int, float]:
        ts = j.created_at.timestamp() if j.created_at else 0.0
        bucket = status_order.get(j.status, 99)
        return (bucket, ts if j.status in fifo_statuses else -ts)

    matched.sort(key=_sort_key)
    matched = matched[:cap]

    counts: dict[str, int] = {}
    for j in matched:
        counts[j.status] = counts.get(j.status, 0) + 1

    return {
        "jobs": [_serialize(j) for j in matched],
        "total_returned": len(matched),
        "status_counts": counts,
    }


@router.post("/{project_id}/jobs/{job_id}/cancel")
def cancel_project_job(
    project_id: str,
    job_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Cancel a queued or running job.

    Wraps :func:`pipeline_queue.cancel_job` after verifying the
    job belongs to this project.
    """
    _require_project(db, project_id)
    job = db.get(Job, job_id)
    if job is None or not _job_belongs_to_project(job, project_id):
        raise HTTPException(status_code=404, detail="Job not found")
    cancelled = pipeline_queue.cancel_job(db, job_id)
    return {"ok": True, "cancelled": cancelled, "job_id": job_id}


class ReprioritizeBody(BaseModel):
    priority: int = Field(
        ...,
        ge=0,
        le=100,
        description="New priority. Lower wins. 5 = review band, 10 = generation band.",
    )


@router.post("/{project_id}/jobs/{job_id}/reprioritize")
def reprioritize_project_job(
    project_id: str,
    job_id: str,
    body: ReprioritizeBody,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Set the priority of a queued job.

    Only valid while the job is still ``queued`` — once the worker
    has claimed it the priority no longer affects scheduling.
    Returns 409 for non-queued jobs.
    """
    _require_project(db, project_id)
    job = db.get(Job, job_id)
    if job is None or not _job_belongs_to_project(job, project_id):
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != "queued":
        raise HTTPException(
            status_code=409,
            detail=f"Cannot reprioritize a {job.status!r} job",
        )
    job.priority = body.priority
    db.commit()
    return {"ok": True, "job_id": job_id, "priority": job.priority}


@router.delete("/{project_id}/jobs/{job_id}")
def delete_project_job(
    project_id: str,
    job_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Remove a job row.

    Only allowed for terminal states (``completed``, ``failed``,
    ``cancelled``). Queued rows are first cancelled to keep the
    worker's invariants intact, then removed. Running rows must
    be cancelled separately and reach a terminal state before they
    can be deleted — returning 409 otherwise.
    """
    _require_project(db, project_id)
    job = db.get(Job, job_id)
    if job is None or not _job_belongs_to_project(job, project_id):
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status == "running":
        raise HTTPException(
            status_code=409,
            detail="Cancel the job first; it can be deleted once it stops",
        )
    if job.status == "queued":
        # Mark cancelled before deleting so any audit log / cancel
        # listener sees the transition before the row vanishes.
        pipeline_queue.cancel_job(db, job_id)
        db.refresh(job)
    db.delete(job)
    db.commit()
    return {"ok": True, "job_id": job_id}
