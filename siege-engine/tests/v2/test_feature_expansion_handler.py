"""Tests for backend.graph.handlers.feature_expansion.

The handler is async and opens its own ``SessionLocal()``. To make it
deterministic, we point ``backend.database.SessionLocal`` at an
in-memory engine with ``StaticPool + check_same_thread=False``, then
drive the handler with ``asyncio.run``. ``cli_manager.generate`` is
monkeypatched to return a canned string; the real CLI is never
invoked.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database import Base
from backend.graph import events as ev
from backend.graph.expansion import bootstrap_expansion_node
from backend.graph.handlers.feature_expansion import (
    FeatureExpansionHandlerError,
    generate_feature_expansion,
)
from backend.graph.reducer import append_event
from backend.models import InputDocument, Project
from backend.models.node import Draft
from backend.models.telemetry import GenerationTelemetry


@pytest.fixture()
def shared_session_factory(monkeypatch):
    """Redirect ``backend.database.SessionLocal`` to an in-memory engine.

    The handler under test does ``SessionLocal()`` twice on its own,
    so we have to replace the module-level factory. The pool pins a
    single connection across threads so the in-memory DB stays alive
    for the whole test.
    """
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    import backend.database as _database_mod
    import backend.graph.handlers.feature_expansion as _handler_mod

    monkeypatch.setattr(_database_mod, "SessionLocal", factory)
    monkeypatch.setattr(_handler_mod, "SessionLocal", factory)
    yield factory
    engine.dispose()


@pytest.fixture()
def seeded_project(shared_session_factory):
    """Create a project + input doc + expansion node in the shared engine."""
    factory = shared_session_factory
    session: Session = factory()
    try:
        project_id = str(uuid.uuid4())
        project = Project(id=project_id, name="T", git_repo_path="/tmp/t")
        session.add(project)
        session.flush()
        session.add(
            InputDocument(
                project_id=project_id,
                name="Project Document",
                content="Build a widget tracker.",
                doc_type="project_doc",
            )
        )
        bootstrap_expansion_node(session, project_id)
        session.commit()
        return project_id
    finally:
        session.close()


def _patch_cli(
    monkeypatch,
    return_value: str = "# Generated expansion\n",
    *,
    prompt_tokens: int = 100,
    completion_tokens: int = 50,
    model: str = "claude-sonnet-4-6",
):
    """Patch the ``cli_manager.generate_with_usage`` bound method used by the handler."""
    import backend.graph.handlers.feature_expansion as _handler_mod
    from backend.cli.manager import GenerationResult

    calls: list[dict] = []

    async def fake_generate_with_usage(**kwargs):
        calls.append(kwargs)
        return GenerationResult(
            text=return_value,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            model=model,
        )

    monkeypatch.setattr(_handler_mod.cli_manager, "generate_with_usage", fake_generate_with_usage)
    return calls


class TestHappyPath:
    def test_generates_pending_draft(self, shared_session_factory, seeded_project, monkeypatch):
        calls = _patch_cli(monkeypatch, "# First draft\n")
        asyncio.run(generate_feature_expansion({"project_id": seeded_project, "feedback": None}))

        assert len(calls) == 1
        assert "Build a widget tracker." in calls[0]["prompt"]
        assert calls[0]["system_prompt"]

        session = shared_session_factory()
        try:
            drafts = list(
                session.execute(select(Draft).where(Draft.project_id == seeded_project)).scalars()
            )
            assert len(drafts) == 1
            assert drafts[0].status == "pending"
            assert drafts[0].content == "# First draft\n"
            assert drafts[0].target_type == "node"
            assert drafts[0].id.startswith("draft_")
        finally:
            session.close()

    def test_regeneration_discards_old_pending(
        self, shared_session_factory, seeded_project, monkeypatch
    ):
        # First generation
        _patch_cli(monkeypatch, "# Draft one\n")
        asyncio.run(generate_feature_expansion({"project_id": seeded_project, "feedback": None}))

        # Second generation with feedback
        _patch_cli(monkeypatch, "# Draft two\n")
        asyncio.run(
            generate_feature_expansion({"project_id": seeded_project, "feedback": "Make it better"})
        )

        session = shared_session_factory()
        try:
            drafts = list(
                session.execute(
                    select(Draft)
                    .where(Draft.project_id == seeded_project)
                    .order_by(Draft.created_at.asc())
                ).scalars()
            )
            assert len(drafts) == 2
            statuses = [d.status for d in drafts]
            assert statuses.count("pending") == 1
            assert statuses.count("discarded") == 1
            # The pending one is the newer draft.
            pending = next(d for d in drafts if d.status == "pending")
            assert pending.content == "# Draft two\n"
        finally:
            session.close()

    def test_regeneration_passes_prior_pending_to_prompt(
        self, shared_session_factory, seeded_project, monkeypatch
    ):
        _patch_cli(monkeypatch, "# Draft one\n")
        asyncio.run(generate_feature_expansion({"project_id": seeded_project, "feedback": None}))

        calls = _patch_cli(monkeypatch, "# Draft two\n")
        asyncio.run(
            generate_feature_expansion(
                {"project_id": seeded_project, "feedback": "Shorten section 2"}
            )
        )

        assert len(calls) == 1
        prompt = calls[0]["prompt"]
        assert "# Draft one" in prompt
        assert "Shorten section 2" in prompt


class TestFailureModes:
    def test_missing_project_id_raises(self, shared_session_factory):
        with pytest.raises(FeatureExpansionHandlerError, match="project_id"):
            asyncio.run(generate_feature_expansion({}))

    def test_missing_expansion_node_raises(self, shared_session_factory):
        # Create a project without bootstrapping an expansion node.
        factory = shared_session_factory
        s = factory()
        try:
            pid = str(uuid.uuid4())
            s.add(Project(id=pid, name="T2", git_repo_path="/tmp/t2"))
            s.commit()
        finally:
            s.close()

        with pytest.raises(FeatureExpansionHandlerError, match="no expansion node"):
            asyncio.run(generate_feature_expansion({"project_id": pid, "feedback": None}))

    def test_cli_failure_leaves_no_events(
        self, shared_session_factory, seeded_project, monkeypatch
    ):
        import backend.graph.handlers.feature_expansion as _handler_mod

        async def boom(**kwargs):
            raise RuntimeError("LLM exploded")

        monkeypatch.setattr(_handler_mod.cli_manager, "generate_with_usage", boom)

        with pytest.raises(RuntimeError, match="LLM exploded"):
            asyncio.run(
                generate_feature_expansion({"project_id": seeded_project, "feedback": None})
            )

        session = shared_session_factory()
        try:
            drafts = list(
                session.execute(select(Draft).where(Draft.project_id == seeded_project)).scalars()
            )
            assert drafts == []
        finally:
            session.close()


class TestApprovalPath:
    """Spot-check that the handler + existing DraftApproved reducer
    branch compose: a generated draft can be approved and its content
    lands on the expansion node.
    """

    def test_approve_commits_content_to_node(
        self, shared_session_factory, seeded_project, monkeypatch
    ):
        _patch_cli(monkeypatch, "# Approved content\n")
        asyncio.run(generate_feature_expansion({"project_id": seeded_project, "feedback": None}))

        session = shared_session_factory()
        try:
            draft = session.execute(
                select(Draft).where(Draft.project_id == seeded_project)
            ).scalar_one()
            append_event(session, seeded_project, ev.DraftApproved(draft_id=draft.id))
            session.commit()

            from backend.graph.expansion import get_expansion_node

            node = get_expansion_node(session, seeded_project)
            assert node is not None
            assert node.content == "# Approved content\n"
        finally:
            session.close()


class TestTelemetry:
    """Every successful generation call records a telemetry row."""

    def test_records_telemetry_row(self, shared_session_factory, seeded_project, monkeypatch):
        _patch_cli(
            monkeypatch,
            "# Draft\n",
            prompt_tokens=1234,
            completion_tokens=567,
            model="claude-sonnet-4-6",
        )
        asyncio.run(generate_feature_expansion({"project_id": seeded_project, "feedback": None}))

        session = shared_session_factory()
        try:
            rows = list(
                session.execute(
                    select(GenerationTelemetry).where(
                        GenerationTelemetry.project_id == seeded_project
                    )
                ).scalars()
            )
            assert len(rows) == 1
            row = rows[0]
            assert row.section == "expansion"
            assert row.prompt_tokens == 1234
            assert row.completion_tokens == 567
            assert row.model == "claude-sonnet-4-6"
            assert row.node_id is not None
            assert row.node_id.startswith("expansion_")
        finally:
            session.close()

    def test_telemetry_accumulates_across_regens(
        self, shared_session_factory, seeded_project, monkeypatch
    ):
        """Two generations produce two telemetry rows, newest last."""
        _patch_cli(
            monkeypatch,
            "# First\n",
            prompt_tokens=100,
            completion_tokens=50,
        )
        asyncio.run(generate_feature_expansion({"project_id": seeded_project, "feedback": None}))
        _patch_cli(
            monkeypatch,
            "# Second\n",
            prompt_tokens=200,
            completion_tokens=75,
        )
        asyncio.run(
            generate_feature_expansion({"project_id": seeded_project, "feedback": "more please"})
        )

        session = shared_session_factory()
        try:
            rows = list(
                session.execute(
                    select(GenerationTelemetry)
                    .where(GenerationTelemetry.project_id == seeded_project)
                    .order_by(GenerationTelemetry.created_at)
                ).scalars()
            )
            assert len(rows) == 2
            assert rows[0].prompt_tokens == 100
            assert rows[1].prompt_tokens == 200
        finally:
            session.close()

    def test_cli_failure_writes_no_telemetry_row(
        self, shared_session_factory, seeded_project, monkeypatch
    ):
        import backend.graph.handlers.feature_expansion as _handler_mod

        async def boom(**kwargs):
            raise RuntimeError("LLM exploded")

        monkeypatch.setattr(_handler_mod.cli_manager, "generate_with_usage", boom)

        with pytest.raises(RuntimeError):
            asyncio.run(
                generate_feature_expansion({"project_id": seeded_project, "feedback": None})
            )

        session = shared_session_factory()
        try:
            rows = list(
                session.execute(
                    select(GenerationTelemetry).where(
                        GenerationTelemetry.project_id == seeded_project
                    )
                ).scalars()
            )
            assert rows == []
        finally:
            session.close()
