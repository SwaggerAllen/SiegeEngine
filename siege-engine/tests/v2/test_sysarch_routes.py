"""End-to-end tests for the sysarch HTTP routes.

Same TestClient + in-memory-DB pattern as test_requirements_routes.py.
CLI is mocked so the generation handler produces deterministic
content fed through the real parse-validate loop.
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

import asyncio  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from backend.auth.routes import get_current_user  # noqa: E402
from backend.database import Base, get_db  # noqa: E402
from backend.graph import events as ev  # noqa: E402
from backend.graph.handlers import feature_expansion as fe_handler  # noqa: E402
from backend.graph.handlers.sysarch_generation import (  # noqa: E402
    generate_sysarch,
)
from backend.graph.ids import Kind, mint  # noqa: E402
from backend.graph.reducer import append_event  # noqa: E402
from backend.graph.sysarch import bootstrap_sysarch_node  # noqa: E402
from backend.main import app  # noqa: E402
from backend.models import InputDocument, Project  # noqa: E402
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
    import backend.graph.handlers.sysarch_generation as _sys_gen
    import backend.graph.handlers.sysarch_mint as _sys_mint

    monkeypatch.setattr(_database_mod, "SessionLocal", factory)
    monkeypatch.setattr(fe_handler, "SessionLocal", factory)
    monkeypatch.setattr(_sys_gen, "SessionLocal", factory)
    monkeypatch.setattr(_sys_mint, "SessionLocal", factory)
    yield engine, factory
    engine.dispose()


@pytest.fixture(autouse=True)
def _fast_cli_retry_backoff(monkeypatch):
    monkeypatch.setattr(
        fe_handler,
        "CLI_RETRY_BACKOFF_SECONDS",
        (0.0,) * (fe_handler.CLI_MAX_TRANSIENT_RETRIES + 1),
    )


@pytest.fixture()
def db(engine_and_factory):
    _, factory = engine_and_factory
    session: Session = factory()
    try:
        yield session
    finally:
        session.close()


def _mint_top_level_resp(session, project_id, name, order):
    resp_id = mint(session, Kind.RESP)
    append_event(
        session,
        project_id,
        ev.NodeCreated(
            node_id=resp_id,
            tier="resp",
            kind="domain",
            parent_id=None,
            name=name,
            display_order=order,
            content=f"{name} intent.",
        ),
    )
    return resp_id


@pytest.fixture()
def project_with_sysarch(db):
    p = Project(
        id=str(uuid.uuid4()),
        name="Test Project",
        git_repo_path="/tmp/test-repo",
    )
    db.add(p)
    db.add(
        InputDocument(
            project_id=p.id,
            name="Project Document",
            content="A task management app.",
            doc_type="project_doc",
        )
    )
    _mint_top_level_resp(db, p.id, "Authentication", 0)
    _mint_top_level_resp(db, p.id, "Billing", 1)
    _mint_top_level_resp(db, p.id, "Foundation", 2)
    bootstrap_sysarch_node(db, p.id)
    db.commit()
    return p


@pytest.fixture()
def project_no_sysarch(db):
    """Project with resps but no sysarch node — exercises lazy bootstrap."""
    p = Project(
        id=str(uuid.uuid4()),
        name="Legacy",
        git_repo_path="/tmp/legacy",
    )
    db.add(p)
    _mint_top_level_resp(db, p.id, "X", 0)
    db.commit()
    return p


@pytest.fixture()
def client(db, project_with_sysarch):
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


def _resp_ids(db, project_id):
    return [
        rid
        for (rid,) in db.execute(
            select(Node.id)
            .where(
                Node.project_id == project_id,
                Node.tier == "resp",
                Node.parent_id.is_(None),
            )
            .order_by(Node.display_order)
        ).all()
    ]


def _valid_sysarch(resp_ids: list[str]) -> str:
    auth_id, billing_id, foundation_id = resp_ids
    return (
        "<sysarch>"
        "<techspec>Typical Python + React stack.</techspec>"
        "<components>"
        '<component alias="auth">'
        "<name>Authentication</name><kind>domain</kind>"
        "<role>Identify callers.</role>"
        "<api-intent>authenticate().</api-intent>"
        f'<responsibilities><resp id="{auth_id}"/></responsibilities>'
        "</component>"
        '<component alias="billing">'
        "<name>Billing</name><kind>domain</kind>"
        "<role>Handle payments.</role>"
        "<api-intent>get_billing_state().</api-intent>"
        f'<responsibilities><resp id="{billing_id}"/></responsibilities>'
        "</component>"
        '<component alias="foundation">'
        "<name>Foundation</name><kind>domain</kind>"
        "<role>Project root, shared utilities.</role>"
        "<api-intent>load_settings().</api-intent>"
        f'<responsibilities><resp id="{foundation_id}"/></responsibilities>'
        "<foundation/>"
        "</component>"
        "</components>"
        "<policies></policies>"
        "<dependencies>"
        '<dep from="billing" to="foundation"/>'
        '<dep from="auth" to="foundation"/>'
        "</dependencies>"
        "<domain-parent></domain-parent>"
        "</sysarch>"
    )


def _patch_cli(monkeypatch, output, **kw):
    from backend.cli.manager import GenerationResult

    async def fake(**kwargs):
        return GenerationResult(
            text=output,
            prompt_tokens=kw.get("prompt_tokens", 100),
            completion_tokens=kw.get("completion_tokens", 50),
            model=kw.get("model", "claude-sonnet-4-6"),
        )

    monkeypatch.setattr(fe_handler.cli_manager, "generate_with_usage", fake)


class TestGetSysarch:
    def test_returns_node_state(self, client, project_with_sysarch):
        resp = client.get(f"/api/projects/{project_with_sysarch.id}/sysarch")
        assert resp.status_code == 200
        body = resp.json()
        assert body["node"]["name"] == "System Architecture"
        assert body["node"]["content"] == ""
        assert body["pending_draft"] is None
        assert body["generation_status"] == "idle"

    def test_lazy_bootstraps_missing_sysarch(self, client, project_no_sysarch, db):
        resp = client.get(f"/api/projects/{project_no_sysarch.id}/sysarch")
        assert resp.status_code == 200
        node = db.execute(
            select(Node).where(Node.project_id == project_no_sysarch.id, Node.tier == "sysarch")
        ).scalar_one_or_none()
        assert node is not None
        jobs = db.execute(select(Job).where(Job.job_type == "v2.generate_sysarch")).scalars().all()
        assert any(j.payload.get("project_id") == project_no_sysarch.id for j in jobs)

    def test_unknown_project_is_404(self, client):
        resp = client.get("/api/projects/does-not-exist/sysarch")
        assert resp.status_code == 404


class TestFeedback:
    def test_feedback_enqueues_generate_job(self, client, project_with_sysarch, db):
        resp = client.post(
            f"/api/projects/{project_with_sysarch.id}/sysarch/feedback",
            json={"feedback": "Split billing into subscription + invoicing"},
        )
        assert resp.status_code == 200
        job_id = resp.json()["job_id"]
        job = db.get(Job, job_id)
        assert job is not None
        assert job.job_type == "v2.generate_sysarch"
        assert job.payload["project_id"] == project_with_sysarch.id
        assert job.payload["feedback"] == "Split billing into subscription + invoicing"

    def test_read_only_after_approval(self, client, project_with_sysarch, db):
        node = db.execute(
            select(Node).where(Node.project_id == project_with_sysarch.id, Node.tier == "sysarch")
        ).scalar_one()
        node.content = "<sysarch>already approved</sysarch>"
        db.commit()

        resp = client.post(
            f"/api/projects/{project_with_sysarch.id}/sysarch/feedback",
            json={"feedback": "retry"},
        )
        assert resp.status_code == 409
        assert "read-only after approval" in resp.json()["detail"]


class TestApprove:
    def test_approve_commits_content_and_enqueues_mint(
        self, client, project_with_sysarch, db, monkeypatch
    ):
        draft_xml = _valid_sysarch(_resp_ids(db, project_with_sysarch.id))
        _patch_cli(monkeypatch, draft_xml)
        asyncio.run(generate_sysarch({"project_id": project_with_sysarch.id, "feedback": None}))
        draft = db.execute(
            select(Draft).where(Draft.project_id == project_with_sysarch.id)
        ).scalar_one()

        resp = client.post(
            f"/api/projects/{project_with_sysarch.id}/sysarch/approve",
            json={"draft_id": draft.id},
        )
        assert resp.status_code == 200
        assert resp.json()["node"]["content"] == draft_xml

        jobs = db.execute(select(Job).where(Job.job_type == "v2.mint_sysarch")).scalars().all()
        assert any(j.payload.get("project_id") == project_with_sysarch.id for j in jobs)


class TestDiscard:
    def test_discard_enqueues_new_generation(self, client, project_with_sysarch, db, monkeypatch):
        draft_xml = _valid_sysarch(_resp_ids(db, project_with_sysarch.id))
        _patch_cli(monkeypatch, draft_xml)
        asyncio.run(generate_sysarch({"project_id": project_with_sysarch.id, "feedback": None}))
        draft = db.execute(
            select(Draft).where(Draft.project_id == project_with_sysarch.id)
        ).scalar_one()

        resp = client.post(
            f"/api/projects/{project_with_sysarch.id}/sysarch/discard",
            json={"draft_id": draft.id},
        )
        assert resp.status_code == 200

        db.refresh(draft)
        assert draft.status == "discarded"
        fresh = [
            j
            for j in db.execute(select(Job).where(Job.job_type == "v2.generate_sysarch")).scalars()
            if j.payload.get("project_id") == project_with_sysarch.id
        ]
        assert fresh


class TestComponentsList:
    def test_empty_initially(self, client, project_with_sysarch):
        resp = client.get(f"/api/projects/{project_with_sysarch.id}/components")
        assert resp.status_code == 200
        assert resp.json() == {"components": []}

    def test_lists_minted_components(self, client, project_with_sysarch, db):
        # Fake-mint comp_* directly
        for i, (n, kind) in enumerate(
            [("Auth", "domain"), ("Billing", "domain"), ("UI", "presentational")]
        ):
            cid = mint(db, Kind.COMP)
            append_event(
                db,
                project_with_sysarch.id,
                ev.NodeCreated(
                    node_id=cid,
                    tier="comp",
                    kind=kind,
                    parent_id=None,
                    name=n,
                    display_order=i,
                    content="",
                ),
            )
        db.commit()

        resp = client.get(f"/api/projects/{project_with_sysarch.id}/components")
        body = resp.json()
        assert [c["name"] for c in body["components"]] == ["Auth", "Billing", "UI"]
        assert [c["kind"] for c in body["components"]] == [
            "domain",
            "domain",
            "presentational",
        ]
        assert all(c["id"].startswith("comp_") for c in body["components"])


class TestPoliciesList:
    def test_empty_initially(self, client, project_with_sysarch):
        resp = client.get(f"/api/projects/{project_with_sysarch.id}/policies")
        assert resp.status_code == 200
        assert resp.json() == {"policies": []}

    def test_lists_minted_policies(self, client, project_with_sysarch, db):
        pid = mint(db, Kind.POLICY)
        blob = (
            "<policy>"
            "<name>Telemetry</name>"
            "<trigger>any LLM call</trigger>"
            "<required>resp_xxx</required>"
            "<rationale>Audit.</rationale>"
            "</policy>"
        )
        append_event(
            db,
            project_with_sysarch.id,
            ev.NodeCreated(
                node_id=pid,
                tier="policy",
                kind="domain",
                parent_id=None,
                name="Telemetry",
                display_order=0,
                content=blob,
            ),
        )
        db.commit()

        resp = client.get(f"/api/projects/{project_with_sysarch.id}/policies")
        body = resp.json()
        assert len(body["policies"]) == 1
        assert body["policies"][0]["name"] == "Telemetry"
        # Raw blob on the wire so the frontend can parse for display
        assert "<trigger>any LLM call</trigger>" in body["policies"][0]["content"]
