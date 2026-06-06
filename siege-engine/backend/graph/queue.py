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
this module needs a distributed lock. Sequence allocation in
:func:`enqueue_instruction` is a read-then-write against
``pending_instructions.sequence``; under SQLite WAL single-writer that
is safe, but a multi-process deployment needs either a unique
constraint on ``(project_id, sequence)`` or a server-side serializer.

The handler registered here walks ``running`` rows in sequence order
and translates each instruction to reducer events via
:mod:`backend.graph.apply_instruction`. **Halt on first failure**:
the failed row flips to ``failed`` with its error message; any
subsequent rows that were already flipped to ``running`` flip back to
``queued`` so the user can edit or discard them and retry.
"""

from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.database import SessionLocal
from backend.graph import apply_instruction as apply_mod
from backend.graph import instructions as instr_mod
from backend.graph.broadcast import commit_and_publish, publish_queue_event
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


def discard_pending(session: Session, project_id: str, sequence: int | None = None) -> int:
    """Discard queued instructions for a project.

    ``sequence=None`` (default) discards every ``queued`` row — the
    "Discard all" affordance on the queue panel. Pass a specific
    ``sequence`` to discard just that row (the per-row undo).

    Implements the "free undo" — the row hasn't run, so nothing to
    roll back. Returns the number of rows flipped.
    """
    now = datetime.utcnow()
    q = session.query(PendingInstruction).filter(
        PendingInstruction.project_id == project_id,
        PendingInstruction.status == "queued",
    )
    if sequence is not None:
        q = q.filter(PendingInstruction.sequence == sequence)
    rows = q.all()
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


# ── Apply handler ────────────────────────────────────────────────────


async def _apply_instructions_handler(payload: dict) -> None:
    """Drain ``running`` instructions for a project, translating each to events.

    Reads running rows in sequence order and dispatches each to
    :func:`backend.graph.apply_instruction.dispatch_instruction`. On
    the first failure, the failing row is marked ``failed`` with its
    error, any subsequent ``running`` rows are flipped back to
    ``queued`` (so the user can edit / discard / retry), and the
    loop halts. Events produced by successful instructions are
    flushed via :func:`backend.graph.broadcast.commit_and_publish` so
    SSE subscribers see per-event deltas.
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
        if not rows:
            return

        now = datetime.utcnow()
        halted = False
        affected_node_ids: set[str] = set()
        for row in rows:
            if halted:
                row.status = "queued"
                row.error = None
                row.updated_at = now
                continue
            try:
                instruction = instr_mod.instruction_from_row(row.instruction_type, row.payload)
                apply_mod.dispatch_instruction(db, project_id, instruction)
            except Exception as exc:  # noqa: BLE001 — we want to halt on any failure
                logger.warning(
                    "v2.apply_instructions: project=%s seq=%d failed: %s",
                    project_id,
                    row.sequence,
                    exc,
                )
                row.status = "failed"
                row.error = str(exc)[:1000]
                row.updated_at = now
                halted = True
                continue
            row.status = "applied"
            row.error = None
            row.updated_at = now
            # Collect node_ids the frontend should invalidate when the
            # apply completes. Each instruction payload carries them
            # under one of these well-known keys.
            for key in ("node_id", "source_id", "target_id", "policy_id", "component_id"):
                val = (row.payload or {}).get(key)
                if isinstance(val, str):
                    affected_node_ids.add(val)

        # Fire the cascade-enqueue helper so downstream regens for
        # any synchronously-emitted events get enqueued before we
        # publish.
        if not halted:
            from backend.graph.fanout import flush_pending_regens

            for job_type, payload in flush_pending_regens(db, project_id):
                pipeline_queue.enqueue(db, job_type=job_type, payload=payload)

        commit_and_publish(db, project_id)
        publish_queue_event(
            project_id,
            "QueueFailed" if halted else "QueueApplied",
            node_ids=tuple(sorted(affected_node_ids)),
        )
    finally:
        db.close()


def register_apply_handler() -> None:
    """Register the apply handler with the pipeline job queue.

    Called from ``backend.graph.__init__`` at import time so the
    pipeline worker always has a handler for ``v2.apply_instructions``.
    """
    pipeline_queue.register_handler(APPLY_INSTRUCTIONS_JOB_TYPE, _apply_instructions_handler)
