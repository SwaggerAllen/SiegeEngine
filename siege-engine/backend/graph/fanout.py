"""Phase 9 — central staleness-marker fanout dispatcher.

When ``append_event`` commits any event, this module classifies it
and returns the set of ledger changes (marks to insert, clears to
delete) that keep the staleness ledger consistent with the
projection. The caller applies those changes directly to the
``StalenessLedger`` table in the same transaction — staleness is
**derived state**, not primary state, so no events land in the log
for the mark/clear bookkeeping.

Scope limitation (Phase 9 MVP): the fanout walks edges recorded
in the ``edges`` table — ``dependency``, ``decomposition``,
``domain_parent``, ``policy_application``, ``reference``.
Propagation that goes through **structural parent chains**
(``parent_id``) rather than explicit edges — specifically impl →
fanin and fanin → presentational comparch — is NOT caught by this
module. Those two paths stay on their bespoke hooks
(``on_impl_approved`` and ``_unblock_presentationals_on_fanin_commit``)
until a follow-up phase either (a) emits synthetic edges at mint
time to mirror the parent-id relationship, or (b) teaches fanout
to walk parent_id for specific tier pairs. Documenting here
because the plan originally called for retiring those hooks;
retiring safely requires the edge-graph extension first.

Derived-state rationale: staleness is a function of the edge graph
plus the content-offset history. Rebuilding the projection from the
event log regenerates nodes, edges, fragments, drafts — all the
primary state. Staleness ledger entries could in principle be
rebuilt by replaying content events through the fanout logic, but
they're running-state (they tell the scheduler what to regen next),
not historical state (they don't answer "what did the project look
like at time T"). Leaving the ledger empty after replay is the
correct semantics: there's nothing stale in a freshly-rebuilt
projection because nothing has happened after rebuild yet.

Events break into four groups:

- **Content commits** (``DraftApproved``, ``FragmentUpdated``,
  ``FanInContentUpdated``, ``BootstrapNodeContentCleared``) — the
  source node's content changed. Clear its own ledger entries
  (it caught up with its upstream) and mark every inbound-edge
  source as stale w.r.t. the source node.
- **Edge changes** (``EdgeCreated``) — the dependent endpoint's
  context set just changed. Mark the dependent stale w.r.t. the
  other endpoint. ``EdgeDeleted`` is a no-op for MVP (see
  comment in ``compute_staleness_changes``).
- **Destructive structural ops** (``NodeDeleted`` / ``NodesMerged``
  / ``NodeSplit`` / ``NodePromoted`` / ``NodeDemoted`` /
  ``NodeReparented``) — affected neighbors get marks with
  ``reason=structural_change``. The caller checks
  :func:`is_destructive` to suppress auto-enqueue; marks stay
  visible for manual user review.
- **Everything else** — no fanout.

See ``docs/architecture/v2-roadmap.md`` Phase 9.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.graph import events as ev
from backend.graph.fragments import parse_fragment_id
from backend.models.node import Draft, Edge, Node, StalenessLedger

# Structural ops that halt the cascade. The dispatcher still emits
# marks so affected neighbors are visible in the UI, but the
# caller checks is_destructive to skip auto-enqueueing regens —
# the user decides what to do about the destructive change.
_DESTRUCTIVE_EVENT_TYPES = frozenset(
    {
        "NodeDeleted",
        "NodesMerged",
        "NodeSplit",
        "NodePromoted",
        "NodeDemoted",
        "NodeReparented",
    }
)


def is_destructive(event: ev._EventBase) -> bool:
    """Return True if ``event`` is a structural op that halts the cascade."""
    return event.event_type in _DESTRUCTIVE_EVENT_TYPES


@dataclass(frozen=True)
class _Mark:
    """Insert a staleness ledger row for (stale, source, reason)."""

    stale_node_id: str
    source_node_id: str
    source_offset: int
    reason: str


@dataclass(frozen=True)
class _Clear:
    """Delete ledger rows for (stale, source), any reason."""

    stale_node_id: str
    source_node_id: str


@dataclass
class StalenessChanges:
    """Ledger mutations the fanout dispatcher computed for one trigger."""

    marks: list[_Mark] = field(default_factory=list)
    clears: list[_Clear] = field(default_factory=list)


def compute_staleness_changes(
    session: Session,
    project_id: str,
    trigger: ev._EventBase,
    trigger_offset: int,
) -> StalenessChanges:
    """Return the ledger mutations that should follow ``trigger``.

    Called by :func:`backend.graph.reducer.append_event` after
    ``apply_event`` succeeds. The returned :class:`StalenessChanges`
    is applied directly to the ``StalenessLedger`` table in the
    same transaction via :func:`apply_staleness_changes`.

    ``trigger_offset`` is the per-project ``graph_events.offset``
    the trigger landed at — stamped onto inserted marks so the
    ledger captures "stale w.r.t. neighbor N at offset O" per the
    Phase 9 roadmap bullet.
    """
    changes = StalenessChanges()

    # isinstance dispatch narrows the type on each branch so mypy
    # can verify the per-event attribute accesses below. String-
    # based dispatch on trigger.event_type works at runtime but
    # doesn't give mypy the narrowing it needs under strict
    # configs used in CI.
    if isinstance(trigger, ev.DraftApproved):
        _fanout_draft_approved(session, project_id, trigger, trigger_offset, changes)
    elif isinstance(trigger, ev.FragmentUpdated):
        # Post-MVP refinement: peek pre-apply fragment content and
        # call fragment_changed() to skip no-op idempotent writes.
        # For Phase 9 crude fanout, any FragmentUpdated emits
        # staleness; downstream over-regen is acceptable noise.
        _fanout_content_change(
            session, project_id, trigger.owner_id, trigger_offset, "fragment_changed", changes
        )
    elif isinstance(trigger, ev.FanInContentUpdated):
        _fanout_content_change(
            session, project_id, trigger.node_id, trigger_offset, "content_changed", changes
        )
    elif isinstance(trigger, ev.BootstrapNodeContentCleared):
        _fanout_content_change(
            session, project_id, trigger.node_id, trigger_offset, "content_changed", changes
        )
    elif isinstance(trigger, ev.NodeRenamed):
        _fanout_node_renamed(session, project_id, trigger, trigger_offset, changes)
    elif isinstance(trigger, ev.EdgeCreated):
        _fanout_edge_change(
            session,
            project_id,
            trigger.source_id,
            trigger.target_id,
            trigger_offset,
            "edge_created",
            changes,
        )
    elif isinstance(trigger, ev.EdgeDeleted):
        # EdgeDeleted carries only edge_id; the edge row is gone
        # from the projection by the time fanout runs, so we can't
        # resolve its source/target here. Phase 9 MVP: skip
        # EdgeDeleted staleness. Destructive structural ops
        # (NodeDeleted etc.) cover the common case — cascading
        # deletes that remove edges fan out staleness via the
        # structural-change branch on the deleted node.
        pass
    elif trigger.event_type in _DESTRUCTIVE_EVENT_TYPES:
        _fanout_structural_change(session, project_id, trigger, trigger_offset, changes)

    # Drop marks whose target has no approved content yet — those
    # nodes aren't "stale" in the Phase 9 sense, they're pre-first-
    # pass and the regular scheduler will handle them once their
    # prerequisites are met. Without this filter, fanout auto-
    # enqueues regens on never-generated nodes, which the tier
    # handlers' readiness gates then hard-fail (e.g., a comparch
    # regen firing before the comp's subreqs have been approved).
    # Clears are kept regardless — removing a ledger entry is
    # harmless.
    changes.marks = [m for m in changes.marks if _has_approved_content(session, m.stale_node_id)]

    return changes


def _has_approved_content(session: Session, node_id: str) -> bool:
    """Return True when ``node_id`` has non-empty approved content.

    Used by :func:`compute_staleness_changes` to skip marks for
    nodes that haven't had their first-pass generation yet. An
    empty content field is the platform signal for "not approved"
    on every tier whose generator writes to ``Node.content``; for
    draft-target tiers, approval writes content, and reset paths
    explicitly clear it back to the empty string.
    """
    node = session.get(Node, node_id)
    if node is None:
        return False
    return bool((node.content or "").strip())


def apply_staleness_changes(
    session: Session,
    project_id: str,
    changes: StalenessChanges,
) -> None:
    """Apply a :class:`StalenessChanges` to the ledger table.

    Clears run before marks so a "regen resolves upstream X and
    produces new content that re-stales X" pattern lands correctly
    (the clear happens first, then the mark if one was computed).
    Idempotent on the ``(project_id, stale_node_id, source_node_id,
    reason)`` unique constraint — re-applying the same mark before
    a clear is a no-op; re-applying a clear when no row exists is
    a no-op.
    """
    now = datetime.utcnow()
    for clear in changes.clears:
        rows = (
            session.execute(
                select(StalenessLedger).where(
                    StalenessLedger.project_id == project_id,
                    StalenessLedger.stale_node_id == clear.stale_node_id,
                    StalenessLedger.source_node_id == clear.source_node_id,
                )
            )
            .scalars()
            .all()
        )
        for row in rows:
            session.delete(row)
    for mark in changes.marks:
        existing = session.execute(
            select(StalenessLedger).where(
                StalenessLedger.project_id == project_id,
                StalenessLedger.stale_node_id == mark.stale_node_id,
                StalenessLedger.source_node_id == mark.source_node_id,
                StalenessLedger.reason == mark.reason,
            )
        ).scalar_one_or_none()
        if existing is not None:
            if mark.source_offset > existing.source_offset:
                existing.source_offset = mark.source_offset
            continue
        session.add(
            StalenessLedger(
                project_id=project_id,
                stale_node_id=mark.stale_node_id,
                source_node_id=mark.source_node_id,
                source_offset=mark.source_offset,
                reason=mark.reason,
                created_at=now,
            )
        )


# ── Per-branch helpers ────────────────────────────────────────────────


def _fanout_draft_approved(
    session: Session,
    project_id: str,
    event: ev.DraftApproved,
    offset: int,
    changes: StalenessChanges,
) -> None:
    """A draft's content has committed to either a node or a fragment.

    Resolve the source node id (for fragment targets, the owner
    node is the source) and delegate to the content-change helper.
    """
    draft = session.get(Draft, event.draft_id)
    if draft is None or draft.project_id != project_id:
        return
    if draft.target_type == "node":
        source_node_id = draft.target_id
        reason = "content_changed"
    elif draft.target_type == "fragment":
        try:
            owner_id, _kind = parse_fragment_id(draft.target_id)
        except Exception:
            return
        source_node_id = owner_id
        reason = "fragment_changed"
    else:
        return
    _fanout_content_change(session, project_id, source_node_id, offset, reason, changes)


def _fanout_content_change(
    session: Session,
    project_id: str,
    source_node_id: str,
    offset: int,
    reason: str,
    changes: StalenessChanges,
) -> None:
    """Content landed on ``source_node_id``.

    - Clears every ledger row whose ``stale_node_id == source_node_id``
      (the source just regenerated, so its own staleness w.r.t.
      anything upstream is resolved).
    - Marks every node that has an outbound edge targeting
      ``source_node_id`` as stale w.r.t. ``source_node_id``.
    """
    # Clear source's own staleness — group by upstream so one clear
    # per (source, upstream) removes all reasons in a single call.
    own_rows = (
        session.execute(
            select(StalenessLedger).where(
                StalenessLedger.project_id == project_id,
                StalenessLedger.stale_node_id == source_node_id,
            )
        )
        .scalars()
        .all()
    )
    cleared_upstreams: set[str] = set()
    for row in own_rows:
        if row.source_node_id in cleared_upstreams:
            continue
        cleared_upstreams.add(row.source_node_id)
        changes.clears.append(
            _Clear(stale_node_id=source_node_id, source_node_id=row.source_node_id)
        )

    # Mark inbound-edge sources as stale w.r.t. the changed node.
    inbound = (
        session.execute(
            select(Edge).where(
                Edge.project_id == project_id,
                Edge.target_id == source_node_id,
            )
        )
        .scalars()
        .all()
    )
    marked: set[str] = set()
    for edge in inbound:
        if edge.source_id == source_node_id:
            continue  # defensive: skip self-loops
        if edge.source_id in marked:
            continue
        marked.add(edge.source_id)
        changes.marks.append(
            _Mark(
                stale_node_id=edge.source_id,
                source_node_id=source_node_id,
                source_offset=offset,
                reason=reason,
            )
        )


def _fanout_edge_change(
    session: Session,
    project_id: str,
    source_id: str,
    target_id: str,
    offset: int,
    reason: str,
    changes: StalenessChanges,
) -> None:
    """An edge was created.

    Edge direction is ``source → target``; the source reads the
    target's handle (context walks originate at source and pull
    target content). A new edge therefore invalidates the source:
    its context set just changed.
    """
    changes.marks.append(
        _Mark(
            stale_node_id=source_id,
            source_node_id=target_id,
            source_offset=offset,
            reason=reason,
        )
    )


def _fanout_node_renamed(
    session: Session,
    project_id: str,
    event: ev.NodeRenamed,
    offset: int,
    changes: StalenessChanges,
) -> None:
    """A rename changes the node's handle.

    Two consequences:
    - The renamed node itself likely has content still mentioning
      the old name and wants a regen to refresh prose. Mark it
      stale with source = itself so auto-enqueue fires a
      ``v2.regen_<tier>`` for it.
    - Every inbound-edge source reads this node's handle in its
      regen context. Those dependents are now stale w.r.t. the
      renamed node.

    Unlike ``_fanout_content_change``, we deliberately do NOT
    clear the renamed node's prior staleness — a rename isn't
    the node catching up with its upstreams; it's an orthogonal
    structural op, and any pending staleness is still real.
    """
    changes.marks.append(
        _Mark(
            stale_node_id=event.node_id,
            source_node_id=event.node_id,
            source_offset=offset,
            reason="content_changed",
        )
    )
    inbound = (
        session.execute(
            select(Edge).where(
                Edge.project_id == project_id,
                Edge.target_id == event.node_id,
            )
        )
        .scalars()
        .all()
    )
    marked: set[str] = set()
    for edge in inbound:
        if edge.source_id == event.node_id:
            continue
        if edge.source_id in marked:
            continue
        marked.add(edge.source_id)
        changes.marks.append(
            _Mark(
                stale_node_id=edge.source_id,
                source_node_id=event.node_id,
                source_offset=offset,
                reason="content_changed",
            )
        )


def _fanout_structural_change(
    session: Session,
    project_id: str,
    trigger: ev._EventBase,
    offset: int,
    changes: StalenessChanges,
) -> None:
    """A destructive structural op landed.

    Mark every neighbor that depended on or decomposed from the
    affected node(s) as stale with ``reason=structural_change``.
    The caller checks :func:`is_destructive` to suppress
    auto-enqueueing regens; the user reviews and kicks regen
    manually after deciding what to do about the destructive
    change.
    """
    target_ids = _structural_target_ids(trigger)
    seen: set[tuple[str, str]] = set()

    for target_id in target_ids:
        # Inbound: who read this node?
        inbound = (
            session.execute(
                select(Edge).where(
                    Edge.project_id == project_id,
                    Edge.target_id == target_id,
                )
            )
            .scalars()
            .all()
        )
        for edge in inbound:
            if edge.source_id == target_id:
                continue
            key = (edge.source_id, target_id)
            if key in seen:
                continue
            seen.add(key)
            changes.marks.append(
                _Mark(
                    stale_node_id=edge.source_id,
                    source_node_id=target_id,
                    source_offset=offset,
                    reason="structural_change",
                )
            )
        # Outbound: who did this node read? Reversing the edge
        # direction captures "the thing this node pointed at is
        # now a dangling reference" cases (e.g., merge collapsed
        # one endpoint into another).
        outbound = (
            session.execute(
                select(Edge).where(
                    Edge.project_id == project_id,
                    Edge.source_id == target_id,
                )
            )
            .scalars()
            .all()
        )
        for edge in outbound:
            if edge.target_id == target_id:
                continue
            key = (edge.target_id, target_id)
            if key in seen:
                continue
            seen.add(key)
            changes.marks.append(
                _Mark(
                    stale_node_id=edge.target_id,
                    source_node_id=target_id,
                    source_offset=offset,
                    reason="structural_change",
                )
            )


def _structural_target_ids(trigger: ev._EventBase) -> list[str]:
    """Extract the set of node ids a destructive event operates on."""
    etype = trigger.event_type
    if etype == "NodesMerged":
        sources = list(getattr(trigger, "source_ids", []) or [])
        dest = getattr(trigger, "dest_id", None)
        if dest:
            sources.append(dest)
        return sources
    if etype == "NodeSplit":
        target = getattr(trigger, "source_id", None)
        dests = list(getattr(trigger, "dest_ids", []) or [])
        out = list(dests)
        if target:
            out.append(target)
        return out
    # NodeDeleted / NodePromoted / NodeDemoted / NodeReparented all
    # carry a single ``node_id``.
    node_id = getattr(trigger, "node_id", None)
    return [node_id] if node_id else []


# ── Auto-enqueue: regen jobs for non-destructive staleness ───────────


def regen_job_for_node(project_id: str, node: Node) -> tuple[str, dict] | None:
    """Return ``(job_type, payload)`` for regenerating ``node``, or None.

    Maps a node's tier to the generation job that refreshes its
    content, using the handler's expected payload shape (per each
    handler's ``payload.get(...)`` contract). Returns None for
    tiers that aren't regenerated independently — feat / resp /
    policy / vocab / plan / manifest are minted from their owning
    bootstrap's approval, so staleness on them auto-resolves when
    the bootstrap regens. The caller skips enqueueing for those
    tiers.

    Payloads match the convention each handler expects, including
    ``feedback: None`` for tiers whose handlers read that key —
    same payload shape the bespoke ``on_approve`` hooks and
    in-handler enqueues produce, so the queue's payload-dedupe
    collapses regens from fanout and from hooks into a single job.
    """
    tier = node.tier
    base = {"project_id": project_id}
    if tier == "expansion":
        return ("v2.generate_expansion", {**base, "feedback": None})
    if tier == "reqs":
        return ("v2.generate_requirements", {**base, "feedback": None})
    if tier == "sysarch":
        return ("v2.generate_sysarch", {**base, "feedback": None})
    if tier == "subreqs":
        if node.parent_id is None:
            return None
        return (
            "v2.generate_subreqs",
            {**base, "component_id": node.parent_id, "feedback": None},
        )
    if tier == "comp":
        # Top-level → comparch regen; subcomp → subcomparch regen.
        if node.parent_id is None:
            return (
                "v2.generate_comparch",
                {**base, "component_id": node.id, "feedback": None},
            )
        return (
            "v2.generate_subcomparch",
            {**base, "component_id": node.id, "feedback": None},
        )
    if tier == "fanin":
        # Fanin handler payload: {project_id, owner_comp_id}. No
        # feedback key — fanin regens don't take user feedback.
        if node.parent_id is None:
            return None
        return ("v2.generate_fanin", {**base, "owner_comp_id": node.parent_id})
    if tier == "impl":
        if node.parent_id is None:
            return None
        return (
            "v2.generate_impl",
            {**base, "owner_id": node.parent_id, "feedback": None},
        )
    if tier == "ref":
        return (
            "v2.generate_reference",
            {**base, "ref_id": node.id, "feedback": None},
        )
    return None


def auto_enqueue_regens(
    session: Session,
    project_id: str,
    trigger: ev._EventBase,
    changes: StalenessChanges,
) -> list[tuple[str, dict]]:
    """Return ``(job_type, payload)`` pairs for regens to enqueue.

    Empty when ``trigger`` is destructive — the cascade halts for
    the user to review. Otherwise returns one enqueue per marked
    node that has a known regen job type. The caller pipes each
    pair through ``backend.pipeline.queue.enqueue``; the queue's
    payload-dedupe collapses duplicate enqueues into a single job.
    """
    if is_destructive(trigger):
        return []

    requests: list[tuple[str, dict]] = []
    seen: set[tuple[str, str]] = set()  # (job_type, target_key) for dedup
    for mark in changes.marks:
        node = session.get(Node, mark.stale_node_id)
        if node is None or node.project_id != project_id:
            continue
        job = regen_job_for_node(project_id, node)
        if job is None:
            continue
        job_type, payload = job
        target_key = "|".join(f"{k}={v}" for k, v in sorted(payload.items()) if k != "project_id")
        key = (job_type, target_key)
        if key in seen:
            continue
        seen.add(key)
        requests.append((job_type, payload))
    return requests
