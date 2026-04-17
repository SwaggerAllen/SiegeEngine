"""Tests for backend.graph.handlers.impl_generation (Phase 8).

Mirrors test_subcomparch_handler shape. The CLI is mocked; the
real parse-validate retry loop runs through the impl validator.
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
from backend.graph.handlers.impl_generation import (
    ImplHandlerError,
    ImplParseRetryExhausted,
    ImplPreconditionError,
    generate_impl,
)
from backend.graph.ids import Kind, mint
from backend.graph.reducer import append_event
from backend.models import Project
from backend.models.node import Draft, Node
from backend.models.telemetry import GenerationTelemetry


@pytest.fixture(autouse=True)
def _fast_cli_retry_backoff(monkeypatch):
    import backend.graph.handlers.feature_expansion as _fe_handler

    monkeypatch.setattr(
        _fe_handler,
        "CLI_RETRY_BACKOFF_SECONDS",
        (0.0,) * (_fe_handler.CLI_MAX_TRANSIENT_RETRIES + 1),
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
    import backend.graph.handlers.impl_generation as _handler_mod

    monkeypatch.setattr(_database_mod, "SessionLocal", factory)
    monkeypatch.setattr(_handler_mod, "SessionLocal", factory)
    yield factory
    engine.dispose()


def _seed_project_with_owner(factory, owner_kind: str = "top_level") -> tuple[str, str, str]:
    """Seed a project + owning comp + empty impl shell.

    Returns (project_id, owner_id, impl_id). ``owner_kind`` is
    ``"top_level"`` for an un-fanned-out comp (impl's owner is
    the top-level itself) or ``"sub"`` (impl's owner is a
    subcomponent whose parent is a top-level comp).
    """
    session: Session = factory()
    try:
        project_id = str(uuid.uuid4())
        session.add(Project(id=project_id, name="T", git_repo_path="/tmp/t"))
        session.flush()

        if owner_kind == "top_level":
            owner_id = mint(session, Kind.COMP)
            append_event(
                session,
                project_id,
                ev.NodeCreated(
                    node_id=owner_id,
                    tier="comp",
                    kind="domain",
                    parent_id=None,
                    name="TopComp",
                    content="<comparch>...</comparch>",  # approved content
                ),
            )
        else:
            top_id = mint(session, Kind.COMP)
            append_event(
                session,
                project_id,
                ev.NodeCreated(
                    node_id=top_id,
                    tier="comp",
                    kind="domain",
                    parent_id=None,
                    name="Parent",
                    content="<comparch>...</comparch>",
                ),
            )
            owner_id = mint(session, Kind.COMP)
            append_event(
                session,
                project_id,
                ev.NodeCreated(
                    node_id=owner_id,
                    tier="comp",
                    kind="domain",
                    parent_id=top_id,
                    name="Sub",
                    content="<subcomparch>...</subcomparch>",
                ),
            )

        impl_id = mint(session, Kind.IMPL)
        append_event(
            session,
            project_id,
            ev.NodeCreated(
                node_id=impl_id,
                tier="impl",
                kind="domain",
                parent_id=owner_id,
                name=f"{'TopComp' if owner_kind == 'top_level' else 'Sub'} impl",
            ),
        )
        session.commit()
        return project_id, owner_id, impl_id
    finally:
        session.close()


_VALID_IMPL = (
    "<implementation>"
    "<behavior>Stub behavior.</behavior>"
    "<invariants>Stub invariants.</invariants>"
    "<sequencing>Stub sequencing.</sequencing>"
    "<edge-cases>Stub edges.</edge-cases>"
    "</implementation>"
)


def _patch_cli(monkeypatch, return_value: str = _VALID_IMPL):
    import backend.graph.handlers.feature_expansion as _fe_mod
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
    import backend.graph.handlers.feature_expansion as _fe_mod
    from backend.cli.manager import GenerationResult

    calls: list[dict] = []
    remaining = list(return_values)

    async def fake(**kwargs):
        calls.append(kwargs)
        if not remaining:
            raise RuntimeError("CLI mock exhausted")
        return GenerationResult(
            text=remaining.pop(0),
            prompt_tokens=100,
            completion_tokens=50,
            model="claude-sonnet-4-6",
        )

    monkeypatch.setattr(_fe_mod.cli_manager, "generate_with_usage", fake)
    return calls


class TestHappyPath:
    def test_generates_pending_draft_for_top_level(self, shared_session_factory, monkeypatch):
        project_id, owner_id, impl_id = _seed_project_with_owner(
            shared_session_factory, owner_kind="top_level"
        )
        _patch_cli(monkeypatch)
        asyncio.run(generate_impl({"project_id": project_id, "owner_id": owner_id}))

        session = shared_session_factory()
        try:
            drafts = list(
                session.execute(
                    select(Draft).where(
                        Draft.project_id == project_id,
                        Draft.target_id == impl_id,
                        Draft.status == "pending",
                    )
                ).scalars()
            )
            assert len(drafts) == 1
            assert "<implementation>" in drafts[0].content
            telemetry = list(
                session.execute(
                    select(GenerationTelemetry).where(
                        GenerationTelemetry.project_id == project_id,
                        GenerationTelemetry.node_id == impl_id,
                        GenerationTelemetry.section == "impl",
                    )
                ).scalars()
            )
            assert len(telemetry) == 1
        finally:
            session.close()

    def test_generates_pending_draft_for_subcomponent(self, shared_session_factory, monkeypatch):
        project_id, owner_id, impl_id = _seed_project_with_owner(
            shared_session_factory, owner_kind="sub"
        )
        _patch_cli(monkeypatch)
        asyncio.run(generate_impl({"project_id": project_id, "owner_id": owner_id}))
        session = shared_session_factory()
        try:
            draft = session.execute(
                select(Draft).where(
                    Draft.target_id == impl_id,
                    Draft.status == "pending",
                )
            ).scalar_one()
            assert "<implementation>" in draft.content
        finally:
            session.close()


class TestPreconditionErrors:
    def test_empty_owner_content_fails_precondition(self, shared_session_factory, monkeypatch):
        """Impl generation requires owner.content non-empty."""
        session = shared_session_factory()
        try:
            project_id = str(uuid.uuid4())
            session.add(Project(id=project_id, name="T", git_repo_path="/tmp/t"))
            session.flush()
            owner_id = mint(session, Kind.COMP)
            append_event(
                session,
                project_id,
                ev.NodeCreated(
                    node_id=owner_id,
                    tier="comp",
                    kind="domain",
                    parent_id=None,
                    name="Empty",
                    content="",  # arch doc not approved
                ),
            )
            impl_id = mint(session, Kind.IMPL)
            append_event(
                session,
                project_id,
                ev.NodeCreated(
                    node_id=impl_id,
                    tier="impl",
                    kind="domain",
                    parent_id=owner_id,
                    name="Empty impl",
                ),
            )
            session.commit()
        finally:
            session.close()

        _patch_cli(monkeypatch)
        with pytest.raises(ImplPreconditionError):
            asyncio.run(generate_impl({"project_id": project_id, "owner_id": owner_id}))

    def test_missing_impl_shell_raises(self, shared_session_factory, monkeypatch):
        """Owner approved but no impl shell — should raise (shouldn't happen in practice)."""
        session = shared_session_factory()
        try:
            project_id = str(uuid.uuid4())
            session.add(Project(id=project_id, name="T", git_repo_path="/tmp/t"))
            session.flush()
            owner_id = mint(session, Kind.COMP)
            append_event(
                session,
                project_id,
                ev.NodeCreated(
                    node_id=owner_id,
                    tier="comp",
                    kind="domain",
                    parent_id=None,
                    name="Owner",
                    content="<comparch/>",
                ),
            )
            session.commit()
        finally:
            session.close()
        _patch_cli(monkeypatch)
        with pytest.raises(ImplHandlerError, match="no impl shell"):
            asyncio.run(generate_impl({"project_id": project_id, "owner_id": owner_id}))


class TestPayloadErrors:
    def test_missing_project_id_raises(self, shared_session_factory):
        with pytest.raises(ImplHandlerError):
            asyncio.run(generate_impl({"owner_id": "comp_XXXXXXXX"}))

    def test_missing_owner_id_raises(self, shared_session_factory):
        with pytest.raises(ImplHandlerError):
            asyncio.run(generate_impl({"project_id": "pid"}))

    def test_unknown_owner_raises(self, shared_session_factory, monkeypatch):
        session = shared_session_factory()
        try:
            project_id = str(uuid.uuid4())
            session.add(Project(id=project_id, name="T", git_repo_path="/tmp/t"))
            session.commit()
        finally:
            session.close()
        _patch_cli(monkeypatch)
        with pytest.raises(ImplHandlerError, match="not found"):
            asyncio.run(generate_impl({"project_id": project_id, "owner_id": "comp_DEADBEEF"}))


class TestRetryLoop:
    def test_retries_on_parse_failure_then_succeeds(self, shared_session_factory, monkeypatch):
        project_id, owner_id, impl_id = _seed_project_with_owner(shared_session_factory)
        calls = _patch_cli_sequence(
            monkeypatch,
            return_values=[
                "<nope/>",  # wrong root
                _VALID_IMPL,
            ],
        )
        asyncio.run(generate_impl({"project_id": project_id, "owner_id": owner_id}))
        assert len(calls) == 2

    def test_exhausts_retries(self, shared_session_factory, monkeypatch):
        project_id, owner_id, _ = _seed_project_with_owner(shared_session_factory)
        from backend.graph.handlers.feature_expansion import MAX_PARSE_RETRIES

        _patch_cli_sequence(
            monkeypatch,
            return_values=["<bad/>"] * (MAX_PARSE_RETRIES + 1),
        )
        with pytest.raises(ImplParseRetryExhausted):
            asyncio.run(generate_impl({"project_id": project_id, "owner_id": owner_id}))


class TestRegenerateAfterApproval:
    """Impl is never frozen — regen flows freely post-approval."""

    def test_post_approval_regen_succeeds(self, shared_session_factory, monkeypatch):
        project_id, owner_id, impl_id = _seed_project_with_owner(shared_session_factory)
        _patch_cli(monkeypatch)
        asyncio.run(generate_impl({"project_id": project_id, "owner_id": owner_id}))

        # Approve the draft so Node.content is populated.
        session = shared_session_factory()
        try:
            draft = session.execute(
                select(Draft).where(Draft.target_id == impl_id, Draft.status == "pending")
            ).scalar_one()
            append_event(session, project_id, ev.DraftApproved(draft_id=draft.id))
            session.commit()
            impl_node = session.get(Node, impl_id)
            assert impl_node is not None
            assert impl_node.content  # approved

            # Run again — should produce a new draft regardless.
        finally:
            session.close()

        asyncio.run(
            generate_impl(
                {
                    "project_id": project_id,
                    "owner_id": owner_id,
                    "feedback": "please iterate",
                }
            )
        )
        session = shared_session_factory()
        try:
            pending = list(
                session.execute(
                    select(Draft).where(
                        Draft.target_id == impl_id,
                        Draft.status == "pending",
                    )
                ).scalars()
            )
            assert len(pending) == 1
        finally:
            session.close()
