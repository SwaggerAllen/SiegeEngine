"""Phase 11 — translate pending instructions into reducer events.

The apply-queue handler (``backend.graph.queue._apply_instructions_handler``)
walks a project's ``running`` ``pending_instructions`` rows in sequence
order and calls :func:`dispatch_instruction` on each. This module is the
single branch table from instruction type to event emission.

Every branch is narrow: rehydrate the instruction, emit one or more
events via ``append_event``. The reducer drives fanout + staleness +
broadcaster wiring; this module never touches projection rows directly.

Failure modes:
  * :class:`CycleDetected` — raised by the ``AddDependency`` branch
    when the proposed edge would close a dependency cycle. The apply
    handler catches this, marks the instruction ``failed``, and halts
    the queue.
  * :class:`InstructionApplyError` — raised for invariant violations
    (missing nodes, missing edges on a remove, etc.) that the apply
    handler surfaces the same way.
  * Any other ``ReducerError`` or ``ValueError`` bubbles up and is
    handled by the caller.

Rename currently emits ``NodeRenamed`` directly. Phase 11 PR #6 swaps
this branch for an LLM prose-rewrite job enqueue; the seam is
deliberately narrow so that change doesn't touch any other branch.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from backend.graph import events as ev
from backend.graph import instructions as instr
from backend.graph import queries
from backend.graph.handlers.rename_rewrite import RENAME_REWRITE_JOB_TYPE
from backend.graph.ids import Kind, mint
from backend.graph.reducer import append_event
from backend.models.node import Node
from backend.pipeline import queue as pipeline_queue


class InstructionApplyError(RuntimeError):
    """Raised when an instruction can't be applied (missing node / edge / etc.)."""


class CycleDetected(InstructionApplyError):
    """Raised when ``AddDependency`` would close a dependency cycle.

    Carries the cycle path as a list of node ids so the apply handler
    can surface it in the row's ``error`` field for the UI to render.
    """

    def __init__(self, path: list[str]) -> None:
        self.path = path
        arrow = " → ".join(path)
        super().__init__(f"Dependency cycle: {arrow}")


def dispatch_instruction(
    db: Session,
    project_id: str,
    instruction: instr._InstructionBase,
) -> None:
    """Translate ``instruction`` into one or more reducer events.

    Single dispatch function — match/case over ``instruction_type``.
    Each branch is narrow (3–10 lines) so this file stays scannable.
    """
    match instruction:
        case instr.Create():
            _apply_create(db, project_id, instruction)
        case instr.Delete():
            _apply_delete(db, project_id, instruction)
        case instr.Rename():
            _apply_rename(db, project_id, instruction)
        case instr.ReassignMapping():
            _apply_reassign(db, project_id, instruction)
        case instr.Promote():
            _apply_promote(db, project_id, instruction)
        case instr.Demote():
            _apply_demote(db, project_id, instruction)
        case instr.Merge():
            _apply_merge(db, project_id, instruction)
        case instr.Split():
            _apply_split(db, project_id, instruction)
        case instr.AddDependency():
            _apply_add_edge(db, project_id, instruction, edge_type="dependency", check_cycle=True)
        case instr.RemoveDependency():
            _apply_remove_edge(db, project_id, instruction, edge_type="dependency")
        case instr.AddDomainParent():
            _apply_add_edge(
                db, project_id, instruction, edge_type="domain_parent", check_cycle=False
            )
        case instr.RemoveDomainParent():
            _apply_remove_edge(db, project_id, instruction, edge_type="domain_parent")
        case instr.AddPolicyApplication():
            _apply_add_policy_application(db, project_id, instruction)
        case instr.RemovePolicyApplication():
            _apply_remove_policy_application(db, project_id, instruction)
        case _:
            raise InstructionApplyError(
                f"No apply branch for instruction_type={instruction.instruction_type!r}"
            )


# ── Node ops ─────────────────────────────────────────────────────────


def _require_node(db: Session, project_id: str, node_id: str) -> Node:
    node = db.get(Node, node_id)
    if node is None or node.project_id != project_id:
        raise InstructionApplyError(f"Node {node_id!r} not found in project {project_id!r}")
    return node


def _apply_create(db: Session, project_id: str, ins: instr.Create) -> None:
    # User-initiated creates default to ``domain`` kind — presentational
    # creation is rare in the structured-edit UIs and can be retrofitted
    # with an explicit kind field on the instruction if needed.
    # If a parent is given and exists, inherit its kind so sub-creates
    # stay in the same subtree.
    kind: str = "domain"
    if ins.parent_id:
        parent = _require_node(db, project_id, ins.parent_id)
        kind = parent.kind
    append_event(
        db,
        project_id,
        ev.NodeCreated(
            node_id=ins.node_id,
            tier=ins.tier,
            kind=kind,  # type: ignore[arg-type]
            parent_id=ins.parent_id,
            name=ins.name,
        ),
    )


def _apply_delete(db: Session, project_id: str, ins: instr.Delete) -> None:
    _require_node(db, project_id, ins.node_id)
    append_event(db, project_id, ev.NodeDeleted(node_id=ins.node_id))


