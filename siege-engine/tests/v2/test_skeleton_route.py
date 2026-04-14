"""Tests for the /debug/skeleton endpoint (content-stripped snapshot)."""

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
from backend.graph.fragments import FragmentKind, fragment_id  # noqa: E402
from backend.graph.ids import Kind, mint  # noqa: E402
from backend.graph.reducer import append_event  # noqa: E402
from backend.main import app  # noqa: E402
from backend.models import Project  # noqa: E402
from backend.models.job import Job  # noqa: E402


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
    p = Project(id=str(uuid.uuid4()), name="T", git_repo_path="/tmp/t")
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


class TestSkeletonEndpoint:
    def test_empty_project(self, client, project):
        resp = client.get(f"/api/projects/{project.id}/debug/skeleton")
        assert resp.status_code == 200
        body = resp.json()
        assert body["nodes"] == []
        assert body["edges"] == []
        assert body["fragments"] == []
        assert body["drafts"] == []
        assert body["recent_jobs"] == []
        assert "event_count" in body
        assert "latest_offset" in body

    def test_unknown_project_is_404(self, client):
        resp = client.get("/api/projects/does-not-exist/debug/skeleton")
        assert resp.status_code == 404

    def test_node_content_is_replaced_with_length(self, client, project, db):
        # Seed a node with a big content field
        big_content = "A" * 5000
        rid = mint(db, Kind.RESP)
        append_event(
            db,
            project.id,
            ev.NodeCreated(
                node_id=rid,
                tier="resp",
                kind="domain",
                parent_id=None,
                name="BigResp",
                display_order=0,
                content=big_content,
            ),
        )
        db.commit()

        resp = client.get(f"/api/projects/{project.id}/debug/skeleton")
        body = resp.json()
        assert len(body["nodes"]) == 1
        node = body["nodes"][0]
        # content_length present, content itself absent
        assert node["content_length"] == 5000
        assert "content" not in node
        # Name is preserved (it's an identifier, not prose)
        assert node["name"] == "BigResp"
        # Tier + id + parent_id + kind are preserved
        assert node["tier"] == "resp"
        assert node["kind"] == "domain"
        assert node["id"] == rid

    def test_fragment_content_is_replaced_with_length(self, client, project, db):
        cid = mint(db, Kind.COMP)
        append_event(
            db,
            project.id,
            ev.NodeCreated(
                node_id=cid,
                tier="comp",
                kind="domain",
                parent_id=None,
                name="C",
                display_order=0,
                content="",
            ),
        )
        frag_content = "X" * 1200
        append_event(
            db,
            project.id,
            ev.FragmentUpdated(
                fragment_id=fragment_id(cid, FragmentKind.TECHSPEC),
                owner_id=cid,
                fragment_kind=FragmentKind.TECHSPEC,
                new_content=frag_content,
            ),
        )
        db.commit()

        resp = client.get(f"/api/projects/{project.id}/debug/skeleton")
        body = resp.json()
        assert len(body["fragments"]) == 1
        frag = body["fragments"][0]
        assert frag["content_length"] == 1200
        assert "content" not in frag

    def test_recent_jobs_includes_latest_per_type_with_error_tail(self, client, project, db):
        # Seed two failed jobs of the same type + one successful,
        # one queued of a different type. The response should show
        # the latest of each type, with error_tail only on the
        # failed one.
        db.add(
            Job(
                id="job_old_failed",
                job_type="v2.generate_sysarch",
                payload={"project_id": project.id, "feedback": None},
                status="failed",
                error_message="Old error — should not appear",
            )
        )
        # Create the newer failed job with a distinctive error
        db.add(
            Job(
                id="job_new_failed",
                job_type="v2.generate_sysarch",
                payload={"project_id": project.id, "feedback": None},
                status="failed",
                error_message="Newer error: max budget exceeded",
                retry_count=2,
            )
        )
        db.add(
            Job(
                id="job_queued",
                job_type="v2.generate_comparch",
                payload={"project_id": project.id, "component_id": "comp_x"},
                status="queued",
            )
        )
        db.commit()

        resp = client.get(f"/api/projects/{project.id}/debug/skeleton")
        body = resp.json()
        assert len(body["recent_jobs"]) == 2
        jobs_by_type = {j["job_type"]: j for j in body["recent_jobs"]}
        # Sysarch: only the newest failed entry is kept
        sysarch = jobs_by_type["v2.generate_sysarch"]
        assert sysarch["status"] == "failed"
        assert "Newer error" in sysarch.get("error_tail", "")
        assert "Old error" not in sysarch.get("error_tail", "")
        assert sysarch["retry_count"] == 2
        assert sorted(sysarch["payload_keys"]) == ["feedback", "project_id"]
        # Comparch: queued, no error_tail
        comparch = jobs_by_type["v2.generate_comparch"]
        assert comparch["status"] == "queued"
        assert "error_tail" not in comparch

    def test_other_project_jobs_excluded(self, client, project, db):
        # Seed a job for a different project — should be excluded
        db.add(
            Job(
                id="job_other",
                job_type="v2.generate_sysarch",
                payload={"project_id": "some_other_project", "feedback": None},
                status="failed",
                error_message="should not appear",
            )
        )
        db.commit()

        resp = client.get(f"/api/projects/{project.id}/debug/skeleton")
        body = resp.json()
        assert body["recent_jobs"] == []

    def test_response_never_contains_prose(self, client, project, db):
        """Structural check: no 'content' key anywhere in the payload."""
        # Seed enough state to populate every section
        feat_id = mint(db, Kind.FEAT)
        append_event(
            db,
            project.id,
            ev.NodeCreated(
                node_id=feat_id,
                tier="feat",
                kind="domain",
                parent_id=None,
                name="F",
                display_order=0,
                content="secret feature description",
            ),
        )
        cid = mint(db, Kind.COMP)
        append_event(
            db,
            project.id,
            ev.NodeCreated(
                node_id=cid,
                tier="comp",
                kind="domain",
                parent_id=None,
                name="C",
                display_order=0,
                content="secret component arch doc",
            ),
        )
        append_event(
            db,
            project.id,
            ev.FragmentUpdated(
                fragment_id=fragment_id(cid, FragmentKind.TECHSPEC),
                owner_id=cid,
                fragment_kind=FragmentKind.TECHSPEC,
                new_content="secret fragment content",
            ),
        )
        db.commit()

        resp = client.get(f"/api/projects/{project.id}/debug/skeleton")
        body = resp.json()

        def _scan(obj):
            if isinstance(obj, dict):
                for k, v in obj.items():
                    assert k != "content", f"content key leaked in {obj}"
                    _scan(v)
            elif isinstance(obj, list):
                for item in obj:
                    _scan(item)

        _scan(body)
        # Prose strings never appear as dict values
        import json

        serialized = json.dumps(body)
        assert "secret" not in serialized
