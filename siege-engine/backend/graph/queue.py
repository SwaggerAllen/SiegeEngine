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

The real handler dispatches each instruction to a per-type applier
that emits events via :func:`backend.graph.reducer.append_event`.
Events flow through the reducer → Phase 9 fanout → staleness +
auto-enqueue pipeline for free; this module just maps instruction
payloads onto the correct event shapes.

Per-instruction error isolation: an exception in one applier marks
that row ``failed`` with error text and continues to the next. The
job itself only fails if the database transaction breaks.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.database import SessionLocal
from backend.graph import events as ev
from backend.graph import instructions as instr_mod
from backend.graph.ids import Kind, mint
from backend.graph.reducer import append_event
from backend.models.node import Edge
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


def discard_one(session: Session, project_id: str, instruction_id: str) -> bool:
    """Discard a single ``queued`` instruction by id.

    Rejects if the row is already ``running`` / ``applied`` / etc.
    Returns True on a successful discard, False if no matching
    queued row exists.
    """
    row = (
        session.query(PendingInstruction)
        .filter(
            PendingInstruction.project_id == project_id,
            PendingInstruction.id == instruction_id,
            PendingInstruction.status == "queued",
        )
        .one_or_none()
    )
    if row is None:
        return False
    row.status = "discarded"
    row.updated_at = datetime.utcnow()
    session.flush()
    return True


def retry_failed(session: Session, project_id: str, instruction_id: str) -> bool:
    """Reset a ``failed`` row back to ``queued`` so Apply picks it up."""
    row = (
        session.query(PendingInstruction)
        .filter(
            PendingInstruction.project_id == project_id,
            PendingInstruction.id == instruction_id,
            PendingInstruction.status == "failed",
        )
        .one_or_none()
    )
    if row is None:
        return False
    row.status = "queued"
    row.error = None
    row.job_id = None
    row.updated_at = datetime.utcnow()
    session.flush()
    return True


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
    for row in rows:
        row.job_id = job_id
    session.commit()
    return job_id


# ── Real apply handler ───────────────────────────────────────────────


class InstructionApplyError(RuntimeError):
    """A single-instruction apply error, captured per row + continued past."""


def _apply_create(db: Session, project_id: str, instr: instr_mod.Create) -> None:
    append_event(
        db,
        project_id,
        ev.NodeCreated(
            node_id=instr.node_id,
            tier=instr.tier,  # type: ignore[arg-type]
            kind="domain",
            parent_id=instr.parent_id,
            name=instr.name,
        ),
    )


def _apply_delete(db: Session, project_id: str, instr: instr_mod.Delete) -> None:
    append_event(db, project_id, ev.NodeDeleted(node_id=instr.node_id))


def _apply_rename(db: Session, project_id: str, instr: instr_mod.Rename) -> None:
    append_event(
        db,
        project_id,
        ev.NodeRenamed(node_id=instr.node_id, new_name=instr.new_name),
    )


def _apply_reassign(db: Session, project_id: str, instr: instr_mod.ReassignMapping) -> None:
    append_event(
        db,
        project_id,
        ev.NodeReparented(node_id=instr.node_id, new_parent_id=instr.new_parent_id),
    )


def _apply_promote(db: Session, project_id: str, instr: instr_mod.Promote) -> None:
    append_event(
        db,
        project_id,
        ev.NodePromoted(node_id=instr.node_id, new_tier=instr.new_tier),  # type: ignore[arg-type]
    )


def _apply_demote(db: Session, project_id: str, instr: instr_mod.Demote) -> None:
    append_event(
        db,
        project_id,
        ev.NodeDemoted(node_id=instr.node_id, new_tier=instr.new_tier),  # type: ignore[arg-type]
    )


def _apply_merge(db: Session, project_id: str, instr: instr_mod.Merge) -> None:
    append_event(
        db,
        project_id,
        ev.NodesMerged(
            source_ids=list(instr.source_ids),
            dest_id=instr.dest_id,
            dest_name=instr.dest_name,
        ),
    )


def _apply_split(db: Session, project_id: str, instr: instr_mod.Split) -> None:
    append_event(
        db,
        project_id,
        ev.NodeSplit(
            source_id=instr.source_id,
            dest_ids=list(instr.dest_ids),
            dest_names=list(instr.dest_names),
        ),
    )


def _apply_add_edge(
    db: Session,
    project_id: str,
    source_id: str,
    target_id: str,
    edge_type: str,
) -> None:
    """Common helper: mint edge id + append EdgeCreated."""
    edge_id = mint(db, Kind.EDGE)
    append_event(
        db,
        project_id,
        ev.EdgeCreated(
            edge_id=edge_id,
            edge_type=edge_type,  # type: ignore[arg-type]
            source_id=source_id,
            target_id=target_id,
        ),
    )


def _apply_remove_edge(
    db: Session,
    project_id: str,
    source_id: str,
    target_id: str,
    edge_type: str,
) -> None:
    """Common helper: resolve edge id from endpoints, then append EdgeDeleted.

    Instructions carry endpoint ids (user-readable) rather than edge
    ids; we look up the concrete edge row by the
    ``(project, edge_type, source, target)`` unique constraint.
    """
    edge = db.execute(
        select(Edge).where(
            Edge.project_id == project_id,
            Edge.edge_type == edge_type,
            Edge.source_id == source_id,
            Edge.target_id == target_id,
        )
    ).scalar_one_or_none()
    if edge is None:
        raise InstructionApplyError(
            f"no {edge_type} edge found with source={source_id!r} target={target_id!r}"
        )
    append_event(db, project_id, ev.EdgeDeleted(edge_id=edge.id))


