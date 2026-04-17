"""HTTP tests for the Phase 8 impl routes.

Covers both URL shapes (per-subcomponent and per-top-level
un-fanned-out comp) delegating to the shared
``bootstrap_*`` helpers via IMPL_CONFIG.
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


def _seed_top_comp(db, project_id, *, approved=True, name="C") -> str:
    comp_id = mint(db, Kind.COMP)
    append_event(
        db,
        project_id,
        ev.NodeCreated(
            node_id=comp_id,
            tier="comp",
            kind="domain",
            parent_id=None,
            name=name,
            content="<comparch>body</comparch>" if approved else "",
        ),
    )
    db.commit()
    return comp_id


def _seed_sub(db, project_id, parent_id, *, approved=True, name="Sub") -> str:
    sub_id = mint(db, Kind.COMP)
    append_event(
        db,
        project_id,
        ev.NodeCreated(
            node_id=sub_id,
            tier="comp",
            kind="domain",
            parent_id=parent_id,
            name=name,
            content="<subcomparch>body</subcomparch>" if approved else "",
        ),
    )
    db.commit()
    return sub_id


def _seed_impl_shell(db, project_id, owner_id, *, name="C impl") -> str:
    impl_id = mint(db, Kind.IMPL)
    append_event(
        db,
        project_id,
        ev.NodeCreated(
            node_id=impl_id,
            tier="impl",
            kind="domain",
            parent_id=owner_id,
            name=name,
        ),
    )
    db.commit()
    return impl_id


class TestGetTopLevelImpl:
    def test_404_unknown_comp(self, client, project):
        resp = client.get(f"/api/projects/{project.id}/components/comp_UNKNOWN1/impl")
        assert resp.status_code == 404

    def test_200_returns_impl_shell(self, client, db, project):
        comp_id = _seed_top_comp(db, project.id)
        impl_id = _seed_impl_shell(db, project.id, comp_id)
        resp = client.get(f"/api/projects/{project.id}/components/{comp_id}/impl")
        assert resp.status_code == 200
        body = resp.json()
        assert body["node"]["id"] == impl_id
        assert body["node"]["parent_id"] == comp_id
        assert body["node"]["content"] == ""

    def test_404_when_no_impl_shell(self, client, db, project):
        # Comp exists but no impl minted yet (before comparch_mint runs).
        comp_id = _seed_top_comp(db, project.id)
        resp = client.get(f"/api/projects/{project.id}/components/{comp_id}/impl")
        assert resp.status_code == 404


class TestGetSubImpl:
    def test_200_returns_sub_impl_shell(self, client, db, project):
        top_id = _seed_top_comp(db, project.id, name="Top")
        sub_id = _seed_sub(db, project.id, top_id, name="Sub")
        impl_id = _seed_impl_shell(db, project.id, sub_id, name="Sub impl")
        resp = client.get(
            f"/api/projects/{project.id}/components/{top_id}/subcomponents/{sub_id}/impl"
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["node"]["id"] == impl_id
        assert body["node"]["parent_id"] == sub_id

    def test_404_when_sub_parent_mismatch(self, client, db, project):
        top_id = _seed_top_comp(db, project.id, name="Top")
        other_top = _seed_top_comp(db, project.id, name="Other")
        sub_id = _seed_sub(db, project.id, top_id, name="Sub")
        _seed_impl_shell(db, project.id, sub_id)
        # Sub exists but wrong parent in URL.
        resp = client.get(
            f"/api/projects/{project.id}/components/{other_top}/subcomponents/{sub_id}/impl"
        )
        assert resp.status_code == 404


class TestFeedback:
    def test_feedback_enqueues_job(self, client, db, project):
        comp_id = _seed_top_comp(db, project.id)
        _seed_impl_shell(db, project.id, comp_id)
        resp = client.post(
            f"/api/projects/{project.id}/components/{comp_id}/impl/feedback",
            json={"feedback": "tighten up"},
        )
        assert resp.status_code == 200
        assert resp.json()["job_id"]

    def test_feedback_works_post_approval(self, client, db, project):
        """Impl is never frozen — feedback succeeds after approval."""
        comp_id = _seed_top_comp(db, project.id)
        impl_id = _seed_impl_shell(db, project.id, comp_id)
        # Simulate approved state
        append_event(
            db,
            project.id,
            ev.DraftGenerated(
                draft_id="draft_approved",
                target_type="node",
                target_id=impl_id,
                content="<implementation><behavior>B</behavior>"
                "<invariants>I</invariants><sequencing>S</sequencing>"
                "<edge-cases>E</edge-cases></implementation>",
                batch_id="batch_1",
            ),
        )
        append_event(db, project.id, ev.DraftApproved(draft_id="draft_approved"))
        db.commit()
        resp = client.post(
            f"/api/projects/{project.id}/components/{comp_id}/impl/feedback",
            json={"feedback": "more"},
        )
        assert resp.status_code == 200


class TestApproveDiscardCancel:
    def test_approve_commits_content(self, client, db, project):
        comp_id = _seed_top_comp(db, project.id)
        impl_id = _seed_impl_shell(db, project.id, comp_id)
        append_event(
            db,
            project.id,
            ev.DraftGenerated(
                draft_id="draft_x",
                target_type="node",
                target_id=impl_id,
                content="<implementation><behavior>B</behavior>"
                "<invariants>I</invariants><sequencing>S</sequencing>"
                "<edge-cases>E</edge-cases></implementation>",
                batch_id="batch_1",
            ),
        )
        db.commit()
        resp = client.post(
            f"/api/projects/{project.id}/components/{comp_id}/impl/approve",
            json={"draft_id": "draft_x"},
        )
        assert resp.status_code == 200
        detail = client.get(f"/api/projects/{project.id}/components/{comp_id}/impl").json()
        assert "<implementation>" in detail["node"]["content"]

    def test_discard_clears_draft(self, client, db, project):
        comp_id = _seed_top_comp(db, project.id)
        impl_id = _seed_impl_shell(db, project.id, comp_id)
        append_event(
            db,
            project.id,
            ev.DraftGenerated(
                draft_id="draft_y",
                target_type="node",
                target_id=impl_id,
                content="<implementation><behavior>B</behavior>"
                "<invariants>I</invariants><sequencing>S</sequencing>"
                "<edge-cases>E</edge-cases></implementation>",
                batch_id="batch_1",
            ),
        )
        db.commit()
        resp = client.post(
            f"/api/projects/{project.id}/components/{comp_id}/impl/discard",
            json={"draft_id": "draft_y"},
        )
        assert resp.status_code == 200
        detail = client.get(f"/api/projects/{project.id}/components/{comp_id}/impl").json()
        assert detail["pending_draft"] is None

    def test_cancel_returns_bool(self, client, db, project):
        comp_id = _seed_top_comp(db, project.id)
        _seed_impl_shell(db, project.id, comp_id)
        resp = client.post(f"/api/projects/{project.id}/components/{comp_id}/impl/cancel")
        assert resp.status_code == 200
        assert isinstance(resp.json()["cancelled"], bool)


class TestSubScopeLifecycle:
    def test_full_sub_lifecycle(self, client, db, project):
        top_id = _seed_top_comp(db, project.id, name="Top")
        sub_id = _seed_sub(db, project.id, top_id, name="Sub")
        impl_id = _seed_impl_shell(db, project.id, sub_id, name="Sub impl")
        base = f"/api/projects/{project.id}/components/{top_id}/subcomponents/{sub_id}/impl"

        # feedback
        resp = client.post(base + "/feedback", json={"feedback": ""})
        assert resp.status_code == 200

        # draft + approve
        append_event(
            db,
            project.id,
            ev.DraftGenerated(
                draft_id="draft_sub",
                target_type="node",
                target_id=impl_id,
                content="<implementation><behavior>B</behavior>"
                "<invariants>I</invariants><sequencing>S</sequencing>"
                "<edge-cases>E</edge-cases></implementation>",
                batch_id="batch_1",
            ),
        )
        db.commit()
        resp = client.post(base + "/approve", json={"draft_id": "draft_sub"})
        assert resp.status_code == 200
