"""Tests for the v3 input-document endpoints.

POST /api/projects/<id>/input-documents — register a
git-resident input document.
GET  /api/projects/<id>/input-documents — list rows.
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

from datetime import datetime  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from backend.auth.routes import get_current_user  # noqa: E402
from backend.database import Base, get_db  # noqa: E402
from backend.main import app  # noqa: E402
from backend.models import InputDocument, Project, User  # noqa: E402


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


class TestCreateInputDocument:
    def test_creates_row_with_body_sha_and_path(self, client, project, db):
        resp = client.post(
            f"/api/projects/{project.id}/input-documents",
            json={
                "role": "project_doc",
                "name": "My Project Spec",
                "body_sha": "deadbeef" * 5,
                "body_path": "inputs/project_doc.md",
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["doc_type"] == "project_doc"
        assert body["name"] == "My Project Spec"
        assert body["body_sha"] == "deadbeef" * 5
        assert body["body_path"] == "inputs/project_doc.md"
        # Round-trip the row directly to confirm persistence.
        row = db.get(InputDocument, body["id"])
        assert row is not None
        assert row.body_sha == "deadbeef" * 5
        assert row.body_path == "inputs/project_doc.md"
        # Sentinel content keeps the NOT NULL constraint satisfied
        # without storing the real body inline.
        assert "git-resident" in row.content

    def test_default_body_path_from_role(self, client, project):
        """When body_path isn't supplied, falls back to inputs/<role>.md."""
        resp = client.post(
            f"/api/projects/{project.id}/input-documents",
            json={
                "role": "domain_spec",
                "name": "Domain Constraints",
                "body_sha": "cafebabe" * 5,
            },
        )
        assert resp.status_code == 200
        assert resp.json()["body_path"] == "inputs/domain_spec.md"

    def test_rejects_empty_role(self, client, project):
        resp = client.post(
            f"/api/projects/{project.id}/input-documents",
            json={"role": "  ", "name": "x", "body_sha": "abc"},
        )
        assert resp.status_code == 422

    def test_rejects_empty_body_sha(self, client, project):
        resp = client.post(
            f"/api/projects/{project.id}/input-documents",
            json={"role": "project_doc", "name": "x", "body_sha": ""},
        )
        assert resp.status_code == 422

    def test_unknown_project_is_404(self, client):
        resp = client.post(
            "/api/projects/does-not-exist/input-documents",
            json={
                "role": "project_doc",
                "name": "x",
                "body_sha": "abc",
            },
        )
        assert resp.status_code == 404


class TestListInputDocuments:
    def test_returns_rows_newest_first(self, client, project, db):
        older = InputDocument(
            id="doc_older",
            project_id=project.id,
            name="Older",
            content="<git-resident>",
            doc_type="project_doc",
            body_sha="a" * 64,
            body_path="inputs/project_doc.md",
            created_at=datetime(2026, 1, 1),
        )
        newer = InputDocument(
            id="doc_newer",
            project_id=project.id,
            name="Newer",
            content="<git-resident>",
            doc_type="domain_spec",
            body_sha="b" * 64,
            body_path="inputs/domain_spec.md",
            created_at=datetime(2026, 6, 1),
        )
        db.add_all([older, newer])
        db.commit()

        resp = client.get(f"/api/projects/{project.id}/input-documents")
        assert resp.status_code == 200
        ids = [d["id"] for d in resp.json()["input_documents"]]
        assert ids == ["doc_newer", "doc_older"]

    def test_returns_empty_list_for_no_docs(self, client, project):
        resp = client.get(f"/api/projects/{project.id}/input-documents")
        assert resp.status_code == 200
        assert resp.json()["input_documents"] == []

    def test_includes_legacy_rows_with_null_body_sha(self, client, project, db):
        """Legacy rows (no body_sha) still surface in the listing
        with body_sha=null so the frontend can distinguish them."""
        legacy = InputDocument(
            id="doc_legacy",
            project_id=project.id,
            name="Legacy",
            content="The full content stored inline.",
            doc_type="project_doc",
            body_sha=None,
            body_path=None,
            created_at=datetime(2026, 1, 1),
        )
        db.add(legacy)
        db.commit()

        resp = client.get(f"/api/projects/{project.id}/input-documents")
        rows = resp.json()["input_documents"]
        assert len(rows) == 1
        assert rows[0]["body_sha"] is None
        assert rows[0]["body_path"] is None
