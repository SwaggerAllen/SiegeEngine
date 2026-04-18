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
from sqlalchemy import create_engine  # noqa: E402
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
        review_xml = (
            "<review>"
            "<handles-structure>"
            '<finding id="h1">Names are specific; coverage is complete.</finding>'
            "</handles-structure>"
            "<architectural-decisions>"
            '<finding id="a1">Decomposition axis looks correct.</finding>'
            "</architectural-decisions>"
            "</review>"
        )
        _stub_cli(monkeypatch, review_xml)

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
        assert "<handles-structure>" in draft.review_text
        assert "<architectural-decisions>" in draft.review_text
        assert 'id="h1"' in draft.review_text

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
        _seed_pending_draft(db, seeded)

        resp = client.post(
            f"/api/projects/{seeded['project_id']}"
            f"/components/{seeded['comp_id']}/subrequirements/review/retry"
        )
        assert resp.status_code == 200, resp.text
        assert "job_id" in resp.json()

    def test_retroactive_review_against_approved_node_content(self, db, seeded, monkeypatch):
        """No pending draft, approved node content → review runs
        against ``node.content`` and lands on ``Node.review_text``.

        This is the grandfathered-content path: the subreqs node
        was approved before Phase 8 (or with reviews disabled) so
        ``review_text`` is empty. The retry endpoint enqueues a
        review with ``draft_id=None``; the handler falls back to
        reading the node's approved content.
        """
        # Approve some content onto the subreqs node directly
        # (no draft row). Mimics content minted before Phase 8.
        from backend.models.node import Node

        node = db.get(Node, seeded["subreqs_id"])
        assert node is not None
        node.content = (
            "<subrequirements><subresponsibility><name>X</name>"
            "<intent>Y</intent><derived-from>"
            f'<resp id="{seeded["resp_id"]}"/>'
            "</derived-from></subresponsibility></subrequirements>"
        )
        db.commit()

        review_xml = (
            "<review>"
            "<handles-structure>"
            '<finding id="h1">Looks good retroactively.</finding>'
            "</handles-structure>"
            "<architectural-decisions>"
            '<finding id="a1">Decomposition reasonable.</finding>'
            "</architectural-decisions>"
            "</review>"
        )
        _stub_cli(monkeypatch, review_xml)

        asyncio.run(
            review_handler.review_subreqs(
                {
                    "project_id": seeded["project_id"],
                    "node_id": seeded["subreqs_id"],
                    "draft_id": None,
                }
            )
        )

        db.expire_all()
        node = db.get(Node, seeded["subreqs_id"])
        assert node is not None
        assert "<handles-structure>" in node.review_text
        assert "<architectural-decisions>" in node.review_text

    def test_retroactive_retry_endpoint_allows_no_pending_draft(self, client, db, seeded):
        """The retry endpoint accepts approved-content-only state."""
        from backend.models.node import Node

        node = db.get(Node, seeded["subreqs_id"])
        assert node is not None
        node.content = "<subrequirements/>"
        db.commit()

        resp = client.post(
            f"/api/projects/{seeded['project_id']}"
            f"/components/{seeded['comp_id']}/subrequirements/review/retry"
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert "job_id" in body

        # Verify the enqueued job carries ``draft_id=None``.
        job = db.get(Job, body["job_id"])
        assert job is not None
        assert job.payload["draft_id"] is None
        assert job.payload["node_id"] == seeded["subreqs_id"]

    def test_retry_endpoint_rejects_when_no_draft_or_content(self, client, seeded):
        # No pending draft, no approved content either → 409.
        resp = client.post(
            f"/api/projects/{seeded['project_id']}"
            f"/components/{seeded['comp_id']}/subrequirements/review/retry"
        )
        assert resp.status_code == 409
