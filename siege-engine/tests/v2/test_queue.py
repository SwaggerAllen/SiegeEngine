"""Tests for the pending-instruction queue."""

from __future__ import annotations

import asyncio

import pytest

from backend.graph import queue as q
from backend.graph.instructions import Rename
from backend.models import Project
from backend.models.job import Job
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
    def test_discards_only_queued(self, db, project):
        q.enqueue_instruction(db, project.id, _mk_rename("comp_AAAAAAAA", "a", "b"))
        q.enqueue_instruction(db, project.id, _mk_rename("comp_BBBBBBBB", "c", "d"))
        # Mark one as applied manually; it should be left alone.
        rows = db.query(PendingInstruction).filter_by(project_id=project.id).all()
        rows[0].status = "applied"
        db.flush()

        count = q.discard_pending(db, project.id)
        assert count == 1
        statuses = {
            r.status for r in db.query(PendingInstruction).filter_by(project_id=project.id)
        }
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


class TestStubHandler:
    def test_marks_running_rows_applied(self, db, project, monkeypatch):
        # Enqueue two instructions and kick them to running.
        q.enqueue_instruction(db, project.id, _mk_rename("comp_AAAAAAAA", "a", "b"))
        q.enqueue_instruction(db, project.id, _mk_rename("comp_BBBBBBBB", "c", "d"))
        job_id = q.apply_pending_queue(db, project.id)
        assert job_id is not None

        # Point the handler's SessionLocal at our test session so it sees
        # the rows without opening a fresh DB connection.
        class _FakeSessionLocal:
            def __call__(self_inner):
                return _NoCloseProxy(db)

        def _factory():
            return _NoCloseProxy(db)

        monkeypatch.setattr(q, "SessionLocal", _factory)

        asyncio.run(q._stub_apply_instructions({"project_id": project.id}))

        rows = db.query(PendingInstruction).filter_by(project_id=project.id).all()
        assert all(r.status == "applied" for r in rows)

    def test_rejects_missing_project_id(self):
        with pytest.raises(ValueError, match="missing project_id"):
            asyncio.run(q._stub_apply_instructions({}))


class _NoCloseProxy:
    """Wrap a Session so .close() is a no-op (fixture owns the real close)."""

    def __init__(self, session):
        self._session = session

    def __getattr__(self, name):
        return getattr(self._session, name)

    def close(self):  # no-op
        return None
