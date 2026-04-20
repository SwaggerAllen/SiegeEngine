"""HTTP surface for the Phase 11 pending-change queue.

One router, four endpoints:

  * ``GET  /{project_id}/queue`` — list queued + running + recently
    applied/failed rows (default last ~100).
  * ``POST /{project_id}/queue/enqueue`` — append one instruction
    to the queue. Body is the discriminated ``Instruction`` union.
  * ``POST /{project_id}/queue/discard`` — per-row (``sequence``) or
    bulk (no body) discard of queued rows.
  * ``POST /{project_id}/queue/apply`` — flip queued rows to running
    and enqueue the ``v2.apply_instructions`` pipeline job. Returns
    the new job id.

Auth is the same project-scoped pattern every other v2 write uses —
``get_current_user`` + project lookup. Router is mounted in
``backend.main`` under the ``/api/projects`` prefix alongside
``graph_router``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from backend.auth.routes import get_current_user
from backend.database import get_db
from backend.graph import queue as queue_mod
from backend.graph.instructions import Instruction
from backend.models import Project, User
from backend.models.pending_instruction import PendingInstruction

router = APIRouter()


# ── Response shapes ─────────────────────────────────────────────────


class QueueRow(BaseModel):
    """Serialized ``pending_instructions`` row for the queue panel."""

    sequence: int
    instruction_type: str
    payload: dict[str, Any]
    status: str
    job_id: str | None
    error: str | None
    created_at: str
    updated_at: str

    @classmethod
    def from_orm_row(cls, row: PendingInstruction) -> "QueueRow":
        return cls(
            sequence=row.sequence,
            instruction_type=row.instruction_type,
            payload=dict(row.payload or {}),
            status=row.status,
            job_id=row.job_id,
            error=row.error,
            created_at=_iso(row.created_at),
            updated_at=_iso(row.updated_at),
        )


class QueueListResponse(BaseModel):
    rows: list[QueueRow]


class EnqueueRequest(BaseModel):
    instruction: Instruction


class EnqueueResponse(BaseModel):
    sequence: int


class DiscardRequest(BaseModel):
    """``sequence=None`` discards every queued row for the project."""

    sequence: int | None = None


class DiscardResponse(BaseModel):
    discarded: int = Field(..., description="Count of rows flipped to discarded.")


class ApplyResponse(BaseModel):
    job_id: str | None = Field(
        ..., description="Job id for the apply run, or null if nothing was queued."
    )


# ── Helpers ─────────────────────────────────────────────────────────


def _iso(dt: datetime | None) -> str:
    return dt.isoformat() if dt else ""


def _require_project(db: Session, project_id: str) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


# ── Routes ──────────────────────────────────────────────────────────


@router.get("/{project_id}/queue", response_model=QueueListResponse)
def list_queue(
    project_id: str,
    limit: int = 100,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> QueueListResponse:
    """Return the project's recent queue rows.

    Ordering: active work (queued + running) first by sequence ascending,
    then the most recent terminal rows (applied / failed / discarded)
    descending. Default limit of 100 covers the panel's default view;
    the panel can request more for the history pane.
    """
    _require_project(db, project_id)

    active = list(
        db.execute(
            select(PendingInstruction)
            .where(
                PendingInstruction.project_id == project_id,
                or_(
                    PendingInstruction.status == "queued",
                    PendingInstruction.status == "running",
                ),
            )
            .order_by(PendingInstruction.sequence.asc())
        ).scalars()
    )
    terminal_budget = max(0, limit - len(active))
    terminal = (
        list(
            db.execute(
                select(PendingInstruction)
                .where(
                    PendingInstruction.project_id == project_id,
                    PendingInstruction.status.in_(("applied", "failed", "discarded")),
                )
                .order_by(PendingInstruction.updated_at.desc())
                .limit(terminal_budget)
            ).scalars()
        )
        if terminal_budget
        else []
    )
    return QueueListResponse(
        rows=[QueueRow.from_orm_row(r) for r in (*active, *terminal)],
    )


@router.post("/{project_id}/queue/enqueue", response_model=EnqueueResponse)
def enqueue(
    project_id: str,
    body: EnqueueRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> EnqueueResponse:
    _require_project(db, project_id)
    sequence = queue_mod.enqueue_instruction(db, project_id, body.instruction)
    db.commit()
    return EnqueueResponse(sequence=sequence)


@router.post("/{project_id}/queue/discard", response_model=DiscardResponse)
def discard(
    project_id: str,
    body: DiscardRequest | None = None,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> DiscardResponse:
    _require_project(db, project_id)
    sequence = body.sequence if body is not None else None
    count = queue_mod.discard_pending(db, project_id, sequence=sequence)
    db.commit()
    return DiscardResponse(discarded=count)


@router.post("/{project_id}/queue/apply", response_model=ApplyResponse)
def apply(
    project_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> ApplyResponse:
    _require_project(db, project_id)
    job_id = queue_mod.apply_pending_queue(db, project_id)
    return ApplyResponse(job_id=job_id)
