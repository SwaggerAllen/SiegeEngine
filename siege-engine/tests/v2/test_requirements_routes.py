"""End-to-end tests for the requirements HTTP routes.

Mirrors test_expansion_routes.py scaffold. The CLI is mocked so
the generation handler produces deterministic content fed through
the real parse-validate loop.
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
from backend.graph.handlers.requirements_generation import (  # noqa: E402
    generate_requirements,
)
from backend.graph.ids import Kind, mint  # noqa: E402
from backend.graph.reducer import append_event  # noqa: E402
from backend.graph.requirements import bootstrap_reqs_node  # noqa: E402
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
    import backend.graph.handlers.feature_mint as _feature_mint_handler
    import backend.graph.handlers.requirements_generation as _reqs_gen
    import backend.graph.handlers.requirements_mint as _reqs_mint

    monkeypatch.setattr(_database_mod, "SessionLocal", factory)
    monkeypatch.setattr(fe_handler, "SessionLocal", factory)
    monkeypatch.setattr(_feature_mint_handler, "SessionLocal", factory)
    monkeypatch.setattr(_reqs_gen, "SessionLocal", factory)
    monkeypatch.setattr(_reqs_mint, "SessionLocal", factory)
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


def _mint_feature(session, project_id, name, intent, order):
    feat_id = mint(session, Kind.FEAT)
    append_event(
        session,
        project_id,
        ev.NodeCreated(
            node_id=feat_id,
            tier="feat",
            kind="domain",
            parent_id=None,
            name=name,
            display_order=order,
            content=intent,
        ),
    )


@pytest.fixture()
def project_with_reqs(db):
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
    _mint_feature(db, p.id, "Billing", "Users pay.", 0)
    _mint_feature(db, p.id, "Auth", "Users sign in.", 1)
    bootstrap_reqs_node(db, p.id)
    db.commit()
    return p


@pytest.fixture()
def project_no_reqs(db):
    """Project with features but no reqs node — exercises the
    lazy-bootstrap branch of GET /requirements."""
    p = Project(
        id=str(uuid.uuid4()),
        name="Legacy",
        git_repo_path="/tmp/legacy",
    )
    db.add(p)
    _mint_feature(db, p.id, "X", "X intent.", 0)
    db.commit()
    return p


@pytest.fixture()
def client(db, project_with_reqs):
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


def _feat_ids_for(db, project_id) -> list[str]:
    return [
        fid
        for (fid,) in db.execute(
            select(Node.id)
            .where(Node.project_id == project_id, Node.tier == "feat")
            .order_by(Node.display_order)
        ).all()
    ]


def _valid_reqs_xml(feat_ids: list[str], label: str = "Default") -> str:
    covers = "<covers>" + "".join(f'<feat id="{fid}"/>' for fid in feat_ids) + "</covers>"
    return (
        "<requirements>"
        "<responsibility>"
        f"<name>{label}</name>"
        f"<intent>Paragraph for {label} responsibility in route tests.</intent>"
        f"{covers}"
        "</responsibility>"
        "</requirements>"
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


class TestGetRequirements:
    def test_returns_node_state(self, client, project_with_reqs):
        resp = client.get(f"/api/projects/{project_with_reqs.id}/requirements")
        assert resp.status_code == 200
        body = resp.json()
        assert body["node"]["name"] == "Requirements"
        assert body["node"]["content"] == ""
        assert body["pending_draft"] is None
        assert body["generation_status"] == "idle"
        assert body["latest_telemetry"] is None

    def test_lazy_bootstraps_missing_reqs_node(self, client, project_no_reqs, db):
        resp = client.get(f"/api/projects/{project_no_reqs.id}/requirements")
        assert resp.status_code == 200
        # Node was minted by the GET handler
        node = db.execute(
            select(Node).where(Node.project_id == project_no_reqs.id, Node.tier == "reqs")
        ).scalar_one_or_none()
        assert node is not None
        # Generation job enqueued
        jobs = (
            db.execute(select(Job).where(Job.job_type == "v2.generate_requirements"))
            .scalars()
            .all()
        )
        assert any(j.payload.get("project_id") == project_no_reqs.id for j in jobs)

    def test_unknown_project_is_404(self, client):
        resp = client.get("/api/projects/does-not-exist/requirements")
        assert resp.status_code == 404


class TestFeedback:
    def test_feedback_enqueues_generate_job(self, client, project_with_reqs, db):
        resp = client.post(
            f"/api/projects/{project_with_reqs.id}/requirements/feedback",
            json={"feedback": "Add rate limiting"},
        )
        assert resp.status_code == 200
        job_id = resp.json()["job_id"]
        job = db.get(Job, job_id)
        assert job is not None
        assert job.job_type == "v2.generate_requirements"
        assert job.payload["project_id"] == project_with_reqs.id
        assert job.payload["feedback"] == "Add rate limiting"

    def test_read_only_after_approval(self, client, project_with_reqs, db):
        # Fake approved state: set node.content directly.
        node = db.execute(
            select(Node).where(Node.project_id == project_with_reqs.id, Node.tier == "reqs")
        ).scalar_one()
        node.content = "<requirements>already approved</requirements>"
        db.commit()

        resp = client.post(
            f"/api/projects/{project_with_reqs.id}/requirements/feedback",
            json={"feedback": "retry"},
        )
        assert resp.status_code == 409
        assert "read-only after approval" in resp.json()["detail"]


class TestApprove:
    def test_approve_commits_content_and_enqueues_mint(
        self, client, project_with_reqs, db, monkeypatch
    ):
        # Drive the generation handler to produce a real pending draft
        draft_xml = _valid_reqs_xml(_feat_ids_for(db, project_with_reqs.id))
        _patch_cli(monkeypatch, draft_xml)
        asyncio.run(generate_requirements({"project_id": project_with_reqs.id, "feedback": None}))
        draft = db.execute(
            select(Draft).where(Draft.project_id == project_with_reqs.id)
        ).scalar_one()

        resp = client.post(
            f"/api/projects/{project_with_reqs.id}/requirements/approve",
            json={"draft_id": draft.id},
        )
        assert resp.status_code == 200
        assert resp.json()["node"]["content"] == draft_xml

        # Mint job enqueued
        jobs = db.execute(select(Job).where(Job.job_type == "v2.mint_requirements")).scalars().all()
        assert any(j.payload.get("project_id") == project_with_reqs.id for j in jobs)


class TestDiscard:
    def test_discard_enqueues_new_generation(self, client, project_with_reqs, db, monkeypatch):
        draft_xml = _valid_reqs_xml(_feat_ids_for(db, project_with_reqs.id))
        _patch_cli(monkeypatch, draft_xml)
        asyncio.run(generate_requirements({"project_id": project_with_reqs.id, "feedback": None}))
        draft = db.execute(
            select(Draft).where(Draft.project_id == project_with_reqs.id)
        ).scalar_one()

        resp = client.post(
            f"/api/projects/{project_with_reqs.id}/requirements/discard",
            json={"draft_id": draft.id},
        )
        assert resp.status_code == 200

        # Draft moved to discarded, new generate job enqueued
        db.refresh(draft)
        assert draft.status == "discarded"
        fresh_gens = [
            j
            for j in db.execute(
                select(Job).where(Job.job_type == "v2.generate_requirements")
            ).scalars()
            if j.payload.get("project_id") == project_with_reqs.id
        ]
        assert fresh_gens  # At least one enqueued
