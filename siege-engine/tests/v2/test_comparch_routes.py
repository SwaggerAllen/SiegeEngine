"""End-to-end tests for the comparch HTTP routes."""

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
def project_with_comp(db):
    p = Project(
        id=str(uuid.uuid4()),
        name="Test",
        git_repo_path="/tmp/test",
    )
    db.add(p)

    # Top-level comp
    cid = mint(db, Kind.COMP)
    append_event(
        db,
        p.id,
        ev.NodeCreated(
            node_id=cid,
            tier="comp",
            kind="domain",
            parent_id=None,
            name="BillingService",
            display_order=0,
            content="",
        ),
    )
    db.commit()
    return {"project": p, "comp_id": cid}


@pytest.fixture()
def client(db, project_with_comp):
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


class TestGetComparch:
    def test_returns_empty_state(self, client, project_with_comp):
        resp = client.get(
            f"/api/projects/{project_with_comp['project'].id}"
            f"/components/{project_with_comp['comp_id']}/comparch"
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["node"]["name"] == "BillingService"
        assert body["node"]["content"] == ""
        assert body["pending_draft"] is None
        assert body["generation_status"] == "idle"

    def test_unknown_component_404(self, client, project_with_comp):
        resp = client.get(
            f"/api/projects/{project_with_comp['project'].id}/components/comp_missing01/comparch"
        )
        assert resp.status_code == 404

    def test_subcomponent_404(self, client, project_with_comp, db):
        # Create a subcomponent under the top-level comp
        sub_id = mint(db, Kind.COMP)
        append_event(
            db,
            project_with_comp["project"].id,
            ev.NodeCreated(
                node_id=sub_id,
                tier="comp",
                kind="domain",
                parent_id=project_with_comp["comp_id"],
                name="SubThing",
                display_order=0,
                content="",
            ),
        )
        db.commit()

        resp = client.get(
            f"/api/projects/{project_with_comp['project'].id}/components/{sub_id}/comparch"
        )
        assert resp.status_code == 404


class TestFeedback:
    def test_feedback_enqueues_generation(self, client, project_with_comp, db):
        resp = client.post(
            f"/api/projects/{project_with_comp['project'].id}"
            f"/components/{project_with_comp['comp_id']}/comparch/feedback",
            json={"feedback": "Add async token refresh"},
        )
        assert resp.status_code == 200
        jobs = db.execute(select(Job).where(Job.job_type == "v2.generate_comparch")).scalars().all()
        assert any(
            j.payload.get("component_id") == project_with_comp["comp_id"]
            and j.payload.get("feedback") == "Add async token refresh"
            for j in jobs
        )

    def test_read_only_after_approval(self, client, project_with_comp, db):
        # Write approved content to the comp node
        node = db.get(Node, project_with_comp["comp_id"])
        node.content = "<comparch>approved</comparch>"
        db.commit()

        resp = client.post(
            f"/api/projects/{project_with_comp['project'].id}"
            f"/components/{project_with_comp['comp_id']}/comparch/feedback",
            json={"feedback": "retry"},
        )
        assert resp.status_code == 409
        assert "read-only after approval" in resp.json()["detail"]


class TestApproveDiscard:
    def test_approve_enqueues_mint(self, client, project_with_comp, db):
        draft = Draft(
            id="draft_test0001",
            project_id=project_with_comp["project"].id,
            target_type="node",
            target_id=project_with_comp["comp_id"],
            content="<comparch>pending</comparch>",
            status="pending",
            batch_id="batch_test000001",
        )
        db.add(draft)
        db.commit()

        resp = client.post(
            f"/api/projects/{project_with_comp['project'].id}"
            f"/components/{project_with_comp['comp_id']}/comparch/approve",
            json={"draft_id": "draft_test0001"},
        )
        assert resp.status_code == 200

        jobs = db.execute(select(Job).where(Job.job_type == "v2.mint_comparch")).scalars().all()
        assert any(j.payload.get("component_id") == project_with_comp["comp_id"] for j in jobs)

    def test_discard_enqueues_fresh_generation(self, client, project_with_comp, db):
        draft = Draft(
            id="draft_test0002",
            project_id=project_with_comp["project"].id,
            target_type="node",
            target_id=project_with_comp["comp_id"],
            content="<comparch>pending</comparch>",
            status="pending",
            batch_id="batch_test000002",
        )
        db.add(draft)
        db.commit()

        resp = client.post(
            f"/api/projects/{project_with_comp['project'].id}"
            f"/components/{project_with_comp['comp_id']}/comparch/discard",
            json={"draft_id": "draft_test0002"},
        )
        assert resp.status_code == 200

        db.refresh(draft)
        assert draft.status == "discarded"


class TestLists:
    def test_subcomponents_empty_initially(self, client, project_with_comp):
        resp = client.get(
            f"/api/projects/{project_with_comp['project'].id}"
            f"/components/{project_with_comp['comp_id']}/subcomponents"
        )
        assert resp.status_code == 200
        assert resp.json() == {"subcomponents": []}

    def test_subcomponents_populated(self, client, project_with_comp, db):
        for i, name in enumerate(["Store", "Foundation"]):
            sub_id = mint(db, Kind.COMP)
            append_event(
                db,
                project_with_comp["project"].id,
                ev.NodeCreated(
                    node_id=sub_id,
                    tier="comp",
                    kind="domain",
                    parent_id=project_with_comp["comp_id"],
                    name=name,
                    display_order=i,
                    content="",
                ),
            )
        db.commit()
        resp = client.get(
            f"/api/projects/{project_with_comp['project'].id}"
            f"/components/{project_with_comp['comp_id']}/subcomponents"
        )
        body = resp.json()
        assert [s["name"] for s in body["subcomponents"]] == ["Store", "Foundation"]

    def test_local_policies_empty_initially(self, client, project_with_comp):
        resp = client.get(
            f"/api/projects/{project_with_comp['project'].id}"
            f"/components/{project_with_comp['comp_id']}/local-policies"
        )
        assert resp.status_code == 200
        assert resp.json() == {"policies": []}

    def test_local_policies_populated(self, client, project_with_comp, db):
        pid = mint(db, Kind.POLICY)
        append_event(
            db,
            project_with_comp["project"].id,
            ev.NodeCreated(
                node_id=pid,
                tier="policy",
                kind="domain",
                parent_id=project_with_comp["comp_id"],
                name="AuditTrail",
                display_order=0,
                content=(
                    "<policy><name>AuditTrail</name>"
                    "<trigger>any domain write</trigger>"
                    "<required>resp_x</required>"
                    "<rationale>Audit.</rationale></policy>"
                ),
            ),
        )
        db.commit()
        resp = client.get(
            f"/api/projects/{project_with_comp['project'].id}"
            f"/components/{project_with_comp['comp_id']}/local-policies"
        )
        body = resp.json()
        assert len(body["policies"]) == 1
        assert body["policies"][0]["name"] == "AuditTrail"
        assert "<trigger>any domain write</trigger>" in body["policies"][0]["content"]

    def test_applied_policies_empty_initially(self, client, project_with_comp):
        resp = client.get(
            f"/api/projects/{project_with_comp['project'].id}"
            f"/components/{project_with_comp['comp_id']}/applied-policies"
        )
        assert resp.status_code == 200
        assert resp.json() == {"applied_policies": []}

    def test_applied_policies_populated(self, client, project_with_comp, db):
        # Seed a top-level policy + an application edge to this comp
        pid = mint(db, Kind.POLICY)
        append_event(
            db,
            project_with_comp["project"].id,
            ev.NodeCreated(
                node_id=pid,
                tier="policy",
                kind="domain",
                parent_id=None,
                name="Telemetry",
                display_order=0,
                content="<policy><name>Telemetry</name></policy>",
            ),
        )
        edge_id = mint(db, Kind.EDGE)
        append_event(
            db,
            project_with_comp["project"].id,
            ev.EdgeCreated(
                edge_id=edge_id,
                edge_type="policy_application",
                source_id=pid,
                target_id=project_with_comp["comp_id"],
            ),
        )
        db.commit()
        resp = client.get(
            f"/api/projects/{project_with_comp['project'].id}"
            f"/components/{project_with_comp['comp_id']}/applied-policies"
        )
        body = resp.json()
        assert len(body["applied_policies"]) == 1
        assert body["applied_policies"][0]["policy_name"] == "Telemetry"
