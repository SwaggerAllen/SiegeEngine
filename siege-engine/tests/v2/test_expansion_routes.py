"""End-to-end tests for the feature-expansion HTTP routes.

Mirrors ``test_debug_route.py`` in its handling of the cryptography/
cffi environmental skip. Uses a ``StaticPool``-backed in-memory DB
so the TestClient's threadpool-dispatched sync handlers can share
state with the fixture thread.

The background pipeline worker is never started in these tests: the
generation handler is driven synchronously via ``asyncio.run`` where
needed, and the worker loop is disabled by
``SIEGE_DISABLE_WORKER_LOOP=1`` in the autouse fixture.
"""

from __future__ import annotations

import os
import uuid

import pytest

os.environ.setdefault("SIEGE_DISABLE_WORKER_LOOP", "1")

# Skip the whole module if the cryptography stack can't load — the
# jose → cryptography → cffi chain panics (not raises) on this box,
# so we have to catch BaseException here.
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
from backend.graph.expansion import bootstrap_expansion_node  # noqa: E402
from backend.graph.handlers import feature_expansion as fe_handler  # noqa: E402
from backend.main import app  # noqa: E402
from backend.models import InputDocument, Project  # noqa: E402
from backend.models.job import Job  # noqa: E402
from backend.models.node import Draft  # noqa: E402


@pytest.fixture()
def engine_and_factory(monkeypatch):
    """Shared in-memory engine for route + handler.

    Redirects ``backend.database.SessionLocal`` to the same engine so
    the handlers (which open their own sessions) see the same data.
    """
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    import backend.database as _database_mod
    import backend.graph.handlers.feature_mint as _feature_mint_handler

    monkeypatch.setattr(_database_mod, "SessionLocal", factory)
    monkeypatch.setattr(fe_handler, "SessionLocal", factory)
    monkeypatch.setattr(_feature_mint_handler, "SessionLocal", factory)
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
    bootstrap_expansion_node(db, p.id)
    db.commit()
    return p


@pytest.fixture()
def legacy_project(db):
    """A project created without an expansion node — simulates a
    project that existed before the ``expansion`` tier shipped, or
    any future state where bootstrap didn't run.
    """
    p = Project(
        id=str(uuid.uuid4()),
        name="Legacy Project",
        git_repo_path="/tmp/legacy-repo",
    )
    db.add(p)
    db.add(
        InputDocument(
            project_id=p.id,
            name="Project Document",
            content="A legacy project without expansion bootstrap.",
            doc_type="project_doc",
        )
    )
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


def _valid_features_xml(label: str = "Default") -> str:
    """Wrap a single-feature valid <features> block for route tests.

    Route tests don't care about the specific feature set — they
    just need the expansion handler's parse-validate loop to
    accept the mocked CLI output as valid. Phase-11 followup B2
    made the sibling <vocabulary> block mandatory, so this helper
    appends a stub vocabulary entry too.
    """
    return (
        f"<features>"
        f"<feature>"
        f"<name>{label}</name>"
        f"<intent>Paragraph-length intent for the {label} feature "
        f"used as deterministic mock content in route tests.</intent>"
        f"</feature>"
        f"</features>"
        f"<vocabulary>"
        f'<term name="default" scope="project">'
        f"<vocab-entry><definition>Stub term for tests.</definition>"
        f"</vocab-entry>"
        f"</term>"
        f"</vocabulary>"
    )


def _patch_cli(
    monkeypatch,
    output: str,
    *,
    prompt_tokens: int = 100,
    completion_tokens: int = 50,
    model: str = "claude-sonnet-4-6",
):
    """Patch the CLI manager to return a deterministic GenerationResult.

    The output is fed through the real parse-validate retry loop,
    so passing a non-<features> string here will cause the
    expansion handler to retry up to its budget and then fail.
    Route tests that just want a successful generation should use
    :func:`_valid_features_xml` as the output.
    """
    from backend.cli.manager import GenerationResult

    async def fake_generate_with_usage(**kwargs):
        return GenerationResult(
            text=output,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            model=model,
        )

    monkeypatch.setattr(
        fe_handler.cli_manager,
        "generate_with_usage",
        fake_generate_with_usage,
    )


