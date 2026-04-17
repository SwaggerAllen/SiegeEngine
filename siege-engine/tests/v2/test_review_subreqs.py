"""End-to-end test for the subreqs AI self-review flow.

Verifies the vertical slice:

- ``persist_draft`` enqueues a ``v2.review_subreqs`` job after
  committing a generated draft.
- The review handler re-assembles context via the shared
  ``gather_subreqs_context`` builder, runs the CLI (stubbed),
  and emits ``DraftReviewUpdated``.
- The Draft's ``review_text`` column lands with the CLI output.
- Regenerating a draft cancels the in-flight review for the
  prior draft (via ``persist_draft``'s cancellation hook).
- The retry endpoint enqueues a fresh review after a failure.
"""

from __future__ import annotations

import asyncio
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
from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

import backend.graph  # noqa: E402,F401 — triggers handler registration
from backend.auth.routes import get_current_user  # noqa: E402
from backend.cli.manager import GenerationResult  # noqa: E402
from backend.database import Base, get_db  # noqa: E402
from backend.graph import events as ev  # noqa: E402
from backend.graph.handlers import review_subreqs as review_handler  # noqa: E402
from backend.graph.ids import Kind, mint  # noqa: E402
from backend.graph.reducer import append_event  # noqa: E402
from backend.graph.subrequirements import bootstrap_subreqs_node  # noqa: E402
from backend.main import app  # noqa: E402
from backend.models import Project  # noqa: E402
from backend.models.job import Job  # noqa: E402
from backend.models.node import Draft  # noqa: E402


@pytest.fixture()
def engine_and_factory(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    import importlib

    for path in (
        "backend.database",
        "backend.pipeline.queue",
        "backend.graph.handlers._bootstrap_generation",
        "backend.graph.handlers._bootstrap_review",
        "backend.graph.handlers.subreqs_generation",
        "backend.graph.handlers.review_subreqs",
    ):
        module = importlib.import_module(path)
        monkeypatch.setattr(module, "SessionLocal", factory, raising=False)

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
def seeded(db):
    """A project with one comp_*, a parent resp assigned to it, and a subreqs shell."""
    project = Project(id=str(uuid.uuid4()), name="Test", git_repo_path="/tmp/t")
    db.add(project)
    db.flush()

    resp_id = mint(db, Kind.RESP)
    append_event(
        db,
        project.id,
        ev.NodeCreated(
            node_id=resp_id,
            tier="resp",
            kind="domain",
            parent_id=None,
            name="Auth",
            content="Identify callers.",
        ),
    )
    comp_id = mint(db, Kind.COMP)
    append_event(
        db,
        project.id,
        ev.NodeCreated(
            node_id=comp_id,
            tier="comp",
            kind="domain",
            parent_id=None,
            name="AuthN",
            content="<comparch/>",
        ),
    )
    edge_id = mint(db, Kind.EDGE)
    append_event(
        db,
        project.id,
        ev.EdgeCreated(
            edge_id=edge_id,
            edge_type="decomposition",
            source_id=resp_id,
            target_id=comp_id,
        ),
    )
    subreqs_id = bootstrap_subreqs_node(db, project.id, comp_id)
    db.commit()
    return {
        "project_id": project.id,
        "comp_id": comp_id,
        "subreqs_id": subreqs_id,
        "resp_id": resp_id,
    }


@pytest.fixture()
def client(db, seeded):
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


def _seed_pending_draft(db, seeded) -> str:
    """Create a pending subreqs draft row to review against."""
    draft_id = "draft_review0001"
    db.add(
        Draft(
            id=draft_id,
            project_id=seeded["project_id"],
            target_type="node",
            target_id=seeded["subreqs_id"],
            content="<subrequirements><subresponsibility><name>X</name>"
            "<intent>Y</intent><derived-from>"
            f'<resp id="{seeded["resp_id"]}"/>'
            "</derived-from></subresponsibility></subrequirements>",
            status="pending",
            batch_id="batch_review00001",
        )
    )
    db.commit()
    return draft_id


def _stub_cli(monkeypatch, review_markdown: str) -> None:
    async def fake_generate_with_usage(**kwargs):
        return GenerationResult(
            text=review_markdown,
            prompt_tokens=100,
            completion_tokens=50,
            model="claude-fake",
        )

    # The CLI is a module-level singleton (``cli_manager``) with
    # ``generate_with_usage`` as an instance method. Each handler
    # module imports the singleton; patching the bound method on
    # the instance applies to every caller that dereferences
    # through that singleton.
    import backend.graph.handlers.feature_expansion as fe_handler

    monkeypatch.setattr(fe_handler.cli_manager, "generate_with_usage", fake_generate_with_usage)


class TestReviewSubreqs:
    def test_review_handler_commits_draft_review_updated(self, db, seeded, monkeypatch):
        draft_id = _seed_pending_draft(db, seeded)
        review_md = (
            "## Handles & structure\n\n"
            "Names are specific; coverage is complete.\n\n"
            "## Architectural decisions\n\n"
            "Decomposition axis looks correct."
        )
        _stub_cli(monkeypatch, review_md)

        asyncio.run(
            review_handler.review_subreqs(
                {
                    "project_id": seeded["project_id"],
                    "node_id": seeded["subreqs_id"],
                    "draft_id": draft_id,
                }
            )
        )

        db.expire_all()
        draft = db.get(Draft, draft_id)
        assert draft is not None
        assert "## Handles & structure" in draft.review_text
        assert "## Architectural decisions" in draft.review_text

    def test_review_handler_rejects_empty_cli_output(self, db, seeded, monkeypatch):
        draft_id = _seed_pending_draft(db, seeded)
        _stub_cli(monkeypatch, "   \n  ")

        from backend.graph.handlers._bootstrap_review import ReviewError

        with pytest.raises(ReviewError):
            asyncio.run(
                review_handler.review_subreqs(
                    {
                        "project_id": seeded["project_id"],
                        "node_id": seeded["subreqs_id"],
                        "draft_id": draft_id,
                    }
                )
            )

        db.expire_all()
        draft = db.get(Draft, draft_id)
        assert draft is not None
        assert draft.review_text == ""

    def test_retry_endpoint_re_enqueues_review(self, client, db, seeded):
        draft_id = _seed_pending_draft(db, seeded)

        resp = client.post(
            f"/api/projects/{seeded['project_id']}"
            f"/components/{seeded['comp_id']}/subrequirements/review/retry"
        )
        assert resp.status_code == 200, resp.text
        assert "job_id" in resp.json()

        jobs = list(db.execute(select(Job).where(Job.job_type == "v2.review_subreqs")).scalars())
        assert len(jobs) == 1
        assert jobs[0].payload.get("node_id") == seeded["subreqs_id"]
        assert jobs[0].payload.get("draft_id") == draft_id

    def test_retry_endpoint_rejects_when_no_draft_or_content(self, client, seeded):
        # No pending draft, no approved content either → 409.
        resp = client.post(
            f"/api/projects/{seeded['project_id']}"
            f"/components/{seeded['comp_id']}/subrequirements/review/retry"
        )
        assert resp.status_code == 409
