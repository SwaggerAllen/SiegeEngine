"""Tests for the pending-instruction queue."""

from __future__ import annotations

import asyncio

import pytest

from backend.graph import events as ev
from backend.graph import queue as q
from backend.graph.ids import Kind, mint
from backend.graph.instructions import (
    AddDependency,
    Create,
    Delete,
    Rename,
)
from backend.graph.reducer import append_event
from backend.models import Project
from backend.models.job import Job
from backend.models.node import Node
from backend.models.pending_instruction import PendingInstruction


def _mk_rename(node_id: str, old: str, new: str) -> Rename:
    return Rename(node_id=node_id, old_name=old, new_name=new)


class TestEnqueueInstruction:
    def test_assigns_sequential_numbers(self, db, project):
        seqs = [
            q.enqueue_instruction(db, project.id, _mk_rename("comp_AAAAAAAA", "a", "b")),
            q.enqueue_instruction(db, project.id, _mk_rename("comp_BBBBBBBB", "c", "d")),
            q.enqueue_instruction(db, project.id, _mk_rename("comp_CCCCCCCC", "e", "f")),
        ]
        assert seqs == [1, 2, 3]

    def test_sequences_are_per_project(self, db, project):
        other = Project(id=project.id + "-x", name="Other", git_repo_path="/tmp/other")
        db.add(other)
        db.flush()

        a1 = q.enqueue_instruction(db, project.id, _mk_rename("comp_AAAAAAAA", "a", "b"))
        b1 = q.enqueue_instruction(db, other.id, _mk_rename("comp_BBBBBBBB", "c", "d"))
        a2 = q.enqueue_instruction(db, project.id, _mk_rename("comp_AAAAAAAA", "b", "c"))
        assert a1 == 1 and b1 == 1 and a2 == 2

    def test_writes_status_queued(self, db, project):
        q.enqueue_instruction(db, project.id, _mk_rename("comp_AAAAAAAA", "a", "b"))
        rows = db.query(PendingInstruction).filter_by(project_id=project.id).all()
        assert len(rows) == 1
        assert rows[0].status == "queued"
        assert rows[0].instruction_type == "Rename"


class TestDiscardPending:
    def test_discards_all_queued_when_no_sequence(self, db, project):
        q.enqueue_instruction(db, project.id, _mk_rename("comp_AAAAAAAA", "a", "b"))
        q.enqueue_instruction(db, project.id, _mk_rename("comp_BBBBBBBB", "c", "d"))
        # Mark one as applied manually; it should be left alone.
        rows = db.query(PendingInstruction).filter_by(project_id=project.id).all()
        rows[0].status = "applied"
        db.flush()

        count = q.discard_pending(db, project.id)
        assert count == 1
        statuses = {r.status for r in db.query(PendingInstruction).filter_by(project_id=project.id)}
        assert statuses == {"applied", "discarded"}

    def test_discards_single_sequence(self, db, project):
        seq_a = q.enqueue_instruction(db, project.id, _mk_rename("comp_AAAAAAAA", "a", "b"))
        q.enqueue_instruction(db, project.id, _mk_rename("comp_BBBBBBBB", "c", "d"))
        count = q.discard_pending(db, project.id, sequence=seq_a)
        assert count == 1
        rows = {
            r.sequence: r.status
            for r in db.query(PendingInstruction).filter_by(project_id=project.id)
        }
        assert rows[seq_a] == "discarded"

    def test_returns_zero_when_nothing_queued(self, db, project):
        assert q.discard_pending(db, project.id) == 0


class TestApplyPendingQueue:
    def test_returns_none_when_nothing_queued(self, db, project):
        assert q.apply_pending_queue(db, project.id) is None

    def test_flips_to_running_and_enqueues_one_job(self, db, project):
        q.enqueue_instruction(db, project.id, _mk_rename("comp_AAAAAAAA", "a", "b"))
        q.enqueue_instruction(db, project.id, _mk_rename("comp_BBBBBBBB", "c", "d"))

        job_id = q.apply_pending_queue(db, project.id)
        assert job_id is not None

        # Exactly one job was created.
        jobs = db.query(Job).filter_by(job_type=q.APPLY_INSTRUCTIONS_JOB_TYPE).all()
        assert len(jobs) == 1
        assert jobs[0].id == job_id
        assert jobs[0].payload == {"project_id": project.id}

        # All rows are now running, linked to the job.
        rows = db.query(PendingInstruction).filter_by(project_id=project.id).all()
        assert all(r.status == "running" for r in rows)
        assert all(r.job_id == job_id for r in rows)