class TestGetExpansion:
    def test_empty_project_returns_node_without_draft(self, client, project):
        resp = client.get(f"/api/projects/{project.id}/expansion")
        assert resp.status_code == 200
        body = resp.json()
        assert body["node"]["name"] == "Feature Expansion"
        assert body["node"]["content"] == ""
        assert body["pending_draft"] is None
        assert body["generation_status"] == "idle"
        assert body["last_error"] is None

    def test_missing_project_returns_404(self, client):
        resp = client.get("/api/projects/nonexistent/expansion")
        assert resp.status_code == 404

    def test_legacy_project_auto_bootstraps_expansion(self, client, legacy_project, db):
        """Project without an expansion node shouldn't 404 — the GET
        route lazily mints one. Reproduces the "opening existing
        projects 404s" bug for projects created before Phase 1.
        """
        from backend.graph.expansion import get_expansion_node

        # Confirm the legacy project starts with no expansion node.
        db.expire_all()
        assert get_expansion_node(db, legacy_project.id) is None

        resp = client.get(f"/api/projects/{legacy_project.id}/expansion")
        assert resp.status_code == 200
        body = resp.json()
        # Bootstrap minted a node with expansion_ prefix and empty content.
        assert body["node"]["id"].startswith("expansion_")
        assert body["node"]["content"] == ""
        # A generation job was enqueued, so the projection reflects
        # "running".
        assert body["generation_status"] == "running"

        # And after the lazy bootstrap, the node persists.
        db.expire_all()
        persisted = get_expansion_node(db, legacy_project.id)
        assert persisted is not None
        assert persisted.id == body["node"]["id"]

    def test_reports_pending_draft(self, client, project, db, monkeypatch):
        mock_content = _valid_features_xml("TestPlan")
        _patch_cli(monkeypatch, mock_content)
        asyncio.run(
            fe_handler.generate_feature_expansion({"project_id": project.id, "feedback": None})
        )
        resp = client.get(f"/api/projects/{project.id}/expansion")
        assert resp.status_code == 200
        body = resp.json()
        assert body["pending_draft"] is not None
        assert body["pending_draft"]["content"] == mock_content
        # generation_status reflects jobs table; no job row exists here
        # because we drove the handler directly, so it's "idle".
        assert body["generation_status"] == "idle"


