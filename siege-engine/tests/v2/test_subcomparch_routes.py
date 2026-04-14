"""End-to-end tests for the subcomparch HTTP routes (Phase 5)."""

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
from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from backend.auth.routes import get_current_user  # noqa: E402
from backend.database import Base, get_db  # noqa: E402
from backend.graph import events as ev  # noqa: E402
from backend.graph.ids import Kind, mint  # noqa: E402
from backend.graph.reducer import append_event  # noqa: E402
from backend.main import app  # noqa: E402
from backend.models import Project  # noqa: E402
from backend.models.job import Job  # noqa: E402
from backend.models.node import Draft, Node  # noqa: E402


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
def project_with_sub(db):
    p = Project(
        id=str(uuid.uuid4()),
        name="Test",
        git_repo_path="/tmp/test",
    )
    db.add(p)
    db.flush()

    parent_id = mint(db, Kind.COMP)
    append_event(
        db,
        p.id,
        ev.NodeCreated(
            node_id=parent_id,
            tier="comp",
            kind="domain",
            parent_id=None,
            name="BillingService",
            display_order=0,
            content="",
        ),
    )
    sub_id = mint(db, Kind.COMP)
    append_event(
        db,
        p.id,
        ev.NodeCreated(
            node_id=sub_id,
            tier="comp",
            kind="domain",
            parent_id=parent_id,
            name="TokenStore",
            display_order=0,
            content="",
        ),
    )
    other_parent = mint(db, Kind.COMP)
    append_event(
        db,
        p.id,
        ev.NodeCreated(
            node_id=other_parent,
            tier="comp",
            kind="domain",
            parent_id=None,
            name="AuthService",
            display_order=1,
            content="",
        ),
    )
    db.commit()
    return {
        "project": p,
        "parent_id": parent_id,
        "sub_id": sub_id,
        "other_parent": other_parent,
    }


@pytest.fixture()
def client(db, project_with_sub):
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


def _url(project_id: str, parent_id: str, sub_id: str, suffix: str = "") -> str:
    return (
        f"/api/projects/{project_id}/components/{parent_id}"
        f"/subcomponents/{sub_id}/subcomparch{suffix}"
    )