def _apply_add_dependency(db: Session, project_id: str, instr: instr_mod.AddDependency) -> None:
    _apply_add_edge(db, project_id, instr.source_id, instr.target_id, "dependency")


def _apply_remove_dependency(
    db: Session, project_id: str, instr: instr_mod.RemoveDependency
) -> None:
    _apply_remove_edge(db, project_id, instr.source_id, instr.target_id, "dependency")


def _apply_add_domain_parent(
    db: Session, project_id: str, instr: instr_mod.AddDomainParent
) -> None:
    _apply_add_edge(db, project_id, instr.source_id, instr.target_id, "domain_parent")


def _apply_remove_domain_parent(
    db: Session, project_id: str, instr: instr_mod.RemoveDomainParent
) -> None:
    _apply_remove_edge(db, project_id, instr.source_id, instr.target_id, "domain_parent")


def _apply_add_policy_application(
    db: Session, project_id: str, instr: instr_mod.AddPolicyApplication
) -> None:
    _apply_add_edge(db, project_id, instr.policy_id, instr.component_id, "policy_application")


def _apply_remove_policy_application(
    db: Session, project_id: str, instr: instr_mod.RemovePolicyApplication
) -> None:
    _apply_remove_edge(db, project_id, instr.policy_id, instr.component_id, "policy_application")


def _apply_add_decomposition(
    db: Session, project_id: str, instr: instr_mod.AddDecomposition
) -> None:
    _apply_add_edge(db, project_id, instr.source_id, instr.target_id, "decomposition")


def _apply_remove_decomposition(
    db: Session, project_id: str, instr: instr_mod.RemoveDecomposition
) -> None:
    _apply_remove_edge(db, project_id, instr.source_id, instr.target_id, "decomposition")


_APPLIERS: dict[str, Callable[[Session, str, instr_mod._InstructionBase], None]] = {
    "Create": _apply_create,  # type: ignore[dict-item]
    "Delete": _apply_delete,  # type: ignore[dict-item]
    "Rename": _apply_rename,  # type: ignore[dict-item]
    "ReassignMapping": _apply_reassign,  # type: ignore[dict-item]
    "Promote": _apply_promote,  # type: ignore[dict-item]
    "Demote": _apply_demote,  # type: ignore[dict-item]
    "Merge": _apply_merge,  # type: ignore[dict-item]
    "Split": _apply_split,  # type: ignore[dict-item]
    "AddDependency": _apply_add_dependency,  # type: ignore[dict-item]
    "RemoveDependency": _apply_remove_dependency,  # type: ignore[dict-item]
    "AddDomainParent": _apply_add_domain_parent,  # type: ignore[dict-item]
    "RemoveDomainParent": _apply_remove_domain_parent,  # type: ignore[dict-item]
    "AddPolicyApplication": _apply_add_policy_application,  # type: ignore[dict-item]
    "RemovePolicyApplication": _apply_remove_policy_application,  # type: ignore[dict-item]
    "AddDecomposition": _apply_add_decomposition,  # type: ignore[dict-item]
    "RemoveDecomposition": _apply_remove_decomposition,  # type: ignore[dict-item]
}


async def apply_instructions(payload: dict) -> None:
    """Process every ``running`` instruction for the project in sequence order.

    Each instruction dispatches to its per-type applier, which emits
    events via ``append_event``. The reducer and Phase 9 fanout do the
    rest — staleness, auto-enqueue, broadcast, etc. — without this
    handler needing to know about any of it.

    Error isolation: a failing instruction marks that row ``failed``
    with the error text and the loop continues. The row's in-progress
    DB state is rolled back via a savepoint so partial effects don't
    land.
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
            applier = _APPLIERS.get(row.instruction_type)
            if applier is None:
                row.status = "failed"
                row.error = f"no applier registered for instruction_type {row.instruction_type!r}"
                row.updated_at = now
                continue
            try:
                instruction = instr_mod.instruction_from_row(row.instruction_type, row.payload)
            except Exception as exc:
                row.status = "failed"
                row.error = f"could not rehydrate instruction: {exc}"[:1000]
                row.updated_at = now
                continue

            # ``append_event`` already rolls back its own transaction
            # if ``apply_event`` raises. That rollback unwinds every
            # pending session mutation — including previous rows'
            # ``applied`` status flips — so we commit after each
            # successful instruction to make status changes durable
            # across a later rollback. The commit cadence also means
            # the UI sees per-instruction progress as the job runs.
            try:
                applier(db, project_id, instruction)
            except Exception as exc:
                row.status = "failed"
                row.error = f"applier raised: {exc}"[:1000]
                row.updated_at = now
                db.commit()
                logger.exception(
                    "v2.apply_instructions project=%s seq=%d %s failed",
                    project_id,
                    row.sequence,
                    row.instruction_type,
                )
                continue
            row.status = "applied"
            row.updated_at = now
            db.commit()
            logger.info(
                "v2.apply_instructions project=%s seq=%d applied: %s",
                project_id,
                row.sequence,
                instruction.render(),
            )
    finally:
        db.close()


def register_handler() -> None:
    """Register the real handler with the pipeline job queue.

    Called from ``backend.graph.__init__`` at import time so the
    pipeline worker always has a handler for ``v2.apply_instructions``.
    """
    pipeline_queue.register_handler(APPLY_INSTRUCTIONS_JOB_TYPE, apply_instructions)


# Backwards-compatible alias — tests and a few call sites still import
# ``register_stub_handler``; route both to the real registration.
register_stub_handler = register_handler
