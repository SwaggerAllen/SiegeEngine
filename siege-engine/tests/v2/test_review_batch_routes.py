"""End-to-end tests for the Phase 12 review-batch HTTP routes.

Three endpoints:

* ``POST /projects/{id}/review/batches`` — mint a new batch.
* ``GET  /projects/{id}/review/batches/{batch_id}`` — fetch.
* ``POST /projects/{id}/review/batches/{batch_id}/close`` — close.

Mirrors the environmental-skip + StaticPool fixture pattern used by
the other ``test_*_routes`` modules. Pure CRUD; the walker queries +
diff computation they unlock are covered separately under PR-12c.
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
from backend.graph.ids import Kind, mint  # noqa: E402
from backend.graph.reducer import append_event  # noqa: E402
from backend.main import app  # noqa: E402
from backend.models import Project  # noqa: E402


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session: Session = factory()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def project(db):
    p = Project(
        id=str(uuid.uuid4()),
        name="Test Project",
        git_repo_path="/tmp/test-repo",
    )
    db.add(p)
    # Seed one event so pinned_offset is non-zero.
    feat_id = mint(db, Kind.FEAT)
    append_event(
        db,
        p.id,
        ev.NodeCreated(
            node_id=feat_id,
            tier="feat",
            kind="domain",
            parent_id=None,
            name="Login",
            display_order=0,
            content="Let users log in.",
        ),
    )
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


class TestReviewBatchRoutes:
    def test_open_returns_batch_pinned_at_latest_offset(self, client, project):
        resp = client.post(f"/api/projects/{project.id}/review/batches")
        assert resp.status_code == 200
        data = resp.json()
        assert data["project_id"] == project.id
        assert data["pinned_offset"] == 1
        assert data["closed_at"] is None
        assert data["id"].startswith("batch_")

    def test_open_on_unknown_project_returns_404(self, client):
        resp = client.post("/api/projects/proj_missing/review/batches")
        assert resp.status_code == 404

    def test_get_returns_existing_batch(self, client, project):
        opened = client.post(f"/api/projects/{project.id}/review/batches").json()
        resp = client.get(f"/api/projects/{project.id}/review/batches/{opened['id']}")
        assert resp.status_code == 200
        assert resp.json()["id"] == opened["id"]

    def test_get_on_unknown_batch_returns_404(self, client, project):
        resp = client.get(f"/api/projects/{project.id}/review/batches/batch_deadbeef")
        assert resp.status_code == 404

    def test_get_rejects_batch_from_another_project(self, client, project, db):
        # Open a batch on a second project; the first project's routes
        # must not surface it.
        other = Project(id=str(uuid.uuid4()), name="Other", git_repo_path="/tmp/o")
        db.add(other)
        db.commit()
        other_batch = client.post(f"/api/projects/{other.id}/review/batches").json()
        resp = client.get(f"/api/projects/{project.id}/review/batches/{other_batch['id']}")
        assert resp.status_code == 404

    def test_close_stamps_closed_at(self, client, project):
        opened = client.post(f"/api/projects/{project.id}/review/batches").json()
        resp = client.post(f"/api/projects/{project.id}/review/batches/{opened['id']}/close")
        assert resp.status_code == 200
        assert resp.json()["closed_at"] is not None

    def test_close_is_idempotent(self, client, project):
        opened = client.post(f"/api/projects/{project.id}/review/batches").json()
        first = client.post(
            f"/api/projects/{project.id}/review/batches/{opened['id']}/close"
        ).json()
        second = client.post(
            f"/api/projects/{project.id}/review/batches/{opened['id']}/close"
        ).json()
        # Second close leaves the original timestamp intact.
        assert first["closed_at"] == second["closed_at"]

    def test_close_on_unknown_batch_returns_404(self, client, project):
        resp = client.post(f"/api/projects/{project.id}/review/batches/batch_deadbeef/close")
        assert resp.status_code == 404