class TestGetSubcomparch:
    def test_returns_empty_state(self, client, project_with_sub):
        resp = client.get(
            _url(
                project_with_sub["project"].id,
                project_with_sub["parent_id"],
                project_with_sub["sub_id"],
            )
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["node"]["name"] == "TokenStore"
        assert body["node"]["parent_id"] == project_with_sub["parent_id"]
        assert body["node"]["content"] == ""
        assert body["pending_draft"] is None
        assert body["generation_status"] == "idle"

    def test_unknown_parent_404(self, client, project_with_sub):
        resp = client.get(
            _url(
                project_with_sub["project"].id,
                "comp_unknown01",
                project_with_sub["sub_id"],
            )
        )
        assert resp.status_code == 404

    def test_unknown_sub_404(self, client, project_with_sub):
        resp = client.get(
            _url(
                project_with_sub["project"].id,
                project_with_sub["parent_id"],
                "comp_unknown02",
            )
        )
        assert resp.status_code == 404

    def test_sub_under_wrong_parent_404(self, client, project_with_sub):
        """Sub belongs to parent_id=billing but URL uses parent_id=auth."""
        resp = client.get(
            _url(
                project_with_sub["project"].id,
                project_with_sub["other_parent"],
                project_with_sub["sub_id"],
            )
        )
        assert resp.status_code == 404
        assert "parent does not match" in resp.json()["detail"]

    def test_top_level_comp_as_sub_404(self, client, project_with_sub):
        """Trying to treat a top-level comp as a subcomponent."""
        resp = client.get(
            _url(
                project_with_sub["project"].id,
                project_with_sub["parent_id"],
                project_with_sub["parent_id"],  # sub_id = parent_id (top-level)
            )
        )
        assert resp.status_code == 404


class TestFeedback:
    def test_feedback_enqueues_generation(self, client, project_with_sub, db):
        resp = client.post(
            _url(
                project_with_sub["project"].id,
                project_with_sub["parent_id"],
                project_with_sub["sub_id"],
                "/feedback",
            ),
            json={"feedback": "Narrow the surface"},
        )
        assert resp.status_code == 200
        jobs = (
            db.execute(select(Job).where(Job.job_type == "v2.generate_subcomparch")).scalars().all()
        )
        assert any(
            j.payload.get("component_id") == project_with_sub["sub_id"]
            and j.payload.get("feedback") == "Narrow the surface"
            for j in jobs
        )

    def test_read_only_after_approval(self, client, project_with_sub, db):
        node = db.get(Node, project_with_sub["sub_id"])
        node.content = "<subcomparch>approved</subcomparch>"
        db.commit()

        resp = client.post(
            _url(
                project_with_sub["project"].id,
                project_with_sub["parent_id"],
                project_with_sub["sub_id"],
                "/feedback",
            ),
            json={"feedback": "retry"},
        )
        assert resp.status_code == 409
        assert "read-only after approval" in resp.json()["detail"]


class TestApproveDiscard:
    def test_approve_enqueues_mint(self, client, project_with_sub, db):
        draft = Draft(
            id="draft_sub00001",
            project_id=project_with_sub["project"].id,
            target_type="node",
            target_id=project_with_sub["sub_id"],
            content="<subcomparch>pending</subcomparch>",
            status="pending",
            batch_id="batch_sub00000001",
        )
        db.add(draft)
        db.commit()

        resp = client.post(
            _url(
                project_with_sub["project"].id,
                project_with_sub["parent_id"],
                project_with_sub["sub_id"],
                "/approve",
            ),
            json={"draft_id": "draft_sub00001"},
        )
        assert resp.status_code == 200

        jobs = db.execute(select(Job).where(Job.job_type == "v2.mint_subcomparch")).scalars().all()
        assert any(j.payload.get("component_id") == project_with_sub["sub_id"] for j in jobs)

    def test_discard_enqueues_fresh_generation(self, client, project_with_sub, db):
        draft = Draft(
            id="draft_sub00002",
            project_id=project_with_sub["project"].id,
            target_type="node",
            target_id=project_with_sub["sub_id"],
            content="<subcomparch>pending</subcomparch>",
            status="pending",
            batch_id="batch_sub00000002",
        )
        db.add(draft)
        db.commit()

        resp = client.post(
            _url(
                project_with_sub["project"].id,
                project_with_sub["parent_id"],
                project_with_sub["sub_id"],
                "/discard",
            ),
            json={"draft_id": "draft_sub00002"},
        )
        assert resp.status_code == 200

        db.refresh(draft)
        assert draft.status == "discarded"

        jobs = (
            db.execute(select(Job).where(Job.job_type == "v2.generate_subcomparch")).scalars().all()
        )
        assert any(j.payload.get("component_id") == project_with_sub["sub_id"] for j in jobs)

    def test_approve_wrong_draft_404(self, client, project_with_sub, db):
        # Draft targets a different sub
        other_sub = mint(db, Kind.COMP)
        append_event(
            db,
            project_with_sub["project"].id,
            ev.NodeCreated(
                node_id=other_sub,
                tier="comp",
                kind="domain",
                parent_id=project_with_sub["parent_id"],
                name="Other",
                display_order=1,
                content="",
            ),
        )
        draft = Draft(
            id="draft_other_001",
            project_id=project_with_sub["project"].id,
            target_type="node",
            target_id=other_sub,
            content="<subcomparch>x</subcomparch>",
            status="pending",
            batch_id="batch_xxxxxxxxxxx1",
        )
        db.add(draft)
        db.commit()

        resp = client.post(
            _url(
                project_with_sub["project"].id,
                project_with_sub["parent_id"],
                project_with_sub["sub_id"],
                "/approve",
            ),
            json={"draft_id": "draft_other_001"},
        )
        assert resp.status_code == 404
