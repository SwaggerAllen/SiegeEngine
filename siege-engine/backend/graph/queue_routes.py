"""HTTP endpoints for the pending-change queue.

Six routes, all project-scoped under ``/projects/{project_id}/queue``:

- ``GET /`` — list queued / running / failed / recently-applied rows.
- ``POST /enqueue`` — add one instruction.
- ``POST /apply`` — flip queued rows to running + enqueue the
  ``v2.apply_instructions`` job.
- ``POST /discard`` — discard all queued rows.
- ``DELETE /{instruction_id}`` — discard one queued row.
- ``POST /{instruction_id}/retry`` — reset a failed row to queued.

Business logic lives in :mod:`backend.graph.queue`; these handlers
just validate requests and serialize responses.
"""

from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.auth.routes import get_current_user
from backend.database import get_db
from backend.graph import queue as queue_mod
from backend.graph.instructions import Instruction
from backend.models.auth import User
from backend.models.pending_instruction import PendingInstruction
from backend.models.project import Project
from backend.pipeline import queue as pipeline_queue

logger = logging.getLogger(__name__)

router = APIRouter()


# ── Request / response models ────────────────────────────────────────


class InstructionRow(BaseModel):
    """One pending-instruction row as served over HTTP."""

    id: str
    sequence: int
    instruction_type: str
    payload: dict
    status: Literal["queued", "running", "applied", "discarded", "failed"]
    error: str | None
    created_at: str
    updated_at: str
    rendered: str

    @classmethod
    def from_row(cls, row: PendingInstruction) -> InstructionRow:
        from backend.graph import instructions as instr_mod

        try:
            rendered = instr_mod.instruction_from_row(row.instruction_type, row.payload).render()
        except Exception:
            rendered = f"(could not render {row.instruction_type})"
        return cls(
            id=row.id,
            sequence=row.sequence,
            instruction_type=row.instruction_type,
            payload=row.payload,
            status=row.status,  # type: ignore[arg-type]
            error=row.error,
            created_at=row.created_at.isoformat(),
            updated_at=row.updated_at.isoformat(),
            rendered=rendered,
        )


class QueueStateResponse(BaseModel):
    """Grouped queue snapshot for the UI."""

    queued: list[InstructionRow]
    running: list[InstructionRow]
    failed: list[InstructionRow]
    recent_applied: list[InstructionRow]
    apply_in_flight: bool


class EnqueueRequest(BaseModel):
    instruction: Instruction = Field(
        ...,
        description="One of the 16 instruction types; discriminated by instruction_type.",
    )


class EnqueueResponse(BaseModel):
    id: str
    sequence: int


class ApplyResponse(BaseModel):
    job_id: str | None
    applied: int


class DiscardAllResponse(BaseModel):
    discarded: int


class AckResponse(BaseModel):
    ok: bool


# ── Helpers ──────────────────────────────────────────────────────────