def _apply_rename(db: Session, project_id: str, ins: instr.Rename) -> None:
    # Rename dispatches to a ``v2.rename_rewrite`` job rather than
    # emitting ``NodeRenamed`` inline. The rewrite handler walks
    # the renamed node's own fragments + every direct consumer
    # (nodes with outgoing reference/dependency edges at the
    # renamed one), rewrites word-boundaried occurrences of the
    # old name, emits ``FragmentUpdated`` per changed fragment,
    # and finally emits ``NodeRenamed`` so the name flips at the
    # same commit as the prose.
    _require_node(db, project_id, ins.node_id)
    pipeline_queue.enqueue(
        db,
        job_type=RENAME_REWRITE_JOB_TYPE,
        payload={
            "project_id": project_id,
            "node_id": ins.node_id,
            "old_name": ins.old_name,
            "new_name": ins.new_name,
        },
    )


def _apply_reassign(db: Session, project_id: str, ins: instr.ReassignMapping) -> None:
    _require_node(db, project_id, ins.node_id)
    if ins.new_parent_id is not None:
        _require_node(db, project_id, ins.new_parent_id)
    append_event(
        db,
        project_id,
        ev.NodeReparented(node_id=ins.node_id, new_parent_id=ins.new_parent_id),
    )


def _apply_promote(db: Session, project_id: str, ins: instr.Promote) -> None:
    _require_node(db, project_id, ins.node_id)
    append_event(
        db,
        project_id,
        ev.NodePromoted(node_id=ins.node_id, new_tier=ins.new_tier),
    )


def _apply_demote(db: Session, project_id: str, ins: instr.Demote) -> None:
    _require_node(db, project_id, ins.node_id)
    if ins.new_parent_id is not None:
        _require_node(db, project_id, ins.new_parent_id)
    # NodeDemoted carries only node_id + new_tier. Parentage is handled
    # by a follow-up NodeReparented when the caller supplies one —
    # keeps the event schema minimal + matches the promote pattern.
    append_event(
        db,
        project_id,
        ev.NodeDemoted(node_id=ins.node_id, new_tier=ins.new_tier),
    )
    if ins.new_parent_id is not None:
        append_event(
            db,
            project_id,
            ev.NodeReparented(node_id=ins.node_id, new_parent_id=ins.new_parent_id),
        )


def _apply_merge(db: Session, project_id: str, ins: instr.Merge) -> None:
    for src in ins.source_ids:
        _require_node(db, project_id, src)
    append_event(
        db,
        project_id,
        ev.NodesMerged(
            source_ids=list(ins.source_ids),
            dest_id=ins.dest_id,
            dest_name=ins.dest_name,
        ),
    )


def _apply_split(db: Session, project_id: str, ins: instr.Split) -> None:
    _require_node(db, project_id, ins.source_id)
    append_event(
        db,
        project_id,
        ev.NodeSplit(
            source_id=ins.source_id,
            dest_ids=list(ins.dest_ids),
            dest_names=list(ins.dest_names),
        ),
    )


# ── Edge ops ─────────────────────────────────────────────────────────


def _apply_add_edge(
    db: Session,
    project_id: str,
    ins: instr.AddDependency | instr.AddDomainParent,
    *,
    edge_type: str,
    check_cycle: bool,
) -> None:
    _require_node(db, project_id, ins.source_id)
    _require_node(db, project_id, ins.target_id)

    # Idempotency: a duplicate add is a no-op, not a failure. The
    # UI may double-click, and the reducer already idempotency-guards
    # EdgeCreated, but we return before minting to avoid orphaning an
    # edge id allocation.
    existing = queries.find_edge_by_endpoints(
        db, project_id, edge_type, ins.source_id, ins.target_id
    )
    if existing is not None:
        return

    if check_cycle:
        cycle = queries.would_create_cycle(db, project_id, ins.source_id, ins.target_id)
        if cycle is not None:
            raise CycleDetected(cycle)

    edge_id = mint(db, Kind.EDGE)
    append_event(
        db,
        project_id,
        ev.EdgeCreated(
            edge_id=edge_id,
            edge_type=edge_type,  # type: ignore[arg-type]
            source_id=ins.source_id,
            target_id=ins.target_id,
        ),
    )


def _apply_remove_edge(
    db: Session,
    project_id: str,
    ins: instr.RemoveDependency | instr.RemoveDomainParent,
    *,
    edge_type: str,
) -> None:
    edge = queries.find_edge_by_endpoints(db, project_id, edge_type, ins.source_id, ins.target_id)
    if edge is None:
        # Idempotent removal — nothing to do. Treat as success rather
        # than failure so discard/redo flows stay simple.
        return
    append_event(db, project_id, ev.EdgeDeleted(edge_id=edge.id))


def _apply_add_policy_application(
    db: Session, project_id: str, ins: instr.AddPolicyApplication
) -> None:
    _require_node(db, project_id, ins.policy_id)
    _require_node(db, project_id, ins.component_id)
    existing = queries.find_edge_by_endpoints(
        db, project_id, "policy_application", ins.policy_id, ins.component_id
    )
    if existing is not None:
        return
    edge_id = mint(db, Kind.EDGE)
    append_event(
        db,
        project_id,
        ev.EdgeCreated(
            edge_id=edge_id,
            edge_type="policy_application",
            source_id=ins.policy_id,
            target_id=ins.component_id,
        ),
    )


def _apply_remove_policy_application(
    db: Session, project_id: str, ins: instr.RemovePolicyApplication
) -> None:
    edge = queries.find_edge_by_endpoints(
        db, project_id, "policy_application", ins.policy_id, ins.component_id
    )
    if edge is None:
        return
    append_event(db, project_id, ev.EdgeDeleted(edge_id=edge.id))
