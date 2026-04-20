"""HTTP tests for the Phase 11 pending-change queue routes.

Mirrors ``test_expansion_routes.py`` in StaticPool-backed DB setup and
the cryptography-stack skip. No CLI is patched — the queue routes don't
touch the LLM.
"""

from __future__ import annotations

import os
import uuid

import pytest

os.environ.setdefault("SIEGE_DISABLE_WORKER_LOOP", "1")

try:
    import cryptography.hazmat.bindings._rust  # noqa: F401
except BaseException as _exc:  # pragma: no cover - env-dependent skip
    pytest.skip(
        f"cryptography/cffi environmental issue: {_exc!r}",
        allow_module_level=True,
    )

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from backend.auth.routes import get_current_user  # noqa: E402
from backend.database import Base, get_db  # noqa: E402
from backend.graph.broadcast import (  # noqa: E402
    BroadcastMessage,
    reset_broadcaster_for_tests,
)
from backend.main import app  # noqa: E402
from backend.models import Project  # noqa: E402
from backend.models.pending_instruction import PendingInstruction  # noqa: E402


@pytest.fixture()
def engine_and_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    yield engine, factory
    engine.dispose()


@pytest.fixture()
def db(engine_and_factory):
    _, factory = engine_and_factory
    session: Session = factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def project(db):
    p = Project(
        id=str(uuid.uuid4()),
        name="Queue Test Project",
        git_repo_path="/tmp/queue-test-repo",
    )
    db.add(p)
    db.commit()
    return p


@pytest.fixture()
def client(db, project):
    def _get_db():
        yield db

    def _get_user():
        return object()

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[get_current_user] = _get_user
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


RENAME_PAYLOAD = {
    "instruction_type": "Rename",
    "node_id": "comp_AAAAAAAA",
    "old_name": "Old",
    "new_name": "New",
}


class TestListQueue:
    def test_empty_queue_returns_empty_rows(self, client, project):
        resp = client.get(f"/api/projects/{project.id}/queue")
        assert resp.status_code == 200
        assert resp.json() == {"rows": []}

    def test_missing_project_returns_404(self, client):
        resp = client.get("/api/projects/nonexistent/queue")
        assert resp.status_code == 404

    def test_shows_queued_then_terminal(self, client, project, db):
        # Enqueue two queued instructions + a failed historical one.
        from backend.graph import queue as q
        from backend.graph.instructions import Rename

        q.enqueue_instruction(
            db, project.id, Rename(node_id="comp_A" + "A" * 7, old_name="A", new_name="B")
        )
        q.enqueue_instruction(
            db, project.id, Rename(node_id="comp_B" + "B" * 7, old_name="B", new_name="C")
        )
        historic = PendingInstruction(
            project_id=project.id,
            sequence=0,
            instruction_type="Rename",
            payload={
                "instruction_type": "Rename",
                "node_id": "comp_CCCCCCCC",
                "old_name": "C",
                "new_name": "D",
            },
            status="applied",
        )
        db.add(historic)
        db.commit()

        resp = client.get(f"/api/projects/{project.id}/queue")
        assert resp.status_code == 200
        rows = resp.json()["rows"]
        # Queued rows come first in sequence order; terminal rows after.
        assert [r["status"] for r in rows] == ["queued", "queued", "applied"]


class TestEnqueue:
    def test_enqueues_and_returns_sequence(self, client, project, db):
        resp = client.post(
            f"/api/projects/{project.id}/queue/enqueue",
            json={"instruction": RENAME_PAYLOAD},
        )
        assert resp.status_code == 200
        assert resp.json() == {"sequence": 1}

        rows = db.query(PendingInstruction).filter_by(project_id=project.id).all()
        assert len(rows) == 1
        assert rows[0].status == "queued"
        assert rows[0].instruction_type == "Rename"

    def test_rejects_unknown_instruction_type(self, client, project):
        resp = client.post(
            f"/api/projects/{project.id}/queue/enqueue",
            json={"instruction": {"instruction_type": "Fabricated", "node_id": "x"}},
        )
        assert resp.status_code == 422  # pydantic discriminator rejects