class TestApplyHandler:
    """Exercise the real ``_apply_instructions_handler`` end-to-end.

    Uses the same ``_NoCloseProxy`` shim the stub tests used so the
    handler's ``SessionLocal()`` call returns the fixture session.
    """

    def _patch_session(self, db, monkeypatch):
        monkeypatch.setattr(q, "SessionLocal", lambda: _NoCloseProxy(db))

    def _capture_broadcasts(self, monkeypatch):
        """Capture published messages. Returns the list for assertions."""
        import backend.graph.broadcast as broadcast_mod

        captured: list = []
        broadcaster = broadcast_mod.get_broadcaster()
        original = broadcaster.publish
        monkeypatch.setattr(broadcaster, "publish", lambda _pid, msg: captured.append(msg))
        monkeypatch.setattr(broadcaster, "_original", original, raising=False)
        return captured

    def test_marks_running_rows_applied(self, db, project, monkeypatch):
        # Create a real node so the Rename dispatch doesn't raise.
        node_id = mint(db, Kind.COMP)
        append_event(
            db,
            project.id,
            ev.NodeCreated(
                node_id=node_id,
                tier="comp",
                kind="domain",
                name="Old",
            ),
        )
        q.enqueue_instruction(db, project.id, _mk_rename(node_id, "Old", "New"))
        assert q.apply_pending_queue(db, project.id) is not None

        self._patch_session(db, monkeypatch)
        asyncio.run(q._apply_instructions_handler({"project_id": project.id}))

        rows = db.query(PendingInstruction).filter_by(project_id=project.id).all()
        assert [r.status for r in rows] == ["applied"]
        node = db.get(Node, node_id)
        assert node is not None and node.name == "New"

    def test_halts_on_first_failure_requeues_subsequent(self, db, project, monkeypatch):
        # Row 1 is a Delete of an existing node (succeeds).
        nid = mint(db, Kind.COMP)
        append_event(
            db,
            project.id,
            ev.NodeCreated(node_id=nid, tier="comp", kind="domain", name="X"),
        )
        q.enqueue_instruction(db, project.id, Delete(node_id=nid, name="X"))
        # Row 2 is a Delete of a missing node (fails).
        q.enqueue_instruction(db, project.id, Delete(node_id="comp_DEADBEEF", name="Gone"))
        # Row 3 is a harmless Create — should flip back to queued.
        q.enqueue_instruction(
            db,
            project.id,
            Create(node_id="feat_AAAAAAAA", tier="feat", name="Never"),
        )

        q.apply_pending_queue(db, project.id)
        self._patch_session(db, monkeypatch)
        asyncio.run(q._apply_instructions_handler({"project_id": project.id}))

        rows = (
            db.query(PendingInstruction)
            .filter_by(project_id=project.id)
            .order_by(PendingInstruction.sequence.asc())
            .all()
        )
        statuses = [r.status for r in rows]
        assert statuses == ["applied", "failed", "queued"]
        assert rows[1].error is not None and "not found" in rows[1].error.lower()

    def test_cycle_detection_halts_and_surfaces_path(self, db, project, monkeypatch):
        a = mint(db, Kind.COMP)
        b = mint(db, Kind.COMP)
        for nid, name in [(a, "A"), (b, "B")]:
            append_event(
                db,
                project.id,
                ev.NodeCreated(node_id=nid, tier="comp", kind="domain", name=name),
            )

        q.enqueue_instruction(
            db,
            project.id,
            AddDependency(source_id=a, source_name="A", target_id=b, target_name="B"),
        )
        q.enqueue_instruction(
            db,
            project.id,
            AddDependency(source_id=b, source_name="B", target_id=a, target_name="A"),
        )
        q.apply_pending_queue(db, project.id)
        self._patch_session(db, monkeypatch)
        asyncio.run(q._apply_instructions_handler({"project_id": project.id}))

        rows = (
            db.query(PendingInstruction)
            .filter_by(project_id=project.id)
            .order_by(PendingInstruction.sequence.asc())
            .all()
        )
        assert [r.status for r in rows] == ["applied", "failed"]
        assert "cycle" in (rows[1].error or "").lower()

    def test_rejects_missing_project_id(self):
        with pytest.raises(ValueError, match="missing project_id"):
            asyncio.run(q._apply_instructions_handler({}))

    def test_success_publishes_queue_applied_with_node_ids(self, db, project, monkeypatch):
        nid = mint(db, Kind.COMP)
        append_event(
            db,
            project.id,
            ev.NodeCreated(node_id=nid, tier="comp", kind="domain", name="Old"),
        )
        q.enqueue_instruction(db, project.id, _mk_rename(nid, "Old", "New"))
        q.apply_pending_queue(db, project.id)

        self._patch_session(db, monkeypatch)
        captured = self._capture_broadcasts(monkeypatch)
        asyncio.run(q._apply_instructions_handler({"project_id": project.id}))

        # The last broadcast is the terminal QueueApplied / QueueFailed.
        terminal = captured[-1]
        assert terminal.event_type == "QueueApplied"
        assert nid in terminal.node_ids

    def test_failure_publishes_queue_failed(self, db, project, monkeypatch):
        # Queue a Delete against a non-existent node so the dispatcher raises.
        q.enqueue_instruction(db, project.id, Delete(node_id="comp_DEADBEEF", name="Gone"))
        q.apply_pending_queue(db, project.id)

        self._patch_session(db, monkeypatch)
        captured = self._capture_broadcasts(monkeypatch)
        asyncio.run(q._apply_instructions_handler({"project_id": project.id}))

        terminal = captured[-1]
        assert terminal.event_type == "QueueFailed"


class _NoCloseProxy:
    """Wrap a Session so .close() is a no-op (fixture owns the real close)."""

    def __init__(self, session):
        self._session = session

    def __getattr__(self, name):
        return getattr(self._session, name)

    def close(self):  # no-op
        return None
