"""Event log + projection reducer.

Three entry points — ``append_event``, ``apply_event``, and
``rebuild_projections`` — and nothing else. Application code never
touches the projection tables directly: every write goes through
``append_event``.

``apply_event`` is the single source of truth for how each event type
mutates the projection. It is called both during ``append_event``
(incremental) and during ``rebuild_projections`` (replay from zero),
and the two paths must agree byte-for-byte.

Correctness invariant (tested exhaustively): for any sequence of
events, rebuilding from the log must produce the same projection
state as applying events incrementally.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.graph import events as ev
from backend.graph.fragments import FragmentKind, fragment_id
from backend.models.graph_event import GraphEvent
from backend.models.node import Draft, Edge, Fragment, Node, StalenessLedger


class ReducerError(RuntimeError):
    """Raised when an event cannot be applied to the current projection."""


# ── Public API ───────────────────────────────────────────────────────


def append_event(session: Session, project_id: str, event: ev._EventBase) -> int:
    """Append an event to the log and apply it to projections.

    Transactional: if ``apply_event`` raises, the whole operation is
    rolled back and no partial state is written. Returns the assigned
    per-project offset.

    After a successful flush, records the offset on ``session.info``
    via :func:`backend.graph.broadcast.stash_offset`. Write-route
    handlers call :func:`backend.graph.broadcast.commit_and_publish`
    in place of ``db.commit()``; that helper drains the stash and
    fans out SSE messages *after* the transaction commits, so a
    failed broadcast can't roll back state.
    """
    # Local import to avoid a circular graph.broadcast ↔ graph.reducer
    # during package init (broadcast imports GraphEvent which lives
    # in models, which re-exports via models.__init__).
    from backend.graph.broadcast import stash_offset

    # Assign next offset for this project. SQLite doesn't need FOR
    # UPDATE — the surrounding session is already the single writer.
    current_max = session.execute(
        select(func.max(GraphEvent.offset)).where(GraphEvent.project_id == project_id)
    ).scalar()
    next_offset = (current_max or 0) + 1

    row = GraphEvent(
        project_id=project_id,
        offset=next_offset,
        event_type=event.event_type,
        payload=event.model_dump(mode="json"),
        created_at=datetime.utcnow(),
    )
    session.add(row)
    session.flush()

    try:
        apply_event(session, project_id, event)
    except Exception:
        session.rollback()
        raise

    # Phase 9 — central staleness fanout. After the trigger event's
    # projection delta lands, ask the fanout dispatcher what ledger
    # changes (marks/clears) the trigger implies and apply them
    # directly to the StalenessLedger table in the same transaction.
    # Staleness is derived state — not an event-sourced primary
    # projection — so no events land in the log for the mark/clear
    # bookkeeping. This keeps the log canonical and replay clean
    # (rebuild wipes the ledger; a freshly-rebuilt projection has
    # no staleness because nothing has happened after rebuild yet).
    #
    # Local imports avoid circular backend.graph.fanout ↔ reducer
    # and backend.pipeline.queue ↔ reducer during package init.
    from backend.graph.fanout import (
        apply_staleness_changes,
        auto_enqueue_regens,
        compute_staleness_changes,
    )
    from backend.pipeline import queue as pipeline_queue

    changes = compute_staleness_changes(session, project_id, event, next_offset)
    apply_staleness_changes(session, project_id, changes)

    # Auto-enqueue regen jobs for non-destructive triggers.
    # Destructive structural ops (delete/merge/split/promote/demote/
    # reparent) halt the cascade — marks stay visible but no regen
    # fires; the user reviews and kicks regen manually.
    for job_type, payload in auto_enqueue_regens(session, project_id, event, changes):
        pipeline_queue.enqueue(session, job_type=job_type, payload=payload)

    stash_offset(session, next_offset)
    return next_offset


def rebuild_projections(
    session: Session,
    project_id: str,
    up_to_offset: int | None = None,
) -> None:
    """Wipe and replay projections for ``project_id`` from the event log.

    Used for point-in-time view reconstruction and as the test oracle
    for incremental correctness.
    """
    # Wipe projection rows for this project, in FK-safe order.
    session.query(StalenessLedger).filter(StalenessLedger.project_id == project_id).delete(
        synchronize_session=False
    )
    session.query(Draft).filter(Draft.project_id == project_id).delete(synchronize_session=False)
    session.query(Fragment).filter(Fragment.project_id == project_id).delete(
        synchronize_session=False
    )
    session.query(Edge).filter(Edge.project_id == project_id).delete(synchronize_session=False)
    session.query(Node).filter(Node.project_id == project_id).delete(synchronize_session=False)
    session.flush()

    q = (
        select(GraphEvent)
        .where(GraphEvent.project_id == project_id)
        .order_by(GraphEvent.offset.asc())
    )
    if up_to_offset is not None:
        q = q.where(GraphEvent.offset <= up_to_offset)

    for row in session.execute(q).scalars():
        event = ev.event_from_row(row.event_type, row.payload)
        apply_event(session, project_id, event)
    session.flush()


# ── Dispatch ─────────────────────────────────────────────────────────


def apply_event(session: Session, project_id: str, event: ev._EventBase) -> None:
    """Apply an event's projection delta to ``session``.

    One branch per event type. Callers are responsible for committing.
    """
    handler = _HANDLERS.get(event.event_type)
    if handler is None:
        raise ReducerError(f"No reducer branch for event type {event.event_type!r}")
    handler(session, project_id, event)
    session.flush()


# ── Per-event handlers ───────────────────────────────────────────────


def _enforce_comp_depth_cap(
    session: Session,
    project_id: str,
    new_tier: str,
    new_parent_id: str | None,
    node_id_for_error: str,
) -> None:
    """Reject structural changes that would create a three-level ``comp_*`` chain.

    Per ``docs/architecture/v2-rearchitecture.md`` §Subcomponent depth
    cap, the structural component tree is hard-capped at two levels:
    a top-level component can have subcomponent children, but a
    subcomponent cannot itself be the parent of another component.

    Enforced on ``NodeCreated`` / ``NodeReparented`` /
    ``NodePromoted`` / ``NodeDemoted`` events whose *target* tier is
    ``comp``. Non-comp tiers and comp nodes attached to a non-comp
    parent (e.g. a top-level comp under a responsibility) are
    unaffected.
    """
    if new_tier != "comp":
        return
    if new_parent_id is None:
        return
    parent = session.get(Node, new_parent_id)
    if parent is None or parent.project_id != project_id:
        raise ReducerError(
            f"Cannot attach node {node_id_for_error!r}: parent "
            f"{new_parent_id!r} not found in project {project_id!r}"
        )
    if parent.tier != "comp":
        return  # Top-level comp under a responsibility or similar — fine.
    # Parent is a comp. To avoid a three-level chain, the grandparent
    # must not also be a comp.
    if parent.parent_id is None:
        return
    grandparent = session.get(Node, parent.parent_id)
    if grandparent is None or grandparent.project_id != project_id:
        return  # Dangling parent chain — can't enforce, but also can't blow up.
    if grandparent.tier == "comp":
        raise ReducerError(
            f"Subcomponent depth cap violated: cannot attach "
            f"comp node {node_id_for_error!r} under subcomponent "
            f"{new_parent_id!r} (whose parent {parent.parent_id!r} is "
            "already a component). The structural component tree is "
            "capped at two levels; promote the middle layer to a "
            "top-level component instead."
        )


def _enforce_vocab_parent_constraint(
    session: Session,
    project_id: str,
    new_tier: str,
    new_parent_id: str | None,
    node_id_for_error: str,
) -> None:
    """Reject structural changes that would parent a ``vocab_*`` node under a non-feature.

    Per ``docs/architecture/v2-rearchitecture.md`` §Project vocabulary,
    vocab entries are scoped via ``parent_id``: ``None`` for
    project-level, a ``feat_*`` id for feature-local. Anything else —
    a component, a responsibility, another vocab entry — is rejected,
    because scoping below the feature layer would leak project-
    specific terms into arbitrary internal decomposition and defeat
    the coherent-project-vocabulary purpose.

    Enforced on ``NodeCreated`` and ``NodeReparented`` events whose
    target tier is ``vocab``.
    """
    if new_tier != "vocab":
        return
    if new_parent_id is None:
        return  # Project-level, always allowed.
    parent = session.get(Node, new_parent_id)
    if parent is None or parent.project_id != project_id:
        raise ReducerError(
            f"Cannot attach vocab node {node_id_for_error!r}: parent "
            f"{new_parent_id!r} not found in project {project_id!r}"
        )
    if parent.tier != "feat":
        raise ReducerError(
            f"Cannot attach vocab node {node_id_for_error!r} under "
            f"parent {new_parent_id!r} (tier={parent.tier!r}). Vocab "
            "entries may only be scoped to project-level (parent_id "
            "is None) or feature-local (parent_id is a feat_* node). "
            "Parenting vocab under components, responsibilities, or "
            "other tiers is rejected."
        )


def _enforce_reference_parent_constraint(
    new_tier: str,
    new_parent_id: str | None,
    node_id_for_error: str,
) -> None:
    """Reject structural changes that would parent a ``ref_*`` node under anything.

    Per ``docs/architecture/v2-rearchitecture.md`` §Project references,
    refs are always top-level: ``parent_id`` must be ``None``. Unlike
    vocab (which is scoped to project or feature), refs have no
    sub-scope — any node can pull any ref into its regen context via
    an outgoing ``reference`` edge, so parenting refs below the
    project root has no meaning.

    Enforced on ``NodeCreated`` and ``NodeReparented`` events whose
    target tier is ``ref``.
    """
    if new_tier != "ref":
        return
    if new_parent_id is None:
        return
    raise ReducerError(
        f"Cannot attach ref node {node_id_for_error!r} under parent "
        f"{new_parent_id!r}: references are always top-level "
        "(parent_id must be None). Reference edges connect refs to "
        "consumers; hierarchical parenting is not used."
    )


def _apply_node_created(session: Session, project_id: str, event: ev.NodeCreated) -> None:
    _enforce_comp_depth_cap(session, project_id, event.tier, event.parent_id, event.node_id)
    _enforce_vocab_parent_constraint(
        session, project_id, event.tier, event.parent_id, event.node_id
    )
    _enforce_reference_parent_constraint(event.tier, event.parent_id, event.node_id)
    now = datetime.utcnow()
    session.add(
        Node(
            id=event.node_id,
            project_id=project_id,
            tier=event.tier,
            kind=event.kind,
            parent_id=event.parent_id,
            name=event.name,
            display_order=event.display_order,
            content=event.content,
            group_label=event.group_label,
            is_implicit=event.is_implicit,
            is_foundation=event.is_foundation,
            created_at=now,
            updated_at=now,
        )
    )


def _require_node(session: Session, project_id: str, node_id: str) -> Node:
    node = session.get(Node, node_id)
    if node is None or node.project_id != project_id:
        raise ReducerError(f"Node {node_id!r} not found in project {project_id!r}")
    return node


def _apply_node_renamed(session: Session, project_id: str, event: ev.NodeRenamed) -> None:
    node = _require_node(session, project_id, event.node_id)
    node.name = event.new_name
    node.updated_at = datetime.utcnow()


def _apply_node_reparented(session: Session, project_id: str, event: ev.NodeReparented) -> None:
    node = _require_node(session, project_id, event.node_id)
    _enforce_comp_depth_cap(session, project_id, node.tier, event.new_parent_id, event.node_id)
    _enforce_vocab_parent_constraint(
        session, project_id, node.tier, event.new_parent_id, event.node_id
    )
    _enforce_reference_parent_constraint(node.tier, event.new_parent_id, event.node_id)
    node.parent_id = event.new_parent_id
    node.updated_at = datetime.utcnow()


def _apply_node_promoted(session: Session, project_id: str, event: ev.NodePromoted) -> None:
    node = _require_node(session, project_id, event.node_id)
    _enforce_comp_depth_cap(session, project_id, event.new_tier, node.parent_id, event.node_id)
    node.tier = event.new_tier
    node.updated_at = datetime.utcnow()


def _apply_node_demoted(session: Session, project_id: str, event: ev.NodeDemoted) -> None:
    node = _require_node(session, project_id, event.node_id)
    _enforce_comp_depth_cap(session, project_id, event.new_tier, node.parent_id, event.node_id)
    node.tier = event.new_tier
    node.updated_at = datetime.utcnow()


def _apply_nodes_merged(session: Session, project_id: str, event: ev.NodesMerged) -> None:
    # The merge target must already exist (typically one of the source IDs
    # survives as the dest, or a new node was created first by a prior event).
    dest = _require_node(session, project_id, event.dest_id)
    dest.name = event.dest_name
    dest.updated_at = datetime.utcnow()

    # Delete the *other* sources. If dest is among the sources, skip it.
    for sid in event.source_ids:
        if sid == event.dest_id:
            continue
        src = session.get(Node, sid)
        if src is not None and src.project_id == project_id:
            session.delete(src)


def _apply_node_split(session: Session, project_id: str, event: ev.NodeSplit) -> None:
    if len(event.dest_ids) != len(event.dest_names):
        raise ReducerError(
            "NodeSplit: dest_ids and dest_names length mismatch "
            f"({len(event.dest_ids)} vs {len(event.dest_names)})"
        )
    src = _require_node(session, project_id, event.source_id)
    now = datetime.utcnow()
    for new_id, new_name in zip(event.dest_ids, event.dest_names, strict=True):
        if new_id == event.source_id:
            # Rename in place.
            src.name = new_name
            src.updated_at = now
            continue
        session.add(
            Node(
                id=new_id,
                project_id=project_id,
                tier=src.tier,
                kind=src.kind,
                parent_id=src.parent_id,
                name=new_name,
                display_order=src.display_order,
                content="",
                created_at=now,
                updated_at=now,
            )
        )
    # Delete the source if it's not listed among dest_ids.
    if event.source_id not in event.dest_ids:
        session.delete(src)


def _apply_node_deleted(session: Session, project_id: str, event: ev.NodeDeleted) -> None:
    node = session.get(Node, event.node_id)
    if node is not None and node.project_id == project_id:
        session.delete(node)


def _apply_edge_created(session: Session, project_id: str, event: ev.EdgeCreated) -> None:
    # Idempotency: if an edge already exists for this
    # ``(project_id, edge_type, source_id, target_id)`` tuple, treat
    # the event as a no-op rather than violating the
    # ``uq_edges_project_type_source_target`` constraint or raising
    # on the primary key. This lets mint handlers re-run cleanly on
    # retry / crash-recovery: the handler re-emits the same logical
    # edges with fresh ``edge_id`` strings, and the reducer absorbs
    # the duplicate. The event itself is still recorded in the
    # graph_events log so replay from zero produces the same state.
    existing = session.execute(
        select(Edge.id).where(
            Edge.project_id == project_id,
            Edge.edge_type == event.edge_type,
            Edge.source_id == event.source_id,
            Edge.target_id == event.target_id,
        )
    ).first()
    if existing is not None:
        return
    session.add(
        Edge(
            id=event.edge_id,
            project_id=project_id,
            edge_type=event.edge_type,
            source_id=event.source_id,
            target_id=event.target_id,
            created_at=datetime.utcnow(),
        )
    )


def _apply_edge_deleted(session: Session, project_id: str, event: ev.EdgeDeleted) -> None:
    edge = session.get(Edge, event.edge_id)
    if edge is not None and edge.project_id == project_id:
        session.delete(edge)


def _apply_fragment_updated(session: Session, project_id: str, event: ev.FragmentUpdated) -> None:
    frag = session.get(Fragment, event.fragment_id)
    now = datetime.utcnow()
    expected_id = fragment_id(event.owner_id, event.fragment_kind)
    if expected_id != event.fragment_id:
        raise ReducerError(
            f"FragmentUpdated: fragment_id {event.fragment_id!r} does not match "
            f"owner_id/fragment_kind-derived id {expected_id!r}"
        )
    if frag is None:
        # First write to this fragment creates the row.
        session.add(
            Fragment(
                id=event.fragment_id,
                project_id=project_id,
                owner_id=event.owner_id,
                fragment_kind=event.fragment_kind.value,
                content=event.new_content,
                updated_at=now,
            )
        )
    else:
        if frag.project_id != project_id:
            raise ReducerError(f"Fragment {event.fragment_id!r} belongs to a different project")
        # Idempotency: if the content is byte-for-byte identical to
        # the stored fragment, skip the write entirely so a
        # re-running mint handler doesn't churn ``updated_at`` on
        # rows that haven't actually changed.
        if frag.content == event.new_content:
            return
        frag.content = event.new_content
        frag.updated_at = now


def _apply_draft_generated(session: Session, project_id: str, event: ev.DraftGenerated) -> None:
    now = datetime.utcnow()
    session.add(
        Draft(
            id=event.draft_id,
            project_id=project_id,
            target_type=event.target_type,
            target_id=event.target_id,
            content=event.content,
            status="pending",
            batch_id=event.batch_id,
            created_at=now,
            updated_at=now,
        )
    )


def _apply_draft_edited(session: Session, project_id: str, event: ev.DraftEdited) -> None:
    draft = session.get(Draft, event.draft_id)
    if draft is None or draft.project_id != project_id:
        raise ReducerError(f"Draft {event.draft_id!r} not found in project {project_id!r}")
    if draft.status != "pending":
        raise ReducerError(f"Draft {event.draft_id!r} is {draft.status!r}, cannot edit")
    draft.content = event.new_content
    draft.updated_at = datetime.utcnow()


def _apply_draft_approved(session: Session, project_id: str, event: ev.DraftApproved) -> None:
    draft = session.get(Draft, event.draft_id)
    if draft is None or draft.project_id != project_id:
        raise ReducerError(f"Draft {event.draft_id!r} not found in project {project_id!r}")
    if draft.status != "pending":
        raise ReducerError(f"Draft {event.draft_id!r} is {draft.status!r}, cannot approve")
    now = datetime.utcnow()
    draft.status = "approved"
    draft.updated_at = now

    # Commit the draft's content to the target projection.
    if draft.target_type == "node":
        node = _require_node(session, project_id, draft.target_id)
        node.content = draft.content
        node.updated_at = now
    elif draft.target_type == "fragment":
        frag = session.get(Fragment, draft.target_id)
        if frag is None:
            # Cold-start: the fragment row is created on first approval.
            # We need owner_id + kind — parse them from the fragment_id.
            from backend.graph.fragments import parse_fragment_id

            owner_id, kind = parse_fragment_id(draft.target_id)
            session.add(
                Fragment(
                    id=draft.target_id,
                    project_id=project_id,
                    owner_id=owner_id,
                    fragment_kind=kind.value,
                    content=draft.content,
                    updated_at=now,
                )
            )
        else:
            if frag.project_id != project_id:
                raise ReducerError(f"Fragment {draft.target_id!r} belongs to a different project")
            frag.content = draft.content
            frag.updated_at = now
    else:
        raise ReducerError(f"DraftApproved: unknown target_type {draft.target_type!r}")


def _apply_draft_discarded(session: Session, project_id: str, event: ev.DraftDiscarded) -> None:
    draft = session.get(Draft, event.draft_id)
    if draft is None or draft.project_id != project_id:
        raise ReducerError(f"Draft {event.draft_id!r} not found in project {project_id!r}")
    if draft.status != "pending":
        raise ReducerError(f"Draft {event.draft_id!r} is {draft.status!r}, cannot discard")
    draft.status = "discarded"
    draft.updated_at = datetime.utcnow()


def _apply_fanin_content_updated(
    session: Session,
    project_id: str,
    event: ev.FanInContentUpdated,
) -> None:
    """Overwrite a ``tier="fanin"`` node's ``content`` with a new synthesis.

    Fan-in has no draft lifecycle: the generation handler
    validates the LLM output and writes the serialized ``<fanin>``
    block directly via this event. Reusing ``DraftApproved``
    would create phantom ``Draft`` rows with no review step and
    pollute draft-count queries; keeping a dedicated event
    preserves the "Draft rows imply a reviewable artifact"
    invariant.

    Asserts the target node exists, belongs to this project, and
    is on the fan-in tier — any other tier is a bug (caller sent
    the wrong event type).
    """
    node = _require_node(session, project_id, event.node_id)
    if node.tier != "fanin":
        raise ReducerError(
            f"FanInContentUpdated: node {event.node_id!r} is "
            f"tier={node.tier!r}, expected tier='fanin'"
        )
    node.content = event.new_content
    node.updated_at = datetime.utcnow()


def _apply_draft_review_updated(
    session: Session,
    project_id: str,
    event: ev.DraftReviewUpdated,
) -> None:
    """Write the AI self-review markdown to the draft or owning node.

    Phase 8: one review pass per draft commit. When ``draft_id``
    is set the reducer updates ``Draft.review_text``; when it's
    ``None`` (fanin tier — no draft lifecycle), it updates
    ``Node.review_text`` on the owning node.

    Idempotent: replaying simply re-sets ``review_text`` to the
    same value.
    """
    if event.draft_id is not None:
        draft = session.get(Draft, event.draft_id)
        if draft is None or draft.project_id != project_id:
            raise ReducerError(
                f"DraftReviewUpdated: draft {event.draft_id!r} not found in project {project_id!r}"
            )
        draft.review_text = event.review_text
        draft.updated_at = datetime.utcnow()
        return
    node = _require_node(session, project_id, event.node_id)
    node.review_text = event.review_text
    node.updated_at = datetime.utcnow()


def _apply_bootstrap_node_content_cleared(
    session: Session,
    project_id: str,
    event: ev.BootstrapNodeContentCleared,
) -> None:
    """Reset a bootstrap tier node's ``content`` back to empty.

    Used by the destructive reset path on approved bootstrap nodes
    (currently sysarch only) so the user can regenerate against a
    new prompt without touching upstream state. The reset route
    emits this event at the end of the walk, after all downstream
    ``NodeDeleted`` events for the approval cascade, so replay
    from the event log produces a consistent post-reset state.

    Mirrors the one-node scope of ``NodeDeleted``: takes a single
    ``node_id`` and only mutates that node's content field. The
    node itself is not deleted — the ID stays stable so event log
    history stays intact and the next lazy-bootstrap GET finds
    the existing row.

    Sets ``node.content`` to the empty string (not ``None``)
    because the column is ``nullable=False``. The
    ``has_been_approved`` check is ``bool(node.content)``, so
    empty string flips the freeze back off — same as if the
    node had never been approved.
    """
    node = session.get(Node, event.node_id)
    if node is None or node.project_id != project_id:
        raise ReducerError(f"Node {event.node_id!r} not found in project {project_id!r}")
    node.content = ""


def _apply_view_recorded(session: Session, project_id: str, event: ev.ViewRecorded) -> None:
    # View markers are audit records only — no projection mutation.
    return


# Callable is contravariant in its parameter types, so a concrete
# handler ``(Session, str, NodeCreated) -> None`` is NOT a subtype of
# ``(Session, str, _EventBase) -> None``. The dispatch contract is
# "the string key guarantees the event type matches", so we widen the
# value type to ``Any`` on the event parameter and let each branch
# narrow internally.
_HANDLERS: dict[str, Callable[[Session, str, Any], None]] = {
    "NodeCreated": _apply_node_created,
    "NodeRenamed": _apply_node_renamed,
    "NodeReparented": _apply_node_reparented,
    "NodePromoted": _apply_node_promoted,
    "NodeDemoted": _apply_node_demoted,
    "NodesMerged": _apply_nodes_merged,
    "NodeSplit": _apply_node_split,
    "NodeDeleted": _apply_node_deleted,
    "EdgeCreated": _apply_edge_created,
    "EdgeDeleted": _apply_edge_deleted,
    "FragmentUpdated": _apply_fragment_updated,
    "DraftReviewUpdated": _apply_draft_review_updated,
    "DraftGenerated": _apply_draft_generated,
    "DraftEdited": _apply_draft_edited,
    "DraftApproved": _apply_draft_approved,
    "DraftDiscarded": _apply_draft_discarded,
    "FanInContentUpdated": _apply_fanin_content_updated,
    "BootstrapNodeContentCleared": _apply_bootstrap_node_content_cleared,
    "ViewRecorded": _apply_view_recorded,
}


# Silence unused-import when FragmentKind is only referenced via type hints
_ = FragmentKind