class TestFeedback:
    def test_enqueues_job(self, client, project, db):
        resp = client.post(
            f"/api/projects/{project.id}/expansion/feedback",
            json={"feedback": "Add reporting"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "job_id" in body

        # The job row exists and carries the right payload
        db.expire_all()
        jobs = list(
            db.execute(
                select(Job).where(Job.job_type == fe_handler.GENERATE_FEATURE_EXPANSION_JOB_TYPE)
            ).scalars()
        )
        assert len(jobs) == 1
        assert jobs[0].payload == {
            "project_id": project.id,
            "feedback": "Add reporting",
        }

    def test_empty_feedback_becomes_none(self, client, project, db):
        resp = client.post(
            f"/api/projects/{project.id}/expansion/feedback",
            json={"feedback": "   "},
        )
        assert resp.status_code == 200
        db.expire_all()
        job = db.execute(
            select(Job).where(Job.job_type == fe_handler.GENERATE_FEATURE_EXPANSION_JOB_TYPE)
        ).scalar_one()
        assert job.payload["feedback"] is None

    def test_expansion_status_running_after_enqueue(self, client, project):
        client.post(
            f"/api/projects/{project.id}/expansion/feedback",
            json={"feedback": "x"},
        )
        resp = client.get(f"/api/projects/{project.id}/expansion")
        assert resp.status_code == 200
        assert resp.json()["generation_status"] == "running"

    def test_get_surfaces_latest_telemetry_after_generation(self, client, project, db, monkeypatch):
        _patch_cli(
            monkeypatch,
            _valid_features_xml("Telemetry"),
            prompt_tokens=2048,
            completion_tokens=301,
            model="claude-sonnet-4-6",
        )
        asyncio.run(
            fe_handler.generate_feature_expansion({"project_id": project.id, "feedback": None})
        )

        resp = client.get(f"/api/projects/{project.id}/expansion")
        assert resp.status_code == 200
        body = resp.json()
        assert body["latest_telemetry"] is not None
        tlm = body["latest_telemetry"]
        assert tlm["prompt_tokens"] == 2048
        assert tlm["completion_tokens"] == 301
        assert tlm["model"] == "claude-sonnet-4-6"
        assert tlm["created_at"]

    def test_get_returns_null_telemetry_when_never_generated(self, client, project):
        resp = client.get(f"/api/projects/{project.id}/expansion")
        assert resp.status_code == 200
        assert resp.json()["latest_telemetry"] is None

    def test_feedback_rejected_after_approval(self, client, project, db, monkeypatch):
        """Post-approval feedback is blocked with 409.

        The v2 spec makes bootstrap nodes (expansion, reqs, sysarch)
        read-only after their initial approval — ongoing feature-layer
        edits happen on individual feature nodes, not by re-editing
        the expansion prose. This test exercises the guard at
        ``post_expansion_feedback``.
        """
        _patch_cli(monkeypatch, _valid_features_xml("ApprovedContent"))
        asyncio.run(
            fe_handler.generate_feature_expansion({"project_id": project.id, "feedback": None})
        )
        db.expire_all()
        draft = db.execute(select(Draft).where(Draft.project_id == project.id)).scalar_one()

        # Approve the draft — this flips node.content to non-empty.
        approve_resp = client.post(
            f"/api/projects/{project.id}/expansion/approve",
            json={"draft_id": draft.id},
        )
        assert approve_resp.status_code == 200

        # Now feedback should be rejected with 409.
        resp = client.post(
            f"/api/projects/{project.id}/expansion/feedback",
            json={"feedback": "actually let me change this"},
        )
        assert resp.status_code == 409
        assert "read-only" in resp.json()["detail"]


class TestApprove:
    def test_commits_draft_to_node(self, client, project, db, monkeypatch):
        final_content = _valid_features_xml("FinalContent")
        _patch_cli(monkeypatch, final_content)
        asyncio.run(
            fe_handler.generate_feature_expansion({"project_id": project.id, "feedback": None})
        )
        db.expire_all()
        draft = db.execute(select(Draft).where(Draft.project_id == project.id)).scalar_one()

        resp = client.post(
            f"/api/projects/{project.id}/expansion/approve",
            json={"draft_id": draft.id},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["node"]["content"] == final_content

        db.expire_all()
        draft_after = db.get(Draft, draft.id)
        assert draft_after is not None
        assert draft_after.status == "approved"

    def test_missing_draft_returns_404(self, client, project):
        resp = client.post(
            f"/api/projects/{project.id}/expansion/approve",
            json={"draft_id": "draft_MISSINGX"},
        )
        assert resp.status_code == 404

    def test_already_approved_returns_409(self, client, project, db, monkeypatch):
        _patch_cli(monkeypatch, _valid_features_xml("AlreadyApproved"))
        asyncio.run(
            fe_handler.generate_feature_expansion({"project_id": project.id, "feedback": None})
        )
        db.expire_all()
        draft = db.execute(select(Draft).where(Draft.project_id == project.id)).scalar_one()
        client.post(
            f"/api/projects/{project.id}/expansion/approve",
            json={"draft_id": draft.id},
        )
        # Second approval: the row is no longer pending.
        resp = client.post(
            f"/api/projects/{project.id}/expansion/approve",
            json={"draft_id": draft.id},
        )
        assert resp.status_code == 409


class TestDiscard:
    def test_flips_draft_to_discarded(self, client, project, db, monkeypatch):
        _patch_cli(monkeypatch, _valid_features_xml("Discarded"))
        asyncio.run(
            fe_handler.generate_feature_expansion({"project_id": project.id, "feedback": None})
        )
        db.expire_all()
        draft = db.execute(select(Draft).where(Draft.project_id == project.id)).scalar_one()

        resp = client.post(
            f"/api/projects/{project.id}/expansion/discard",
            json={"draft_id": draft.id},
        )
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}

        db.expire_all()
        draft_after = db.get(Draft, draft.id)
        assert draft_after is not None
        assert draft_after.status == "discarded"

        # And the node content is still empty.
        expansion_resp = client.get(f"/api/projects/{project.id}/expansion")
        assert expansion_resp.json()["node"]["content"] == ""

    def test_discard_enqueues_new_generation(self, client, project, db, monkeypatch):
        """Discarding a draft triggers a fresh generation so the
        user doesn't have to re-type 'try again' in the feedback
        box. The 'reject & regenerate' flow is the common case for
        iterating on the expansion during prompt testing.
        """
        _patch_cli(monkeypatch, _valid_features_xml("Rejected"))
        asyncio.run(
            fe_handler.generate_feature_expansion({"project_id": project.id, "feedback": None})
        )
        db.expire_all()
        draft = db.execute(select(Draft).where(Draft.project_id == project.id)).scalar_one()

        # Baseline: count existing generation jobs (there may be
        # one enqueued at project creation that's already complete).
        initial_gen_jobs = list(
            db.execute(
                select(Job).where(Job.job_type == fe_handler.GENERATE_FEATURE_EXPANSION_JOB_TYPE)
            ).scalars()
        )
        initial_count = len(initial_gen_jobs)

        client.post(
            f"/api/projects/{project.id}/expansion/discard",
            json={"draft_id": draft.id},
        )

        db.expire_all()
        gen_jobs = list(
            db.execute(
                select(Job).where(Job.job_type == fe_handler.GENERATE_FEATURE_EXPANSION_JOB_TYPE)
            ).scalars()
        )
        # At least one new generation job was enqueued by the
        # discard endpoint.
        assert len(gen_jobs) == initial_count + 1
        # The newest job's payload carries the project id and
        # null feedback (we're regenerating from scratch).
        newest = sorted(gen_jobs, key=lambda j: j.created_at)[-1]
        assert newest.payload == {"project_id": project.id, "feedback": None}


class TestApproveEnqueuesMint:
    """Approving a draft should enqueue the v2.mint_features job.

    The mint job runs on the pipeline worker to parse the now-
    approved expansion content and mint feat_* nodes.
    """

    def test_mint_job_enqueued_on_approve(self, client, project, db, monkeypatch):
        _patch_cli(monkeypatch, _valid_features_xml("MintTest"))
        asyncio.run(
            fe_handler.generate_feature_expansion({"project_id": project.id, "feedback": None})
        )
        db.expire_all()
        draft = db.execute(select(Draft).where(Draft.project_id == project.id)).scalar_one()

        resp = client.post(
            f"/api/projects/{project.id}/expansion/approve",
            json={"draft_id": draft.id},
        )
        assert resp.status_code == 200

        db.expire_all()
        from backend.graph.handlers.feature_mint import MINT_FEATURES_JOB_TYPE

        mint_jobs = list(
            db.execute(select(Job).where(Job.job_type == MINT_FEATURES_JOB_TYPE)).scalars()
        )
        assert len(mint_jobs) == 1
        assert mint_jobs[0].payload == {"project_id": project.id}