def _require_project(db: Session, project_id: str) -> None:
    if db.get(Project, project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")


def _apply_in_flight(db: Session, project_id: str) -> bool:
    """True iff there's a queued/running ``v2.apply_instructions`` job
    for this project. Blocks a second concurrent Apply."""
    from sqlalchemy import select

    from backend.models.job import Job

    rows = (
        db.execute(
            select(Job).where(
                Job.job_type == queue_mod.APPLY_INSTRUCTIONS_JOB_TYPE,
                Job.status.in_(("queued", "running")),
            )
        )
        .scalars()
        .all()
    )
    return any((r.payload or {}).get("project_id") == project_id for r in rows)


# ── Routes ───────────────────────────────────────────────────────────


@router.get("/{project_id}/queue", response_model=QueueStateResponse)
def get_queue(
    project_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> QueueStateResponse:
    """Return pending + in-flight + failed + recently-applied rows."""
    _require_project(db, project_id)

    rows = (
        db.query(PendingInstruction)
        .filter(PendingInstruction.project_id == project_id)
        .order_by(PendingInstruction.sequence.asc())
        .all()
    )

    def by_status(status: str) -> list[InstructionRow]:
        return [InstructionRow.from_row(r) for r in rows if r.status == status]

    # Recent-applied: last 50 applied rows by updated_at descending.
    applied = sorted(
        (r for r in rows if r.status == "applied"),
        key=lambda r: r.updated_at,
        reverse=True,
    )[:50]

    return QueueStateResponse(
        queued=by_status("queued"),
        running=by_status("running"),
        failed=by_status("failed"),
        recent_applied=[InstructionRow.from_row(r) for r in applied],
        apply_in_flight=_apply_in_flight(db, project_id),
    )


@router.post("/{project_id}/queue/enqueue", response_model=EnqueueResponse)
def enqueue(
    project_id: str,
    body: EnqueueRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> EnqueueResponse:
    """Add one instruction to the queue. Returns the new row's id + seq."""
    _require_project(db, project_id)
    seq = queue_mod.enqueue_instruction(db, project_id, body.instruction)
    db.commit()
    # Find the row we just inserted so the response carries its id.
    row = (
        db.query(PendingInstruction)
        .filter(
            PendingInstruction.project_id == project_id,
            PendingInstruction.sequence == seq,
        )
        .one()
    )
    return EnqueueResponse(id=row.id, sequence=seq)


@router.post("/{project_id}/queue/apply", response_model=ApplyResponse)
def apply(
    project_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> ApplyResponse:
    """Flip queued rows to running + enqueue the apply job.

    409 if an apply job is already in flight for this project.
    """
    _require_project(db, project_id)
    if _apply_in_flight(db, project_id):
        raise HTTPException(
            status_code=409,
            detail="An apply job is already in flight for this project.",
        )
    queued_count = (
        db.query(PendingInstruction)
        .filter(
            PendingInstruction.project_id == project_id,
            PendingInstruction.status == "queued",
        )
        .count()
    )
    job_id = queue_mod.apply_pending_queue(db, project_id)
    return ApplyResponse(job_id=job_id, applied=queued_count)


@router.post("/{project_id}/queue/discard", response_model=DiscardAllResponse)
def discard_all(
    project_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> DiscardAllResponse:
    """Discard every queued row for the project."""
    _require_project(db, project_id)
    count = queue_mod.discard_pending(db, project_id)
    db.commit()
    return DiscardAllResponse(discarded=count)


@router.delete("/{project_id}/queue/{instruction_id}", response_model=AckResponse)
def discard_one(
    project_id: str,
    instruction_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> AckResponse:
    """Discard a single queued row by id.

    404 if the id doesn't exist in this project, 409 if the row is
    past the ``queued`` state (running / applied / failed /
    discarded — all past the undo window).
    """
    _require_project(db, project_id)
    row = (
        db.query(PendingInstruction)
        .filter(
            PendingInstruction.project_id == project_id,
            PendingInstruction.id == instruction_id,
        )
        .one_or_none()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Instruction not found")
    if row.status != "queued":
        raise HTTPException(
            status_code=409,
            detail=f"Instruction is {row.status!r}; only queued rows can be discarded.",
        )
    queue_mod.discard_one(db, project_id, instruction_id)
    db.commit()
    return AckResponse(ok=True)


@router.post("/{project_id}/queue/{instruction_id}/retry", response_model=AckResponse)
def retry(
    project_id: str,
    instruction_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> AckResponse:
    """Reset a failed instruction to ``queued`` so the next Apply runs it."""
    _require_project(db, project_id)
    row = (
        db.query(PendingInstruction)
        .filter(
            PendingInstruction.project_id == project_id,
            PendingInstruction.id == instruction_id,
        )
        .one_or_none()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Instruction not found")
    if row.status != "failed":
        raise HTTPException(
            status_code=409,
            detail=f"Instruction is {row.status!r}; only failed rows can be retried.",
        )
    queue_mod.retry_failed(db, project_id, instruction_id)
    db.commit()
    return AckResponse(ok=True)


__all__ = ["router"]


# Keep pipeline_queue import alive for linters — some code paths
# pattern-match on module presence.
_ = pipeline_queue
