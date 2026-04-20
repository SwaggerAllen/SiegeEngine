"""End-to-end integration tests for the Phase 11 pending-change queue.

Covers the full loop from ``enqueue → apply_pending_queue →
_apply_instructions_handler → reducer events → fanout → staleness
ledger`` without invoking the LLM. Complements the full-chain test
by exercising structural edits the chain test doesn't reach (those
run against a freshly-bootstrapped project; Phase 11 edits land
against an already-minted project).

Each test seeds the projection directly with ``NodeCreated`` /
``EdgeCreated`` events (no CLI mocking needed) and asserts the
post-apply state reflects both the reducer events and the Phase 9
fanout derived state.
"""

from __future__ import annotations

import asyncio

from backend.graph import events as ev
from backend.graph import queue as q
from backend.graph.fanout import is_destructive
from backend.graph.ids import Kind, mint
from backend.graph.instructions import (
    AddDependency,
    Delete,
    ReassignMapping,
    Rename,
)
from backend.graph.reducer import append_event
from backend.models.graph_event import GraphEvent
from backend.models.node import Edge, Node
from backend.models.pending_instruction import PendingInstruction


class _NoCloseProxy:
    def __init__(self, s):
        self._s = s

    def __getattr__(self, k):
        return getattr(self._s, k)

    def close(self):
        return None


def _patch_session(monkeypatch, db):
    from backend.graph import queue as queue_mod
    from backend.graph.handlers import rename_rewrite as rr_mod

    monkeypatch.setattr(queue_mod, "SessionLocal", lambda: _NoCloseProxy(db))
    monkeypatch.setattr(rr_mod, "SessionLocal", lambda: _NoCloseProxy(db))


def _mk_comp(db, project_id, name, parent_id=None):
    nid = mint(db, Kind.COMP)
    append_event(
        db,
        project_id,
        ev.NodeCreated(
            node_id=nid,
            tier="comp",
            kind="domain",
            parent_id=parent_id,
            name=name,
            content="",
        ),
    )
    return nid


def _mk_resp(db, project_id, name, parent_id):
    nid = mint(db, Kind.RESP)
    append_event(
        db,
        project_id,
        ev.NodeCreated(
            node_id=nid,
            tier="resp",
            kind="domain",
            parent_id=parent_id,
            name=name,
            content="",
        ),
    )
    return nid


def _event_types(db, project_id):
    return [r.event_type for r in db.query(GraphEvent).filter_by(project_id=project_id).all()]


