"""Tests for v3 git-backed vocabulary endpoints."""

from __future__ import annotations

import os
import uuid

import pytest

os.environ.setdefault("SIEGE_DISABLE_WORKER_LOOP", "1")

try:
    import cryptography.hazmat.bindings._rust  # noqa: F401
except BaseException as _exc:  # pragma: no cover
    pytest.skip(f"cryptography/cffi: {_exc!r}", allow_module_level=True)

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


class TestCreateGitVocab:
    def test_creates_vocab_node_with_git_coords(self, client, project, db):
        vocab_id = mint(db, Kind.VOCAB)
        db.commit()
        resp = client.post(
            f"/api/projects/{project.id}/vocabulary",
            json={
                "vocab_id": vocab_id,
                "name": "billing cycle",
                "body_sha": "abc" * 22,
                "body_path": f"vocab/{vocab_id}/body.md",
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["id"] == vocab_id
        assert body["body_sha"] == "abc" * 22
        row = db.get(Node, vocab_id)
        assert row is not None
        assert row.tier == "vocab"
        assert row.body_path == f"vocab/{vocab_id}/body.md"

    def test_rejects_malformed_id(self, client, project):
        resp = client.post(
            f"/api/projects/{project.id}/vocabulary",
            json={"vocab_id": "bad", "name": "x", "body_sha": "abc"},
        )
        assert resp.status_code == 422

    def test_rejects_duplicate_name(self, client, project, db):
        a = mint(db, Kind.VOCAB)
        b = mint(db, Kind.VOCAB)
        db.commit()
        client.post(
            f"/api/projects/{project.id}/vocabulary",
            json={"vocab_id": a, "name": "Shared", "body_sha": "a" * 64},
        )
        resp = client.post(
            f"/api/projects/{project.id}/vocabulary",
            json={"vocab_id": b, "name": "Shared", "body_sha": "b" * 64},
        )
        assert resp.status_code == 409


class TestGetVocabByName:
    def test_returns_entry_when_present(self, client, project, db):
        vocab_id = mint(db, Kind.VOCAB)
        db.commit()
        client.post(
            f"/api/projects/{project.id}/vocabulary",
            json={"vocab_id": vocab_id, "name": "Find me", "body_sha": "x" * 64},
        )
        resp = client.get(
            f"/api/projects/{project.id}/vocabulary/by-name",
            params={"name": "Find me"},
        )
        assert resp.status_code == 200
        assert resp.json()["id"] == vocab_id

    def test_returns_null_when_absent(self, client, project):
        resp = client.get(
            f"/api/projects/{project.id}/vocabulary/by-name",
            params={"name": "Absent"},
        )
        assert resp.status_code == 200
        assert resp.json() is None
