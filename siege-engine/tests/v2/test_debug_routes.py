"""Tests for the project debug-snapshot endpoint."""

from __future__ import annotations

import os
import uuid

import pytest

os.environ.setdefault("SIEGE_DISABLE_WORKER_LOOP", "1")

try:
    import cryptography.hazmat.bindings._rust  # noqa: F401
except BaseException as _exc:  # pragma: no cover
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
from backend.graph.ids import Kind, mint  # noqa: E402
from backend.graph.reducer import append_event  # noqa: E402
from backend.main import app  # noqa: E402
from backend.models import Project  # noqa: E402
from backend.pipeline import queue as pipeline_queue  # noqa: E402


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
    s: Session = factory()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture()
def client(db):
    project_id = str(uuid.uuid4())
    db.add(Project(id=project_id, name="T", git_repo_path="/tmp/t"))
    db.flush()

    feat_id = mint(db, Kind.FEAT)
    append_event(
        db,
        project_id,
        ev.NodeCreated(
            node_id=feat_id,
            tier="feat",
            kind="domain",
            parent_id=None,
            name="Feature A",
            display_order=0,
            content="Feature A intent.",
        ),
    )
    pipeline_queue.enqueue(
        db,
        job_type="v2.generate_requirements",
        payload={"project_id": project_id, "feedback": None},
    )
    db.commit()

    def _get_db():
        yield db

    def _get_user():
        return object()

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[get_current_user] = _get_user
    try:
        yield TestClient(app), project_id
    finally:
        app.dependency_overrides.clear()


def test_snapshot_returns_full_project_state(client):
    c, pid = client
    r = c.get(f"/api/projects/{pid}/debug/snapshot")
    assert r.status_code == 200
    body = r.json()
    assert body["project"]["id"] == pid
    assert body["summary"]["node_count"] == 1
    assert body["summary"]["edge_count"] == 0
    assert body["summary"]["events_returned"] >= 1
    assert body["summary"]["jobs_returned"] == 1

    # Node payload echoes the seeded feature.
    feat_node = next(n for n in body["nodes"] if n["tier"] == "feat")
    assert feat_node["name"] == "Feature A"
    assert feat_node["content_length"] > 0

    # Recent events include the NodeCreated.
    event_types = {e["event_type"] for e in body["recent_events"]}
    assert "NodeCreated" in event_types

    # Recent jobs filter by project_id from the payload.
    job = body["recent_jobs"][0]
    assert job["job_type"] == "v2.generate_requirements"
    assert job["payload"]["project_id"] == pid


def test_unknown_project_404s(client):
    c, _ = client
    r = c.get(f"/api/projects/{uuid.uuid4()}/debug/snapshot")
    assert r.status_code == 404


def test_event_and_job_limits_clamp(client):
    c, pid = client
    r = c.get(f"/api/projects/{pid}/debug/snapshot?events=5000&jobs=5000")
    assert r.status_code == 200
    body = r.json()
    # Caps at 2000 events / 500 jobs even when caller asks for more.
    assert body["summary"]["events_returned"] <= 2000
    assert body["summary"]["jobs_returned"] <= 500
