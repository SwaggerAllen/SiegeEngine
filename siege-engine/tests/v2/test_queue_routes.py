"""HTTP-route tests for the pending-change queue.

Covers the six endpoints in ``backend.graph.queue_routes``. Business
logic is tested separately in ``test_queue.py``; these tests just
pin the request/response contract + error cases.
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
from backend.graph import events as ev  # noqa: E402
from backend.graph.reducer import append_event  # noqa: E402
from backend.main import app  # noqa: E402
from backend.models import Project  # noqa: E402
from backend.models.pending_instruction import PendingInstruction  # noqa: E402


@pytest.fixture()
def engine_and_factory(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    import backend.database as _database_mod

    monkeypatch.setattr(_database_mod, "SessionLocal", factory)
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
    p = Project(id=str(uuid.uuid4()), name="T", git_repo_path="/tmp/t")
    db.add(p)
    append_event(
        db,
        p.id,
        ev.NodeCreated(
            node_id="comp_QROUT001",
            tier="comp",
            kind="domain",
            name="Target",
            content="<comparch>approved</comparch>",
        ),
    )
    db.commit()
    return p


@pytest.fixture()
def client(db):
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


def _rename_body(node_id: str, old: str, new: str) -> dict:
    return {
        "instruction": {
            "instruction_type": "Rename",
            "node_id": node_id,
            "old_name": old,
            "new_name": new,
        }
    }


class TestGetQueue:
    def test_empty_project(self, client, project):
        r = client.get(f"/api/projects/{project.id}/queue")
        assert r.status_code == 200
        body = r.json()
        assert body == {
            "queued": [],
            "running": [],
            "failed": [],
            "recent_applied": [],
            "apply_in_flight": False,
        }

    def test_404_on_unknown_project(self, client):
        r = client.get("/api/projects/nosuch/queue")
        assert r.status_code == 404

    def test_buckets_rows_by_status(self, client, project, db):
        client.post(
            f"/api/projects/{project.id}/queue/enqueue",
            json=_rename_body("comp_QROUT001", "Target", "Retarget"),
        )
        r = client.get(f"/api/projects/{project.id}/queue")
        body = r.json()
        assert len(body["queued"]) == 1
        assert body["queued"][0]["instruction_type"] == "Rename"
        assert body["queued"][0]["sequence"] == 1
        assert "Rename" in body["queued"][0]["rendered"]


class TestEnqueue:
    def test_assigns_sequence(self, client, project):
        r1 = client.post(
            f"/api/projects/{project.id}/queue/enqueue",
            json=_rename_body("comp_QROUT001", "Target", "X"),
        )
        assert r1.status_code == 200
        assert r1.json()["sequence"] == 1
        r2 = client.post(
            f"/api/projects/{project.id}/queue/enqueue",
            json=_rename_body("comp_QROUT001", "X", "Y"),
        )
        assert r2.json()["sequence"] == 2

    def test_rejects_unknown_instruction_type(self, client, project):
        r = client.post(
            f"/api/projects/{project.id}/queue/enqueue",
            json={"instruction": {"instruction_type": "Bogus", "x": 1}},
        )
        assert r.status_code == 422


class TestApply:
    def test_flips_queued_to_running_and_returns_job_id(self, client, project):
        client.post(
            f"/api/projects/{project.id}/queue/enqueue",
            json=_rename_body("comp_QROUT001", "Target", "Renamed"),
        )
        r = client.post(f"/api/projects/{project.id}/queue/apply")
        assert r.status_code == 200
        body = r.json()
        assert body["job_id"] is not None
        assert body["applied"] == 1

    def test_409_when_apply_in_flight(self, client, project):
        client.post(
            f"/api/projects/{project.id}/queue/enqueue",
            json=_rename_body("comp_QROUT001", "Target", "A"),
        )
        client.post(f"/api/projects/{project.id}/queue/apply")
        # Second apply while the first job is still queued/running.
        client.post(
            f"/api/projects/{project.id}/queue/enqueue",
            json=_rename_body("comp_QROUT001", "A", "B"),
        )
        r = client.post(f"/api/projects/{project.id}/queue/apply")
        assert r.status_code == 409

    def test_nothing_to_apply(self, client, project):
        r = client.post(f"/api/projects/{project.id}/queue/apply")
        assert r.status_code == 200
        assert r.json() == {"job_id": None, "applied": 0}


class TestDiscard:
    def test_discard_all(self, client, project):
        client.post(
            f"/api/projects/{project.id}/queue/enqueue",
            json=_rename_body("comp_QROUT001", "T", "A"),
        )
        client.post(
            f"/api/projects/{project.id}/queue/enqueue",
            json=_rename_body("comp_QROUT001", "A", "B"),
        )
        r = client.post(f"/api/projects/{project.id}/queue/discard")
        assert r.status_code == 200
        assert r.json()["discarded"] == 2

    def test_discard_single(self, client, project, db):
        enq = client.post(
            f"/api/projects/{project.id}/queue/enqueue",
            json=_rename_body("comp_QROUT001", "T", "A"),
        )
        instr_id = enq.json()["id"]
        r = client.delete(f"/api/projects/{project.id}/queue/{instr_id}")
        assert r.status_code == 200
        assert r.json() == {"ok": True}
        row = db.query(PendingInstruction).filter_by(id=instr_id).one()
        assert row.status == "discarded"

    def test_discard_single_404(self, client, project):
        r = client.delete(f"/api/projects/{project.id}/queue/nosuch")
        assert r.status_code == 404

    def test_discard_single_409_when_past_queued(self, client, project, db):
        enq = client.post(
            f"/api/projects/{project.id}/queue/enqueue",
            json=_rename_body("comp_QROUT001", "T", "A"),
        )
        instr_id = enq.json()["id"]
        # Manually flip to running.
        row = db.query(PendingInstruction).filter_by(id=instr_id).one()
        row.status = "running"
        db.commit()

        r = client.delete(f"/api/projects/{project.id}/queue/{instr_id}")
        assert r.status_code == 409


class TestRetry:
    def test_failed_row_resets_to_queued(self, client, project, db):
        enq = client.post(
            f"/api/projects/{project.id}/queue/enqueue",
            json=_rename_body("comp_QROUT001", "T", "A"),
        )
        instr_id = enq.json()["id"]
        row = db.query(PendingInstruction).filter_by(id=instr_id).one()
        row.status = "failed"
        row.error = "boom"
        db.commit()

        r = client.post(f"/api/projects/{project.id}/queue/{instr_id}/retry")
        assert r.status_code == 200
        db.refresh(row)
        assert row.status == "queued"
        assert row.error is None

    def test_retry_409_on_non_failed(self, client, project):
        enq = client.post(
            f"/api/projects/{project.id}/queue/enqueue",
            json=_rename_body("comp_QROUT001", "T", "A"),
        )
        r = client.post(f"/api/projects/{project.id}/queue/{enq.json()['id']}/retry")
        assert r.status_code == 409
