"""Tests for the vocabulary HTTP routes (Phase 5.5 stage 5).

Covers:

- GET list (all vocab for a project, project-level + feature-local
  flat in one response)
- GET feature-scoped list
- GET single entry
- POST create (project-level and feature-local)
- POST create validation (invalid content, invalid parent,
  duplicate name rejected)
- POST edit (replaces content)
- POST rename
- POST reparent (promote feature-local to project, demote
  project to feature-local)
- POST delete
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
from backend.graph import events as ev  # noqa: E402
from backend.graph.ids import Kind, mint  # noqa: E402
from backend.graph.reducer import append_event  # noqa: E402
from backend.main import app  # noqa: E402
from backend.models import Project  # noqa: E402


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
    db.commit()
    return p


@pytest.fixture()
def feat_billing(db, project):
    feat_id = mint(db, Kind.FEAT)
    append_event(
        db,
        project.id,
        ev.NodeCreated(
            node_id=feat_id,
            tier="feat",
            kind="domain",
            parent_id=None,
            name="Billing",
            display_order=0,
            content="Users pay for plans.",
        ),
    )
    db.commit()
    return feat_id


@pytest.fixture()
def feat_auth(db, project):
    feat_id = mint(db, Kind.FEAT)
    append_event(
        db,
        project.id,
        ev.NodeCreated(
            node_id=feat_id,
            tier="feat",
            kind="domain",
            parent_id=None,
            name="Auth",
            display_order=1,
            content="Users sign in.",
        ),
    )
    db.commit()
    return feat_id


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


def _valid_content(definition: str = "A default definition.") -> str:
    return f"<vocab-entry><definition>{definition}</definition></vocab-entry>"


class TestVocabCreate:
    def test_create_project_level(self, client, project):
        resp = client.post(
            f"/api/projects/{project.id}/vocabulary/create",
            json={
                "name": "boulder",
                "content": _valid_content("A unit of structured work."),
                "parent_id": None,
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["name"] == "boulder"
        assert body["parent_id"] is None
        assert body["parent_name"] is None
        assert body["id"].startswith("vocab_")
        assert "<vocab-entry>" in body["content"]

    def test_create_feature_local(self, client, project, feat_billing):
        resp = client.post(
            f"/api/projects/{project.id}/vocabulary/create",
            json={
                "name": "tranche",
                "content": _valid_content("A billing batch."),
                "parent_id": feat_billing,
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["parent_id"] == feat_billing
        assert body["parent_name"] == "Billing"

    def test_create_rejects_invalid_content(self, client, project):
        resp = client.post(
            f"/api/projects/{project.id}/vocabulary/create",
            json={
                "name": "boulder",
                "content": "<vocab-entry></vocab-entry>",  # missing <definition>
                "parent_id": None,
            },
        )
        assert resp.status_code == 422
        assert "definition" in resp.json()["detail"].lower()

    def test_create_rejects_invalid_parent(self, client, project):
        resp = client.post(
            f"/api/projects/{project.id}/vocabulary/create",
            json={
                "name": "boulder",
                "content": _valid_content(),
                "parent_id": "feat_MISSING0",
            },
        )
        assert resp.status_code == 404

    def test_create_rejects_non_feat_parent(self, client, project, db):
        comp_id = mint(db, Kind.COMP)
        append_event(
            db,
            project.id,
            ev.NodeCreated(
                node_id=comp_id,
                tier="comp",
                kind="domain",
                parent_id=None,
                name="SomeComp",
                display_order=0,
                content="",
            ),
        )
        db.commit()
        resp = client.post(
            f"/api/projects/{project.id}/vocabulary/create",
            json={
                "name": "boulder",
                "content": _valid_content(),
                "parent_id": comp_id,
            },
        )
        assert resp.status_code == 422
        assert "feat_*" in resp.json()["detail"]

    def test_create_rejects_duplicate_name(self, client, project):
        payload = {
            "name": "boulder",
            "content": _valid_content(),
            "parent_id": None,
        }
        r1 = client.post(f"/api/projects/{project.id}/vocabulary/create", json=payload)
        assert r1.status_code == 200
        r2 = client.post(f"/api/projects/{project.id}/vocabulary/create", json=payload)
        assert r2.status_code == 409

    def test_create_allows_same_name_in_different_scope(self, client, project, feat_billing):
        r1 = client.post(
            f"/api/projects/{project.id}/vocabulary/create",
            json={
                "name": "tranche",
                "content": _valid_content("Project meaning."),
                "parent_id": None,
            },
        )
        assert r1.status_code == 200
        r2 = client.post(
            f"/api/projects/{project.id}/vocabulary/create",
            json={
                "name": "tranche",
                "content": _valid_content("Billing meaning."),
                "parent_id": feat_billing,
            },
        )
        assert r2.status_code == 200


class TestVocabList:
    def test_empty_project(self, client, project):
        resp = client.get(f"/api/projects/{project.id}/vocabulary")
        assert resp.status_code == 200
        assert resp.json()["entries"] == []

    def test_list_mixed_scopes(self, client, project, feat_billing):
        client.post(
            f"/api/projects/{project.id}/vocabulary/create",
            json={"name": "boulder", "content": _valid_content(), "parent_id": None},
        )
        client.post(
            f"/api/projects/{project.id}/vocabulary/create",
            json={
                "name": "tranche",
                "content": _valid_content(),
                "parent_id": feat_billing,
            },
        )
        resp = client.get(f"/api/projects/{project.id}/vocabulary")
        assert resp.status_code == 200
        entries = resp.json()["entries"]
        assert len(entries) == 2
        names = {e["name"] for e in entries}
        assert names == {"boulder", "tranche"}

    def test_feature_scoped_list(self, client, project, feat_billing, feat_auth):
        client.post(
            f"/api/projects/{project.id}/vocabulary/create",
            json={"name": "boulder", "content": _valid_content(), "parent_id": None},
        )
        client.post(
            f"/api/projects/{project.id}/vocabulary/create",
            json={
                "name": "tranche",
                "content": _valid_content(),
                "parent_id": feat_billing,
            },
        )
        client.post(
            f"/api/projects/{project.id}/vocabulary/create",
            json={
                "name": "session",
                "content": _valid_content(),
                "parent_id": feat_auth,
            },
        )
        resp = client.get(f"/api/projects/{project.id}/features/{feat_billing}/vocabulary")
        assert resp.status_code == 200
        entries = resp.json()["entries"]
        assert len(entries) == 1
        assert entries[0]["name"] == "tranche"

    def test_feature_scoped_list_404_on_missing_feature(self, client, project):
        resp = client.get(f"/api/projects/{project.id}/features/feat_MISSING0/vocabulary")
        assert resp.status_code == 404


class TestVocabGet:
    def test_get_one(self, client, project):
        create_resp = client.post(
            f"/api/projects/{project.id}/vocabulary/create",
            json={"name": "boulder", "content": _valid_content(), "parent_id": None},
        )
        vocab_id = create_resp.json()["id"]
        resp = client.get(f"/api/projects/{project.id}/vocabulary/{vocab_id}")
        assert resp.status_code == 200
        assert resp.json()["name"] == "boulder"

    def test_get_missing(self, client, project):
        resp = client.get(f"/api/projects/{project.id}/vocabulary/vocab_MISSING0")
        assert resp.status_code == 404


class TestVocabEdit:
    def test_edit_replaces_content(self, client, project):
        create_resp = client.post(
            f"/api/projects/{project.id}/vocabulary/create",
            json={
                "name": "boulder",
                "content": _valid_content("Original definition."),
                "parent_id": None,
            },
        )
        vocab_id = create_resp.json()["id"]
        new_content = _valid_content("Updated definition with more detail.")
        resp = client.post(
            f"/api/projects/{project.id}/vocabulary/{vocab_id}/edit",
            json={"new_content": new_content},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "Updated definition" in body["content"]

    def test_edit_validates_content(self, client, project):
        create_resp = client.post(
            f"/api/projects/{project.id}/vocabulary/create",
            json={"name": "boulder", "content": _valid_content(), "parent_id": None},
        )
        vocab_id = create_resp.json()["id"]
        resp = client.post(
            f"/api/projects/{project.id}/vocabulary/{vocab_id}/edit",
            json={"new_content": "<vocab-entry></vocab-entry>"},  # missing definition
        )
        assert resp.status_code == 422


class TestVocabRename:
    def test_rename_happy_path(self, client, project):
        create_resp = client.post(
            f"/api/projects/{project.id}/vocabulary/create",
            json={"name": "boulder", "content": _valid_content(), "parent_id": None},
        )
        vocab_id = create_resp.json()["id"]
        resp = client.post(
            f"/api/projects/{project.id}/vocabulary/{vocab_id}/rename",
            json={"new_name": "large boulder"},
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "large boulder"

    def test_rename_rejects_duplicate_at_same_scope(self, client, project):
        client.post(
            f"/api/projects/{project.id}/vocabulary/create",
            json={"name": "boulder", "content": _valid_content(), "parent_id": None},
        )
        other_resp = client.post(
            f"/api/projects/{project.id}/vocabulary/create",
            json={"name": "foundation", "content": _valid_content(), "parent_id": None},
        )
        other_id = other_resp.json()["id"]
        resp = client.post(
            f"/api/projects/{project.id}/vocabulary/{other_id}/rename",
            json={"new_name": "boulder"},
        )
        assert resp.status_code == 409


class TestVocabReparent:
    def test_promote_feature_to_project(self, client, project, feat_billing):
        create_resp = client.post(
            f"/api/projects/{project.id}/vocabulary/create",
            json={
                "name": "tranche",
                "content": _valid_content(),
                "parent_id": feat_billing,
            },
        )
        vocab_id = create_resp.json()["id"]
        resp = client.post(
            f"/api/projects/{project.id}/vocabulary/{vocab_id}/reparent",
            json={"new_parent_id": None},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["parent_id"] is None
        assert body["parent_name"] is None

    def test_demote_project_to_feature(self, client, project, feat_billing):
        create_resp = client.post(
            f"/api/projects/{project.id}/vocabulary/create",
            json={"name": "tranche", "content": _valid_content(), "parent_id": None},
        )
        vocab_id = create_resp.json()["id"]
        resp = client.post(
            f"/api/projects/{project.id}/vocabulary/{vocab_id}/reparent",
            json={"new_parent_id": feat_billing},
        )
        assert resp.status_code == 200
        assert resp.json()["parent_id"] == feat_billing
        assert resp.json()["parent_name"] == "Billing"

    def test_reparent_rejects_non_feat_target(self, client, project, db):
        create_resp = client.post(
            f"/api/projects/{project.id}/vocabulary/create",
            json={"name": "boulder", "content": _valid_content(), "parent_id": None},
        )
        vocab_id = create_resp.json()["id"]
        comp_id = mint(db, Kind.COMP)
        append_event(
            db,
            project.id,
            ev.NodeCreated(
                node_id=comp_id,
                tier="comp",
                kind="domain",
                parent_id=None,
                name="SomeComp",
                display_order=0,
                content="",
            ),
        )
        db.commit()
        resp = client.post(
            f"/api/projects/{project.id}/vocabulary/{vocab_id}/reparent",
            json={"new_parent_id": comp_id},
        )
        assert resp.status_code == 422


class TestVocabDelete:
    def test_delete_happy_path(self, client, project, db):
        create_resp = client.post(
            f"/api/projects/{project.id}/vocabulary/create",
            json={"name": "boulder", "content": _valid_content(), "parent_id": None},
        )
        vocab_id = create_resp.json()["id"]
        resp = client.post(f"/api/projects/{project.id}/vocabulary/{vocab_id}/delete")
        assert resp.status_code == 200
        assert resp.json()["status"] == "deleted"

        # GET should now 404
        get_resp = client.get(f"/api/projects/{project.id}/vocabulary/{vocab_id}")
        assert get_resp.status_code == 404

    def test_delete_missing_404(self, client, project):
        resp = client.post(f"/api/projects/{project.id}/vocabulary/vocab_MISSING0/delete")
        assert resp.status_code == 404