class TestDiscard:
    def test_discard_all_queued(self, client, project, db):
        from backend.graph import queue as q
        from backend.graph.instructions import Rename

        q.enqueue_instruction(
            db, project.id, Rename(node_id="comp_A" + "A" * 7, old_name="A", new_name="B")
        )
        q.enqueue_instruction(
            db, project.id, Rename(node_id="comp_B" + "B" * 7, old_name="B", new_name="C")
        )
        db.commit()

        resp = client.post(f"/api/projects/{project.id}/queue/discard", json={})
        assert resp.status_code == 200
        assert resp.json() == {"discarded": 2}

        statuses = {r.status for r in db.query(PendingInstruction).filter_by(project_id=project.id)}
        assert statuses == {"discarded"}

    def test_discard_single_sequence(self, client, project, db):
        from backend.graph import queue as q
        from backend.graph.instructions import Rename

        seq = q.enqueue_instruction(
            db, project.id, Rename(node_id="comp_A" + "A" * 7, old_name="A", new_name="B")
        )
        q.enqueue_instruction(
            db, project.id, Rename(node_id="comp_B" + "B" * 7, old_name="B", new_name="C")
        )
        db.commit()

        resp = client.post(f"/api/projects/{project.id}/queue/discard", json={"sequence": seq})
        assert resp.status_code == 200
        assert resp.json() == {"discarded": 1}


class TestApply:
    def test_returns_null_when_nothing_queued(self, client, project):
        resp = client.post(f"/api/projects/{project.id}/queue/apply")
        assert resp.status_code == 200
        assert resp.json() == {"job_id": None}

    def test_returns_job_id_when_queue_not_empty(self, client, project, db):
        from backend.graph import queue as q
        from backend.graph.instructions import Rename

        q.enqueue_instruction(
            db, project.id, Rename(node_id="comp_A" + "A" * 7, old_name="A", new_name="B")
        )
        db.commit()

        resp = client.post(f"/api/projects/{project.id}/queue/apply")
        assert resp.status_code == 200
        body = resp.json()
        assert body["job_id"] is not None


class TestBroadcastWiring:
    """Phase 11 — queue routes publish ephemeral SSE events."""

    def _capture_broadcasts(self):
        """Monkeypatch the broadcaster to capture published messages."""
        import backend.graph.broadcast as broadcast_mod

        captured: list[BroadcastMessage] = []
        broadcast_mod.get_broadcaster().publish = lambda _pid, msg: captured.append(msg)  # type: ignore[method-assign]
        return captured

    def test_enqueue_publishes_queue_instruction_appended(self, client, project):
        captured = self._capture_broadcasts()
        try:
            resp = client.post(
                f"/api/projects/{project.id}/queue/enqueue",
                json={"instruction": RENAME_PAYLOAD},
            )
            assert resp.status_code == 200
        finally:
            reset_broadcaster_for_tests()
        assert len(captured) == 1
        assert captured[0].event_type == "QueueInstructionAppended"

    def test_discard_publishes_when_rows_actually_discarded(self, client, project, db):
        from backend.graph import queue as q
        from backend.graph.instructions import Rename

        q.enqueue_instruction(
            db, project.id, Rename(node_id="comp_A" + "A" * 7, old_name="A", new_name="B")
        )
        db.commit()

        captured = self._capture_broadcasts()
        try:
            resp = client.post(f"/api/projects/{project.id}/queue/discard", json={})
            assert resp.status_code == 200
        finally:
            reset_broadcaster_for_tests()
        assert [m.event_type for m in captured] == ["QueueInstructionDiscarded"]

    def test_discard_empty_does_not_publish(self, client, project):
        captured = self._capture_broadcasts()
        try:
            resp = client.post(f"/api/projects/{project.id}/queue/discard", json={})
            assert resp.status_code == 200
        finally:
            reset_broadcaster_for_tests()
        # Nothing was actually discarded → no event.
        assert captured == []

    def test_apply_publishes_queue_applying(self, client, project, db):
        from backend.graph import queue as q
        from backend.graph.instructions import Rename

        q.enqueue_instruction(
            db, project.id, Rename(node_id="comp_A" + "A" * 7, old_name="A", new_name="B")
        )
        db.commit()

        captured = self._capture_broadcasts()
        try:
            resp = client.post(f"/api/projects/{project.id}/queue/apply")
            assert resp.status_code == 200
        finally:
            reset_broadcaster_for_tests()
        assert [m.event_type for m in captured] == ["QueueApplying"]

    def test_apply_empty_does_not_publish(self, client, project):
        captured = self._capture_broadcasts()
        try:
            resp = client.post(f"/api/projects/{project.id}/queue/apply")
            assert resp.status_code == 200
        finally:
            reset_broadcaster_for_tests()
        assert captured == []
