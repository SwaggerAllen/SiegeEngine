"""Helpers for the universal batch-id machinery.

Every multi-job operation (Reset All, Regen From Reviews, Resume
Tier) and every per-node operation (single bootstrap_reset /
bootstrap_feedback / bootstrap_approve / retry-review) calls
:func:`mint_batch` at the top of the route to stamp a fresh
``Batch`` row. The minted ``batch_id`` then threads through every
:func:`backend.pipeline.queue.enqueue` call the operation issues
(stamping ``Job.batch_id``) and through the bootstrap-generation
handler (stamping ``Draft.batch_id`` so multi-draft tier-ops
share one batch on their resulting drafts).

Restart resume reads :func:`gaps_in_batch` to find the operation's
jobs that haven't completed yet — the resume endpoint re-enqueues
only those, deliberately *keeping* completed work intact (per the
"don't throw out partial data" principle in the plan).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models.batch import Batch, mint_batch_id
from backend.models.job import Job


def mint_batch(
    db: Session,
    project_id: str,
    *,
    op_type: str,
    tier: str | None = None,
    scope_keys: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
    initiator_user_id: str | None = None,
) -> str:
    """Insert a Batch row and return its id.

    Caller commits — this function only flushes so a subsequent
    ``enqueue`` can carry the batch_id. The route's overall
    transaction commits at the usual point.
    """
    batch = Batch(
        id=mint_batch_id(),
        project_id=project_id,
        op_type=op_type,
        tier=tier,
        scope_keys=scope_keys or {},
        params=params or {},
        initiator_user_id=initiator_user_id,
    )
    db.add(batch)
    db.flush()
    return batch.id


def get_batch(db: Session, batch_id: str) -> Batch | None:
    return db.get(Batch, batch_id)


def list_batches_for_tier(
    db: Session,
    project_id: str,
    tier: str | None,
    *,
    limit: int = 25,
) -> list[Batch]:
    """Return batches for a tier, newest first.

    ``tier=None`` matches every batch. Used by the review-summary
    panel's batch dropdown to populate selectable scopes.
    """
    stmt = select(Batch).where(Batch.project_id == project_id)
    if tier is not None:
        stmt = stmt.where(Batch.tier == tier)
    stmt = stmt.order_by(Batch.started_at.desc()).limit(limit)
    return list(db.execute(stmt).scalars())


def gaps_in_batch(db: Session, batch_id: str) -> list[Job]:
    """Return jobs in the batch that aren't completed.

    "Completed" here means ``status="completed"`` (succeeded
    cleanly). Cancelled, failed, queued, and running jobs are all
    treated as gaps the resume operation should re-enqueue (running
    is unusual since the worker reaps them at startup, but a stuck
    long-running job that the user manually restarts the worker
    around is a legitimate resume case).
    """
    stmt = (
        select(Job)
        .where(Job.batch_id == batch_id)
        .where(Job.status != "completed")
        .order_by(Job.created_at.asc())
    )
    return list(db.execute(stmt).scalars())


def jobs_in_batch(db: Session, batch_id: str) -> list[Job]:
    """Return all jobs stamped with this batch_id, oldest first."""
    stmt = select(Job).where(Job.batch_id == batch_id).order_by(Job.created_at.asc())
    return list(db.execute(stmt).scalars())
