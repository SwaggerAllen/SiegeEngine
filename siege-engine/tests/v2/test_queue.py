"""Tests for the pending-instruction queue."""

from __future__ import annotations

import asyncio

import pytest

from backend.graph import events as ev
from backend.graph import queue as q
from backend.graph.instructions import Rename
from backend.graph.reducer import append_event
from backend.models import Project
from backend.models.job import Job
from backend.models.node import Node
from backend.models.pending_instruction import PendingInstruction


def _mk_rename(node_id: str, old: str, new: str) -> Rename:
    return Rename(node_id=node_id, old_name=old, new_name=new)


def _seed_node(db, project_id: str, node_id: str, name: str) -> None:
    """Mint a comp node so rename/delete instructions have a target."""
    append_event(
        db,
        project_id,
        ev.NodeCreated(
            node_id=node_id,
            tier="comp",
            kind="domain",
            name=name,
            content="<comparch>approved</comparch>",
        ),
    )


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
    def test_discards_only_queued(self, db, project):
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


class TestApplyInstructionsHandler:
    """The real handler dispatches each running instruction to its
    applier, which emits events via append_event. The row flips to
    ``applied`` on success, ``failed`` with an error on exception —
    other rows keep running regardless.
    """

    def test_rename_applies_and_renames_the_node(self, db, project, monkeypatch):
        _seed_node(db, project.id, "comp_AAAAAAAA", "Old")
        q.enqueue_instruction(db, project.id, _mk_rename("comp_AAAAAAAA", "Old", "New"))
        job_id = q.apply_pending_queue(db, project.id)
        assert job_id is not None

        monkeypatch.setattr(q, "SessionLocal", lambda: _NoCloseProxy(db))
        asyncio.run(q.apply_instructions({"project_id": project.id}))

        rows = db.query(PendingInstruction).filter_by(project_id=project.id).all()
        assert [r.status for r in rows] == ["applied"]
        node = db.get(Node, "comp_AAAAAAAA")
        assert node is not None and node.name == "New"

    def test_failing_instruction_marks_row_failed_and_continues(self, db, project, monkeypatch):
        # First instruction targets a real node; second targets a
        # nonexistent node and will fail at reducer time. Third also
        # real — must still apply even though the second failed.
        _seed_node(db, project.id, "comp_AAAAAAAA", "A")
        _seed_node(db, project.id, "comp_CCCCCCCC", "C")
        q.enqueue_instruction(db, project.id, _mk_rename("comp_AAAAAAAA", "A", "A2"))
        q.enqueue_instruction(db, project.id, _mk_rename("comp_NOSUCH99", "x", "y"))
        q.enqueue_instruction(db, project.id, _mk_rename("comp_CCCCCCCC", "C", "C2"))

        q.apply_pending_queue(db, project.id)
        monkeypatch.setattr(q, "SessionLocal", lambda: _NoCloseProxy(db))
        asyncio.run(q.apply_instructions({"project_id": project.id}))

        rows = (
            db.query(PendingInstruction)
            .filter_by(project_id=project.id)
            .order_by(PendingInstruction.sequence)
            .all()
        )
        assert [r.status for r in rows] == ["applied", "failed", "applied"]
        assert rows[1].error is not None and len(rows[1].error) > 0
        assert db.get(Node, "comp_AAAAAAAA").name == "A2"
        assert db.get(Node, "comp_CCCCCCCC").name == "C2"

    def test_rejects_missing_project_id(self):
        with pytest.raises(ValueError, match="missing project_id"):
            asyncio.run(q.apply_instructions({}))


class TestDecompositionInstructions:
    """The new AddDecomposition / RemoveDecomposition instructions
    project to EdgeCreated / EdgeDeleted events on decomposition edges.
    """

    def test_add_then_remove_decomposition_round_trips(self, db, project, monkeypatch):
        from backend.graph.instructions import (
            AddDecomposition,
            RemoveDecomposition,
        )
        from backend.models.node import Edge

        _seed_node(db, project.id, "feat_DECM0001", "Feat")
        _seed_node(db, project.id, "resp_DECM0001", "Resp")

        q.enqueue_instruction(
            db,
            project.id,
            AddDecomposition(
                source_id="feat_DECM0001",
                source_name="Feat",
                target_id="resp_DECM0001",
                target_name="Resp",
            ),
        )
        q.apply_pending_queue(db, project.id)
        monkeypatch.setattr(q, "SessionLocal", lambda: _NoCloseProxy(db))
        asyncio.run(q.apply_instructions({"project_id": project.id}))

        edges = db.query(Edge).filter_by(edge_type="decomposition").all()
        assert len(edges) == 1
        assert edges[0].source_id == "feat_DECM0001"
        assert edges[0].target_id == "resp_DECM0001"

        q.enqueue_instruction(
            db,
            project.id,
            RemoveDecomposition(
                source_id="feat_DECM0001",
                source_name="Feat",
                target_id="resp_DECM0001",
                target_name="Resp",
            ),
        )
        q.apply_pending_queue(db, project.id)
        asyncio.run(q.apply_instructions({"project_id": project.id}))

        assert db.query(Edge).filter_by(edge_type="decomposition").count() == 0


class _NoCloseProxy:
    """Wrap a Session so .close() is a no-op (fixture owns the real close)."""

    def __init__(self, session):
        self._session = session

    def __getattr__(self, name):
        return getattr(self._session, name)

    def close(self):  # no-op
        return None
