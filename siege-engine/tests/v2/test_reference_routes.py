"""HTTP tests for the Phase 6.6 reference routes.

Covers:

- GET list
- GET detail (including pending draft + outgoing/incoming edges)
- POST create (mints ref + edges + enqueues generation)
- POST feedback (enqueues regen — works post-approval too)
- POST approve / discard / delete
- POST /edges/reference (add) + DELETE /edges/reference (remove)
- Error cases (404, 409, 422)
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
            content="Users pay for plans.",
        ),
    )
    db.commit()
    return feat_id


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


def _create_ref(client, project_id: str, name: str = "Runbook") -> str:
    resp = client.post(
        f"/api/projects/{project_id}/references/create",
        json={
            "name": name,
            "seed_description": "Deployment runbook",
            "related_nodes": [],
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["ref_id"]


class TestList:
    def test_empty_list(self, client, project):
        resp = client.get(f"/api/projects/{project.id}/references")
        assert resp.status_code == 200
        assert resp.json() == {"references": []}

    def test_list_after_create(self, client, project):
        _create_ref(client, project.id, "R1")
        _create_ref(client, project.id, "R2")
        resp = client.get(f"/api/projects/{project.id}/references")
        names = [r["name"] for r in resp.json()["references"]]
        assert names == ["R1", "R2"]


class TestCreate:
    def test_create_mints_ref(self, client, project):
        resp = client.post(
            f"/api/projects/{project.id}/references/create",
            json={
                "name": "Runbook",
                "seed_description": "Deployment steps",
                "related_nodes": [],
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ref_id"].startswith("ref_")
        assert body["job_id"]

    def test_create_wires_edges_to_related_nodes(self, client, db, project, feat_billing):
        resp = client.post(
            f"/api/projects/{project.id}/references/create",
            json={
                "name": "BillingRef",
                "seed_description": "Billing reference",
                "related_nodes": [feat_billing],
            },
        )
        ref_id = resp.json()["ref_id"]
        detail = client.get(f"/api/projects/{project.id}/references/{ref_id}").json()
        assert len(detail["outgoing_edges"]) == 1
        assert detail["outgoing_edges"][0]["target_id"] == feat_billing

    def test_create_rejects_empty_name(self, client, project):
        resp = client.post(
            f"/api/projects/{project.id}/references/create",
            json={
                "name": "   ",
                "seed_description": "x",
                "related_nodes": [],
            },
        )
        assert resp.status_code == 422

    def test_create_rejects_empty_seed(self, client, project):
        resp = client.post(
            f"/api/projects/{project.id}/references/create",
            json={
                "name": "R",
                "seed_description": "   ",
                "related_nodes": [],
            },
        )
        assert resp.status_code == 422

    def test_create_rejects_duplicate_name(self, client, project):
        _create_ref(client, project.id, "Runbook")
        resp = client.post(
            f"/api/projects/{project.id}/references/create",
            json={
                "name": "Runbook",
                "seed_description": "x",
                "related_nodes": [],
            },
        )
        assert resp.status_code == 409

    def test_create_rejects_missing_related_node(self, client, project):
        resp = client.post(
            f"/api/projects/{project.id}/references/create",
            json={
                "name": "R",
                "seed_description": "x",
                "related_nodes": ["feat_MISSING0"],
            },
        )
        assert resp.status_code == 404


class TestDetail:
    def test_404_unknown_ref(self, client, project):
        resp = client.get(f"/api/projects/{project.id}/references/ref_DEADBEEF")
        assert resp.status_code == 404

    def test_returns_seed_content_before_first_regen(self, client, project):
        ref_id = _create_ref(client, project.id)
        resp = client.get(f"/api/projects/{project.id}/references/{ref_id}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["node"]["id"] == ref_id
        # The create route now writes a minimal <reference> shell
        # carrying the seed_description as the body, so subsequent
        # regens have something to anchor against.
        assert "<reference>" in body["node"]["content"]
        assert "Deployment runbook" in body["node"]["content"]


class TestFeedback:
    def test_feedback_enqueues_job(self, client, project):
        ref_id = _create_ref(client, project.id)
        resp = client.post(
            f"/api/projects/{project.id}/references/{ref_id}/feedback",
            json={"feedback": "tighten up"},
        )
        assert resp.status_code == 200
        assert resp.json()["job_id"]

    def test_feedback_works_post_approval(self, client, db, project):
        """Key Phase 6.6 property — refs are not frozen after approval."""
        ref_id = _create_ref(client, project.id)
        # Simulate an approved state by manually minting a DraftGenerated + DraftApproved
        append_event(
            db,
            project.id,
            ev.DraftGenerated(
                draft_id="draft_approved",
                target_type="node",
                target_id=ref_id,
                content="<reference><title>X</title><body>y</body></reference>",
                batch_id="batch_01",
            ),
        )
        append_event(db, project.id, ev.DraftApproved(draft_id="draft_approved"))
        db.commit()
        # Feedback should still 200, unlike bootstrap tiers which 409.
        resp = client.post(
            f"/api/projects/{project.id}/references/{ref_id}/feedback",
            json={"feedback": "more"},
        )
        assert resp.status_code == 200


class TestApproveDiscard:
    def _seed_pending_draft(self, db, project, ref_id, draft_id="draft_test"):
        append_event(
            db,
            project.id,
            ev.DraftGenerated(
                draft_id=draft_id,
                target_type="node",
                target_id=ref_id,
                content="<reference><title>t</title><body>b</body></reference>",
                batch_id="batch_test",
            ),
        )
        db.commit()

    def test_approve_commits_content(self, client, db, project):
        ref_id = _create_ref(client, project.id)
        self._seed_pending_draft(db, project, ref_id)
        resp = client.post(
            f"/api/projects/{project.id}/references/{ref_id}/approve",
            json={"draft_id": "draft_test"},
        )
        assert resp.status_code == 200
        detail = client.get(f"/api/projects/{project.id}/references/{ref_id}").json()
        # After approval the draft's <body>b</body> content overrides
        # the seed shell — content stays a reference XML block.
        assert "<reference>" in detail["node"]["content"]
        assert "<body>b</body>" in detail["node"]["content"]

    def test_discard_clears_draft(self, client, db, project):
        ref_id = _create_ref(client, project.id)
        self._seed_pending_draft(db, project, ref_id)
        resp = client.post(
            f"/api/projects/{project.id}/references/{ref_id}/discard",
            json={"draft_id": "draft_test"},
        )
        assert resp.status_code == 200
        detail = client.get(f"/api/projects/{project.id}/references/{ref_id}").json()
        # The discard auto-enqueues a fresh generation (matching the
        # bootstrap-tier UX); the worker is gated off so the new
        # job sits in the queue without producing a draft yet.
        assert detail["pending_draft"] is None


class TestDelete:
    def test_delete_removes_node(self, client, project):
        ref_id = _create_ref(client, project.id)
        resp = client.post(f"/api/projects/{project.id}/references/{ref_id}/delete")
        assert resp.status_code == 200
        detail = client.get(f"/api/projects/{project.id}/references/{ref_id}")
        assert detail.status_code == 404


class TestReferenceEdgeRoutes:
    def test_add_reference_edge(self, client, project, feat_billing):
        ref_id = _create_ref(client, project.id)
        resp = client.post(
            f"/api/projects/{project.id}/edges/reference",
            json={"source_id": ref_id, "target_id": feat_billing},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["source_id"] == ref_id
        assert body["target_id"] == feat_billing

    def test_add_reference_edge_rejects_self(self, client, project):
        ref_id = _create_ref(client, project.id)
        resp = client.post(
            f"/api/projects/{project.id}/edges/reference",
            json={"source_id": ref_id, "target_id": ref_id},
        )
        assert resp.status_code == 422

    def test_add_reference_edge_rejects_missing_endpoint(self, client, project):
        ref_id = _create_ref(client, project.id)
        resp = client.post(
            f"/api/projects/{project.id}/edges/reference",
            json={"source_id": ref_id, "target_id": "feat_MISSING0"},
        )
        assert resp.status_code == 404

    def test_add_reference_edge_rejects_duplicate(self, client, project, feat_billing):
        ref_id = _create_ref(client, project.id)
        client.post(
            f"/api/projects/{project.id}/edges/reference",
            json={"source_id": ref_id, "target_id": feat_billing},
        )
        dup = client.post(
            f"/api/projects/{project.id}/edges/reference",
            json={"source_id": ref_id, "target_id": feat_billing},
        )
        assert dup.status_code == 409

    def test_remove_reference_edge(self, client, project, feat_billing):
        ref_id = _create_ref(client, project.id)
        client.post(
            f"/api/projects/{project.id}/edges/reference",
            json={"source_id": ref_id, "target_id": feat_billing},
        )
        resp = client.request(
            "DELETE",
            f"/api/projects/{project.id}/edges/reference",
            json={"source_id": ref_id, "target_id": feat_billing},
        )
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}

    def test_remove_reference_edge_404_when_missing(self, client, project, feat_billing):
        ref_id = _create_ref(client, project.id)
        resp = client.request(
            "DELETE",
            f"/api/projects/{project.id}/edges/reference",
            json={"source_id": ref_id, "target_id": feat_billing},
        )
        assert resp.status_code == 404