class TestPhase11ApplyIntegration:
    def test_reassign_mapping_produces_nodereparented_and_halts_cascade(
        self, db, project, monkeypatch
    ):
        """ReassignMapping is a destructive structural op — fanout halts.

        Mirrors the Phase 9 contract: destructive events still mark
        neighbors stale (so the UI shows fuchsia), but don't auto-
        enqueue regens. The user reviews the staleness and chooses
        to re-run affected tiers manually.
        """
        # Seed two top-level comps and a subresp under the first one.
        top_a = _mk_comp(db, project.id, name="Billing")
        top_b = _mk_comp(db, project.id, name="Payments")
        sub_a = _mk_comp(db, project.id, name="BillingStore", parent_id=top_a)
        _ = top_b
        resp = _mk_resp(db, project.id, name="persist_invoice", parent_id=sub_a)

        # Queue a reassignment of the subresp to a different subcomp
        # within the top A's subtree. Create the target subcomp first.
        sub_a2 = _mk_comp(db, project.id, name="BillingGateway", parent_id=top_a)
        q.enqueue_instruction(
            db,
            project.id,
            ReassignMapping(
                node_id=resp,
                name="persist_invoice",
                new_parent_id=sub_a2,
                new_parent_name="BillingGateway",
            ),
        )
        job_id = q.apply_pending_queue(db, project.id)
        assert job_id is not None

        _patch_session(monkeypatch, db)
        asyncio.run(q._apply_instructions_handler({"project_id": project.id}))

        # 1. The reparent event landed.
        assert "NodeReparented" in _event_types(db, project.id)
        node = db.get(Node, resp)
        assert node is not None and node.parent_id == sub_a2

        # 2. The instruction row is applied, not requeued.
        rows = db.query(PendingInstruction).filter_by(project_id=project.id).all()
        assert [r.status for r in rows] == ["applied"]

        # 3. NodeReparented is destructive per Phase 9.
        assert is_destructive(ev.NodeReparented(node_id=resp, new_parent_id=sub_a2))

    def test_add_dependency_produces_edge_via_apply(self, db, project, monkeypatch):
        """AddDependency is non-destructive — the edge lands and
        the instruction row flips to ``applied``.

        The fanout-driven staleness mark depends on whether the
        source and target already have approved content (Phase 9
        fanout short-circuits when the consumer's content is empty,
        so a fresh seed has nothing to mark). This test asserts
        the event half of the loop; the Phase 9 staleness path has
        its own dedicated tests in test_fanout.py.
        """
        a = _mk_comp(db, project.id, name="A")
        b = _mk_comp(db, project.id, name="B")

        q.enqueue_instruction(
            db,
            project.id,
            AddDependency(source_id=a, source_name="A", target_id=b, target_name="B"),
        )
        q.apply_pending_queue(db, project.id)

        _patch_session(monkeypatch, db)
        asyncio.run(q._apply_instructions_handler({"project_id": project.id}))

        edge = (
            db.query(Edge).filter_by(source_id=a, target_id=b, edge_type="dependency").one_or_none()
        )
        assert edge is not None
        rows = db.query(PendingInstruction).filter_by(project_id=project.id).all()
        assert [r.status for r in rows] == ["applied"]

    def test_delete_removes_node_via_apply(self, db, project, monkeypatch):
        """Delete drops the node through the reducer + applies the
        queue row.

        The staleness-mark side of Phase 9 destructive fanout has
        dedicated coverage in test_fanout.py; here we pin the
        Phase 11 apply contract: the ``NodeDeleted`` event lands,
        the projection reflects it, and the instruction row flips
        to applied.
        """
        a = _mk_comp(db, project.id, name="A")
        b = _mk_comp(db, project.id, name="B")
        eid = mint(db, Kind.EDGE)
        append_event(
            db,
            project.id,
            ev.EdgeCreated(
                edge_id=eid,
                edge_type="dependency",
                source_id=a,
                target_id=b,
            ),
        )

        q.enqueue_instruction(db, project.id, Delete(node_id=a, name="A"))
        q.apply_pending_queue(db, project.id)

        _patch_session(monkeypatch, db)
        asyncio.run(q._apply_instructions_handler({"project_id": project.id}))

        assert db.get(Node, a) is None
        assert "NodeDeleted" in _event_types(db, project.id)
        rows = db.query(PendingInstruction).filter_by(project_id=project.id).all()
        assert [r.status for r in rows] == ["applied"]

    def test_rename_defers_to_rewrite_job_which_updates_consumers(self, db, project, monkeypatch):
        """Full Rename flow: queue → apply → rewrite handler runs
        and consumer prose gets rewritten.
        """
        import asyncio as aio

        from backend.graph.handlers import rename_rewrite as rr

        renamed = _mk_comp(db, project.id, name="Billing")
        # Consumer node with an outgoing reference edge to the renamed one.
        consumer = _mk_comp(db, project.id, name="BillingDocs")
        consumer_node = db.get(Node, consumer)
        assert consumer_node is not None
        consumer_node.content = "BillingDocs references Billing explicitly."
        db.flush()

        eid = mint(db, Kind.EDGE)
        append_event(
            db,
            project.id,
            ev.EdgeCreated(
                edge_id=eid,
                edge_type="reference",
                source_id=consumer,
                target_id=renamed,
            ),
        )

        q.enqueue_instruction(
            db,
            project.id,
            Rename(node_id=renamed, old_name="Billing", new_name="Payments"),
        )
        q.apply_pending_queue(db, project.id)
        _patch_session(monkeypatch, db)

        # Apply dispatcher only enqueues the rewrite job.
        aio.run(q._apply_instructions_handler({"project_id": project.id}))
        from backend.graph.handlers.rename_rewrite import RENAME_REWRITE_JOB_TYPE
        from backend.models.job import Job

        rewrite_jobs = db.query(Job).filter_by(job_type=RENAME_REWRITE_JOB_TYPE).all()
        assert len(rewrite_jobs) == 1
        payload = rewrite_jobs[0].payload

        # Now run the rewrite handler (same session).
        aio.run(rr._handle(payload))

        # Name flipped.
        node = db.get(Node, renamed)
        assert node is not None and node.name == "Payments"

        # Consumer prose rewritten.
        c = db.get(Node, consumer)
        assert c is not None
        assert "Payments" in c.content
        assert "Billing explicitly" not in c.content

    def test_apply_halts_on_first_failure_and_requeues_tail(self, db, project, monkeypatch):
        """Apply halts on first failure; subsequent rows flip back
        to queued so the user can discard or retry.
        """
        nid = _mk_comp(db, project.id, name="X")
        # Row 1: valid Delete
        q.enqueue_instruction(db, project.id, Delete(node_id=nid, name="X"))
        # Row 2: Delete of a missing node — fails
        q.enqueue_instruction(db, project.id, Delete(node_id="comp_DEADBEEF", name="Gone"))
        # Row 3: harmless Rename — should flip back to queued.
        other = _mk_comp(db, project.id, name="Other")
        q.enqueue_instruction(
            db,
            project.id,
            Rename(node_id=other, old_name="Other", new_name="Other2"),
        )
        q.apply_pending_queue(db, project.id)

        _patch_session(monkeypatch, db)
        asyncio.run(q._apply_instructions_handler({"project_id": project.id}))

        rows = (
            db.query(PendingInstruction)
            .filter_by(project_id=project.id)
            .order_by(PendingInstruction.sequence.asc())
            .all()
        )
        assert [r.status for r in rows] == ["applied", "failed", "queued"]
