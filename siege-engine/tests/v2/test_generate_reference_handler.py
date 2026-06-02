"""Tests for backend.graph.handlers.generate_reference (Phase 6.6).

Same shape as ``test_feature_expansion_handler.py``: point
``SessionLocal`` at an in-memory engine, monkeypatch
``cli_manager.generate_with_usage`` to return a canned
``<reference>`` block, drive the async handler with
``asyncio.run``.
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
from backend.graph.handlers.generate_reference import (
    ReferenceHandlerError,
    ReferenceParseRetryExhausted,
    generate_reference,
)
from backend.graph.ids import Kind, mint
from backend.graph.reducer import append_event
from backend.models import Project
from backend.models.node import Draft, Node
from backend.models.telemetry import GenerationTelemetry


@pytest.fixture(autouse=True)
def _fast_cli_retry_backoff(monkeypatch):
    import backend.graph.handlers._bootstrap_generation as _handler_mod

    monkeypatch.setattr(
        _handler_mod,
        "CLI_RETRY_BACKOFF_SECONDS",
        (0.0,) * (_handler_mod.CLI_MAX_TRANSIENT_RETRIES + 1),
    )


@pytest.fixture()
def shared_session_factory(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    import backend.database as _database_mod
    import backend.graph.handlers.generate_reference as _handler_mod

    monkeypatch.setattr(_database_mod, "SessionLocal", factory)
    monkeypatch.setattr(_handler_mod, "SessionLocal", factory)
    yield factory
    engine.dispose()


@pytest.fixture()
def seeded_ref(shared_session_factory):
    """Create a project + empty ref node in the shared engine. Returns (project_id, ref_id)."""
    factory = shared_session_factory
    session: Session = factory()
    try:
        project_id = str(uuid.uuid4())
        project = Project(id=project_id, name="T", git_repo_path="/tmp/t")
        session.add(project)
        session.flush()
        ref_id = mint(session, Kind.REF)
        append_event(
            session,
            project_id,
            ev.NodeCreated(
                node_id=ref_id,
                tier="ref",
                kind="domain",
                parent_id=None,
                name="Deployment Runbook",
            ),
        )
        session.commit()
        return (project_id, ref_id)
    finally:
        session.close()


_VALID_REFERENCE_XML = (
    "<reference>"
    "<title>Deployment Runbook</title>"
    "<body>Run kubectl apply. Then verify pods.</body>"
    "</reference>"
)


def _patch_cli(monkeypatch, return_value: str = _VALID_REFERENCE_XML):
    # The run_parse_validate_loop lives in _bootstrap_generation and
    # imports _call_cli_with_transient_retry from feature_expansion;
    # its cli_manager is what we need to patch.
    import backend.graph.handlers._bootstrap_generation as _fe_mod
    from backend.cli.manager import GenerationResult

    calls: list[dict] = []

    async def fake(**kwargs):
        calls.append(kwargs)
        return GenerationResult(
            text=return_value,
            prompt_tokens=100,
            completion_tokens=50,
            model="claude-sonnet-4-6",
        )

    monkeypatch.setattr(_fe_mod.cli_manager, "generate_with_usage", fake)
    return calls


def _patch_cli_sequence(monkeypatch, return_values: list[str]):
    import backend.graph.handlers._bootstrap_generation as _fe_mod
    from backend.cli.manager import GenerationResult

    calls: list[dict] = []
    remaining = list(return_values)

    async def fake(**kwargs):
        calls.append(kwargs)
        if not remaining:
            raise RuntimeError("CLI mock exhausted")
        text = remaining.pop(0)
        return GenerationResult(
            text=text,
            prompt_tokens=100,
            completion_tokens=50,
            model="claude-sonnet-4-6",
        )

    monkeypatch.setattr(_fe_mod.cli_manager, "generate_with_usage", fake)
    return calls


class TestHappyPath:
    def test_generates_pending_draft(self, shared_session_factory, seeded_ref, monkeypatch):
        project_id, ref_id = seeded_ref
        _patch_cli(monkeypatch)
        asyncio.run(
            generate_reference(
                {
                    "project_id": project_id,
                    "ref_id": ref_id,
                    "seed_description": "Deployment runbook",
                    "feedback": None,
                }
            )
        )

        session: Session = shared_session_factory()
        try:
            drafts = list(
                session.execute(
                    select(Draft).where(
                        Draft.project_id == project_id,
                        Draft.target_id == ref_id,
                        Draft.status == "pending",
                    )
                ).scalars()
            )
            assert len(drafts) == 1
            assert "<reference>" in drafts[0].content
            telemetry = list(
                session.execute(
                    select(GenerationTelemetry).where(
                        GenerationTelemetry.project_id == project_id,
                        GenerationTelemetry.node_id == ref_id,
                        GenerationTelemetry.section == "reference",
                    )
                ).scalars()
            )
            assert len(telemetry) == 1
        finally:
            session.close()

    def test_regeneration_discards_old_pending(
        self, shared_session_factory, seeded_ref, monkeypatch
    ):
        project_id, ref_id = seeded_ref
        _patch_cli(monkeypatch)
        asyncio.run(
            generate_reference(
                {
                    "project_id": project_id,
                    "ref_id": ref_id,
                    "seed_description": "x",
                    "feedback": None,
                }
            )
        )
        asyncio.run(
            generate_reference(
                {
                    "project_id": project_id,
                    "ref_id": ref_id,
                    "seed_description": "x",
                    "feedback": "add more detail",
                }
            )
        )

        session: Session = shared_session_factory()
        try:
            pending = list(
                session.execute(
                    select(Draft).where(
                        Draft.project_id == project_id,
                        Draft.target_id == ref_id,
                        Draft.status == "pending",
                    )
                ).scalars()
            )
            assert len(pending) == 1
            discarded = list(
                session.execute(
                    select(Draft).where(
                        Draft.project_id == project_id,
                        Draft.target_id == ref_id,
                        Draft.status == "discarded",
                    )
                ).scalars()
            )
            assert len(discarded) == 1
        finally:
            session.close()


class TestPostApprovalRegenNotFrozen:
    """Refs are NOT frozen after approval — regen still works.

    This is the key behavioral difference from bootstrap tiers
    (expansion / reqs / sysarch / subreqs), which reject
    post-approval feedback.
    """

    def test_post_approval_regen_produces_new_draft(
        self, shared_session_factory, seeded_ref, monkeypatch
    ):
        project_id, ref_id = seeded_ref
        _patch_cli(monkeypatch)
        asyncio.run(
            generate_reference(
                {
                    "project_id": project_id,
                    "ref_id": ref_id,
                    "seed_description": "x",
                    "feedback": None,
                }
            )
        )

        # Approve the first draft so Node.content is set
        session: Session = shared_session_factory()
        try:
            draft = session.execute(
                select(Draft).where(
                    Draft.project_id == project_id,
                    Draft.target_id == ref_id,
                    Draft.status == "pending",
                )
            ).scalar_one()
            append_event(session, project_id, ev.DraftApproved(draft_id=draft.id))
            session.commit()
            node = session.get(Node, ref_id)
            assert node is not None
            assert node.content  # now approved
        finally:
            session.close()

        # Trigger a post-approval regen — this would 409 on a bootstrap tier
        asyncio.run(
            generate_reference(
                {
                    "project_id": project_id,
                    "ref_id": ref_id,
                    "seed_description": "x",
                    "feedback": "please update",
                }
            )
        )

        # A new pending draft should exist
        session = shared_session_factory()
        try:
            pending = list(
                session.execute(
                    select(Draft).where(
                        Draft.project_id == project_id,
                        Draft.target_id == ref_id,
                        Draft.status == "pending",
                    )
                ).scalars()
            )
            assert len(pending) == 1
        finally:
            session.close()


class TestParseValidateRetry:
    def test_retries_on_parse_failure_then_succeeds(
        self, shared_session_factory, seeded_ref, monkeypatch
    ):
        project_id, ref_id = seeded_ref
        calls = _patch_cli_sequence(
            monkeypatch,
            return_values=[
                "<references><title>X</title><body>Y</body></references>",  # wrong root tag
                _VALID_REFERENCE_XML,
            ],
        )
        asyncio.run(
            generate_reference(
                {
                    "project_id": project_id,
                    "ref_id": ref_id,
                    "seed_description": "x",
                    "feedback": None,
                }
            )
        )
        assert len(calls) == 2  # first attempt + 1 retry

    def test_exhausts_retries_and_raises(self, shared_session_factory, seeded_ref, monkeypatch):
        project_id, ref_id = seeded_ref
        from backend.graph.handlers._bootstrap_generation import MAX_PARSE_RETRIES

        _patch_cli_sequence(
            monkeypatch,
            return_values=["<bad/>"] * (MAX_PARSE_RETRIES + 1),
        )
        with pytest.raises(ReferenceParseRetryExhausted):
            asyncio.run(
                generate_reference(
                    {
                        "project_id": project_id,
                        "ref_id": ref_id,
                        "seed_description": "x",
                        "feedback": None,
                    }
                )
            )


class TestErrors:
    def test_missing_project_id_raises(self, shared_session_factory):
        with pytest.raises(ReferenceHandlerError):
            asyncio.run(generate_reference({"ref_id": "ref_ABCDEFGH"}))

    def test_missing_ref_id_raises(self, shared_session_factory):
        with pytest.raises(ReferenceHandlerError):
            asyncio.run(generate_reference({"project_id": "some-proj"}))

    def test_unknown_ref_id_raises(self, shared_session_factory, seeded_ref):
        project_id, _ = seeded_ref
        with pytest.raises(ReferenceHandlerError, match="not found"):
            asyncio.run(
                generate_reference(
                    {
                        "project_id": project_id,
                        "ref_id": "ref_DEADBEEF",
                        "seed_description": "x",
                    }
                )
            )
