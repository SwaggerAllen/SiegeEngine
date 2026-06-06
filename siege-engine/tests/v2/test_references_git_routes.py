"""Tests for the v3 git-backed references endpoints.

POST /api/projects/<id>/references — register a ref with a
caller-minted ref_id + body_sha + body_path.

GET /api/projects/<id>/references/by-name — name lookup.
"""

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
from backend.graph.ids import Kind, mint  # noqa: E402
from backend.main import app  # noqa: E402
from backend.models import Project, User  # noqa: E402
from backend.models.node import Node  # noqa: E402


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
def project(db):
    p = Project(id=str(uuid.uuid4()), name="Test", git_repo_path="/tmp/test")
    db.add(p)
    db.commit()
    return p


@pytest.fixture()
def client(db, project):
    def _get_db():
        yield db

    def _get_user():
        return User(id="u1", username="t", password_hash="x", role="admin")

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[get_current_user] = _get_user
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


class TestCreateGitReference:
    def test_creates_ref_node_with_body_sha_and_path(self, client, project, db):
        ref_id = mint(db, Kind.REF)
        db.commit()
        resp = client.post(
            f"/api/projects/{project.id}/references",
            json={
                "ref_id": ref_id,
                "name": "Stripe API summary",
                "body_sha": "deadbeef" * 5,
                "body_path": f"refs/{ref_id}/body.md",
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["id"] == ref_id
        assert body["name"] == "Stripe API summary"
        assert body["body_sha"] == "deadbeef" * 5
        assert body["body_path"] == f"refs/{ref_id}/body.md"
        # Row was minted via the reducer.
        row = db.get(Node, ref_id)
        assert row is not None
        assert row.tier == "ref"
        assert row.body_sha == "deadbeef" * 5
        assert row.body_path == f"refs/{ref_id}/body.md"
        assert "git-resident" in row.content

    def test_default_body_path_from_ref_id(self, client, project, db):
        ref_id = mint(db, Kind.REF)
        db.commit()
        resp = client.post(
            f"/api/projects/{project.id}/references",
            json={
                "ref_id": ref_id,
                "name": "Default-path ref",
                "body_sha": "cafebabe" * 5,
            },
        )
        assert resp.status_code == 200
        assert resp.json()["body_path"] == f"refs/{ref_id}/body.md"

    def test_rejects_malformed_ref_id(self, client, project):
        resp = client.post(
            f"/api/projects/{project.id}/references",
            json={"ref_id": "not-a-ref-id", "name": "x", "body_sha": "abc"},
        )
        assert resp.status_code == 422
        assert "ref_id must match" in resp.json()["detail"]

    def test_rejects_empty_name(self, client, project, db):
        ref_id = mint(db, Kind.REF)
        db.commit()
        resp = client.post(
            f"/api/projects/{project.id}/references",
            json={"ref_id": ref_id, "name": "  ", "body_sha": "abc"},
        )
        assert resp.status_code == 422

    def test_rejects_duplicate_ref_id(self, client, project, db):
        ref_id = mint(db, Kind.REF)
        db.commit()
        client.post(
            f"/api/projects/{project.id}/references",
            json={"ref_id": ref_id, "name": "First", "body_sha": "a" * 64},
        )
        resp = client.post(
            f"/api/projects/{project.id}/references",
            json={"ref_id": ref_id, "name": "Second", "body_sha": "b" * 64},
        )
        assert resp.status_code == 409
        assert "already exists" in resp.json()["detail"]

    def test_rejects_duplicate_name(self, client, project, db):
        ref_id_a = mint(db, Kind.REF)
        ref_id_b = mint(db, Kind.REF)
        db.commit()
        client.post(
            f"/api/projects/{project.id}/references",
            json={"ref_id": ref_id_a, "name": "Shared name", "body_sha": "a" * 64},
        )
        resp = client.post(
            f"/api/projects/{project.id}/references",
            json={"ref_id": ref_id_b, "name": "Shared name", "body_sha": "b" * 64},
        )
        assert resp.status_code == 409
        assert "already exists" in resp.json()["detail"]

    def test_unknown_project_is_404(self, client, db):
        ref_id = mint(db, Kind.REF)
        db.commit()
        resp = client.post(
            "/api/projects/no-such-project/references",
            json={"ref_id": ref_id, "name": "x", "body_sha": "abc" * 16},
        )
        assert resp.status_code == 404


class TestGetReferenceByName:
    def test_returns_ref_when_present(self, client, project, db):
        ref_id = mint(db, Kind.REF)
        db.commit()
        client.post(
            f"/api/projects/{project.id}/references",
            json={"ref_id": ref_id, "name": "Lookup me", "body_sha": "a" * 64},
        )
        resp = client.get(
            f"/api/projects/{project.id}/references/by-name",
            params={"name": "Lookup me"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body is not None
        assert body["id"] == ref_id
        assert body["name"] == "Lookup me"

    def test_returns_null_when_absent(self, client, project):
        resp = client.get(
            f"/api/projects/{project.id}/references/by-name",
            params={"name": "Not present"},
        )
        assert resp.status_code == 200
        assert resp.json() is None
