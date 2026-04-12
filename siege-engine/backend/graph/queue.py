"""Pending-change queue — layered on top of ``backend.pipeline.queue``.

Instructions produced by UI actions or prose feedback are written here
in ``queued`` status, assigned a sequence number per project. When the
user hits "Apply", :func:`apply_pending_queue` flips the project's
queued rows to ``running`` and enqueues a single
``v2.apply_instructions`` Job on the generic pipeline job queue. That
job executes instructions in ``sequence`` order.

**Sequential execution** is guaranteed by two things:
  1. Only one Job is enqueued per ``apply_pending_queue`` call.
  2. The pipeline job queue runs a single in-process worker.

If the worker ever becomes multi-tenant, this invariant breaks and
this module needs a distributed lock.

The handler registered here is a **stub** — it iterates running rows in
sequence order, logs their rendered form, and flips them to ``applied``
without mutating the graph. The first real vertical slice replaces this
with event-appending execution.
"""

from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.database import SessionLocal
from backend.graph import instructions as instr_mod
from backend.models.pending_instruction import PendingInstruction
from backend.pipeline import queue as pipeline_queue

logger = logging.getLogger(__name__)

APPLY_INSTRUCTIONS_JOB_TYPE = "v2.apply_instructions"


# ── Enqueue / discard / apply ────────────────────────────────────────


def enqueue_instruction(
    session: Session,
    project_id: str,
    instruction: instr_mod._InstructionBase,
) -> int:
    """Write a pending instruction and return its per-project sequence."""
    current_max = session.execute(
        select(func.max(PendingInstruction.sequence)).where(
            PendingInstruction.project_id == project_id
        )
    ).scalar()
    next_seq = (current_max or 0) + 1

    now = datetime.utcnow()
    row = PendingInstruction(
        project_id=project_id,
        sequence=next_seq,
        instruction_type=instruction.instruction_type,
        payload=instruction.model_dump(mode="json"),
        status="queued",
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    session.flush()
    return next_seq


def discard_pending(session: Session, project_id: str) -> int:
    """Discard all ``queued`` instructions for a project.

    Implements the "free undo" — hasn't run yet, so nothing to roll
    back. Returns the number of rows flipped.
    """
    now = datetime.utcnow()
    rows = (
        session.query(PendingInstruction)
        .filter(
            PendingInstruction.project_id == project_id,
            PendingInstruction.status == "queued",
        )
        .all()
    )
    for row in rows:
        row.status = "discarded"
        row.updated_at = now
    session.flush()
    return len(rows)


def apply_pending_queue(session: Session, project_id: str) -> str | None:
    """Flip queued rows to running and enqueue the apply job.

    Returns the newly-enqueued Job id, or ``None`` if there was nothing
    to apply. Commits the session before enqueueing the job so the
    worker sees the running rows on the next poll.
    """
    now = datetime.utcnow()
    rows = (
        session.query(PendingInstruction)
        .filter(
            PendingInstruction.project_id == project_id,
            PendingInstruction.status == "queued",
        )
        .order_by(PendingInstruction.sequence.asc())
        .all()
    )
    if not rows:
        return None

    for row in rows:
        row.status = "running"
        row.updated_at = now
    session.flush()
    session.commit()

    job_id = pipeline_queue.enqueue(
        session,
        job_type=APPLY_INSTRUCTIONS_JOB_TYPE,
        payload={"project_id": project_id},
    )
    # Link the running rows to the job so operators can trace them.
    for row in rows:
        row.job_id = job_id
    session.commit()
    return job_id


# ── Stub handler ─────────────────────────────────────────────────────
#
# STUB: the first real vertical slice replaces this with actual
# event-appending execution. Tests explicitly pin the stub behavior and
# are expected to be rewritten when the stub is replaced.


async def _stub_apply_instructions(payload: dict) -> None:
    """Pop running instructions for a project and mark them applied.

    No graph state is touched. This exists so the pipeline-queue
    plumbing can be exercised end-to-end in tests before the real
    handler arrives.
    """
    project_id = payload.get("project_id")
    if not project_id:
        raise ValueError("v2.apply_instructions payload missing project_id")

    db = SessionLocal()
    try:
        rows = (
            db.query(PendingInstruction)
            .filter(
                PendingInstruction.project_id == project_id,
                PendingInstruction.status == "running",
            )
            .order_by(PendingInstruction.sequence.asc())
            .all()
        )
        now = datetime.utcnow()
        for row in rows:
            try:
                instruction = instr_mod.instruction_from_row(row.instruction_type, row.payload)
                logger.info(
                    "v2.apply_instructions [STUB] project=%s seq=%d: %s",
                    project_id,
                    row.sequence,
                    instruction.render(),
                )
            except Exception as exc:  # pragma: no cover - defensive
                logger.exception("Stub handler failed to render instruction")
                row.status = "failed"
                row.error = str(exc)[:1000]
                row.updated_at = now
                continue
            row.status = "applied"
            row.updated_at = now
        db.commit()
    finally:
        db.close()


def register_stub_handler() -> None:
    """Register the stub handler with the pipeline job queue.

    Called from ``backend.graph.__init__`` at import time so the
    pipeline worker always has a handler for ``v2.apply_instructions``.
    """
    pipeline_queue.register_handler(APPLY_INSTRUCTIONS_JOB_TYPE, _stub_apply_instructions)
