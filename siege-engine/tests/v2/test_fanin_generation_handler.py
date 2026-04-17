"""Tests for backend.graph.handlers.fanin_generation (Phase 7).

Mirrors test_impl_handler shape. The CLI is mocked; the real
parse-validate retry loop runs through the fan-in validator.

Coverage:
- Happy path: validated <fanin> block lands on Node.content via
  FanInContentUpdated (no Draft row).
- Re-invocation overwrites existing fan-in content.
- Parse-retry loop survives one bad attempt.
- Parse-retry loop exhausted raises FanInParseRetryExhausted.
- Missing fanin shell raises FanInHandlerError.
- Payload shape errors raise FanInHandlerError.
- Telemetry rows recorded with section="fanin".
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
from backend.graph.handlers.fanin_generation import (
    FanInHandlerError,
    FanInParseRetryExhausted,
    generate_fanin,
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
    import backend.graph.handlers.fanin_generation as _handler_mod

    monkeypatch.setattr(_database_mod, "SessionLocal", factory)
    monkeypatch.setattr(_handler_mod, "SessionLocal", factory)
    yield factory
    engine.dispose()


_VALID_FANIN = (
    "<fanin>"
    "<summary>Stub summary.</summary>"
    "<exposed-surface>Stub surface.</exposed-surface>"
    "<realized-behavior>Stub behavior.</realized-behavior>"
    "</fanin>"
)

_INVALID_FANIN_WRONG_ORDER = (
    "<fanin>"
    "<exposed-surface>Out-of-order.</exposed-surface>"
    "<summary>Nope.</summary>"
    "<realized-behavior>R.</realized-behavior>"
    "</fanin>"
)


def _seed_fanned_out_domain_comp(factory) -> tuple[str, str, str]:
    """Seed a project with:
    - One fanned-out domain comp.
    - Two subcomponents under it, each with approved impl.
    - One fan-in shell under the comp (content="").
    Returns (project_id, comp_id, fanin_id).
    """
    session: Session = factory()
    try:
        project_id = str(uuid.uuid4())
        session.add(Project(id=project_id, name="T", git_repo_path="/tmp/t"))
        session.flush()

        comp_id = mint(session, Kind.COMP)
        append_event(
            session,
            project_id,
            ev.NodeCreated(
                node_id=comp_id,
                tier="comp",
                kind="domain",
                parent_id=None,
                name="Owner",
                content="<comparch>ok</comparch>",
            ),
        )

        for i, sub_name in enumerate(["SubA", "SubB"]):
            sub_id = mint(session, Kind.COMP)
            append_event(
                session,
                project_id,
                ev.NodeCreated(
                    node_id=sub_id,
                    tier="comp",
                    kind="domain",
                    parent_id=comp_id,
                    name=sub_name,
                    content="<subcomparch>ok</subcomparch>",
                    display_order=i,
                ),
            )
            # Each sub has an approved impl.
            impl_id = mint(session, Kind.IMPL)
            append_event(
                session,
                project_id,
                ev.NodeCreated(
                    node_id=impl_id,
                    tier="impl",
                    kind="domain",
                    parent_id=sub_id,
                    name=f"{sub_name} impl",
                    content=(
                        f"<implementation>"
                        f"<behavior>{sub_name} B</behavior>"
                        f"<invariants>{sub_name} I</invariants>"
                        f"<sequencing>{sub_name} S</sequencing>"
                        f"<edge-cases>{sub_name} E</edge-cases>"
                        f"</implementation>"
                    ),
                ),
            )

        fanin_id = mint(session, Kind.FANIN)
        append_event(
            session,
            project_id,
            ev.NodeCreated(
                node_id=fanin_id,
                tier="fanin",
                kind="domain",
                parent_id=comp_id,
                name="Owner fan-in",
                content="",
            ),
        )
        session.commit()
        return project_id, comp_id, fanin_id
    finally:
        session.close()


def _patch_cli(monkeypatch, return_value: str = _VALID_FANIN):
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
    def test_writes_content_directly_to_fanin_node(self, shared_session_factory, monkeypatch):
        project_id, comp_id, fanin_id = _seed_fanned_out_domain_comp(shared_session_factory)
        _patch_cli(monkeypatch)
        asyncio.run(generate_fanin({"project_id": project_id, "owner_comp_id": comp_id}))

        session = shared_session_factory()
        try:
            fanin = session.get(Node, fanin_id)
            assert fanin is not None
            assert fanin.content == _VALID_FANIN
        finally:
            session.close()

    def test_no_draft_row_created(self, shared_session_factory, monkeypatch):
        project_id, comp_id, _ = _seed_fanned_out_domain_comp(shared_session_factory)
        _patch_cli(monkeypatch)
        asyncio.run(generate_fanin({"project_id": project_id, "owner_comp_id": comp_id}))

        session = shared_session_factory()
        try:
            drafts = list(
                session.execute(select(Draft).where(Draft.project_id == project_id)).scalars()
            )
            assert drafts == []
        finally:
            session.close()

    def test_records_telemetry_with_fanin_section(self, shared_session_factory, monkeypatch):
        project_id, comp_id, fanin_id = _seed_fanned_out_domain_comp(shared_session_factory)
        _patch_cli(monkeypatch)
        asyncio.run(generate_fanin({"project_id": project_id, "owner_comp_id": comp_id}))

        session = shared_session_factory()
        try:
            rows = list(
                session.execute(
                    select(GenerationTelemetry).where(
                        GenerationTelemetry.project_id == project_id,
                        GenerationTelemetry.node_id == fanin_id,
                    )
                ).scalars()
            )
            assert len(rows) >= 1
            for row in rows:
                assert row.section == "fanin"
        finally:
            session.close()


class TestOverwrite:
    def test_re_invocation_overwrites_existing_content(self, shared_session_factory, monkeypatch):
        project_id, comp_id, fanin_id = _seed_fanned_out_domain_comp(shared_session_factory)

        first_output = (
            "<fanin>"
            "<summary>First.</summary>"
            "<exposed-surface>E1.</exposed-surface>"
            "<realized-behavior>R1.</realized-behavior>"
            "</fanin>"
        )
        second_output = (
            "<fanin>"
            "<summary>Second.</summary>"
            "<exposed-surface>E2.</exposed-surface>"
            "<realized-behavior>R2.</realized-behavior>"
            "</fanin>"
        )
        _patch_cli(monkeypatch, return_value=first_output)
        asyncio.run(generate_fanin({"project_id": project_id, "owner_comp_id": comp_id}))

        _patch_cli(monkeypatch, return_value=second_output)
        asyncio.run(generate_fanin({"project_id": project_id, "owner_comp_id": comp_id}))

        session = shared_session_factory()
        try:
            fanin = session.get(Node, fanin_id)
            assert fanin.content == second_output
        finally:
            session.close()


class TestParseRetry:
    def test_one_bad_then_good_succeeds(self, shared_session_factory, monkeypatch):
        project_id, comp_id, fanin_id = _seed_fanned_out_domain_comp(shared_session_factory)
        _patch_cli_sequence(
            monkeypatch,
            [_INVALID_FANIN_WRONG_ORDER, _VALID_FANIN],
        )
        asyncio.run(generate_fanin({"project_id": project_id, "owner_comp_id": comp_id}))

        session = shared_session_factory()
        try:
            fanin = session.get(Node, fanin_id)
            assert fanin.content == _VALID_FANIN
        finally:
            session.close()

    def test_exhausted_retries_raises(self, shared_session_factory, monkeypatch):
        project_id, comp_id, _ = _seed_fanned_out_domain_comp(shared_session_factory)
        import backend.graph.handlers.feature_expansion as _fe_mod
        from backend.cli.manager import GenerationResult

        async def always_bad(**kwargs):
            return GenerationResult(
                text=_INVALID_FANIN_WRONG_ORDER,
                prompt_tokens=1,
                completion_tokens=1,
                model="claude-sonnet-4-6",
            )

        monkeypatch.setattr(_fe_mod.cli_manager, "generate_with_usage", always_bad)
        with pytest.raises(FanInParseRetryExhausted):
            asyncio.run(generate_fanin({"project_id": project_id, "owner_comp_id": comp_id}))


class TestPreconditions:
    def test_missing_fanin_shell_raises(self, shared_session_factory, monkeypatch):
        # Seed the comp but NOT its fanin shell.
        session: Session = shared_session_factory()
        try:
            project_id = str(uuid.uuid4())
            session.add(Project(id=project_id, name="T", git_repo_path="/tmp/t"))
            session.flush()
            comp_id = mint(session, Kind.COMP)
            append_event(
                session,
                project_id,
                ev.NodeCreated(
                    node_id=comp_id,
                    tier="comp",
                    kind="domain",
                    parent_id=None,
                    name="X",
                    content="<comparch>ok</comparch>",
                ),
            )
            session.commit()
        finally:
            session.close()

        _patch_cli(monkeypatch)
        with pytest.raises(FanInHandlerError, match="has no fanin_"):
            asyncio.run(generate_fanin({"project_id": project_id, "owner_comp_id": comp_id}))

    def test_missing_payload_keys_raise(self, shared_session_factory):
        with pytest.raises(FanInHandlerError, match="project_id"):
            asyncio.run(generate_fanin({"owner_comp_id": "comp_x"}))

        with pytest.raises(FanInHandlerError, match="owner_comp_id"):
            asyncio.run(generate_fanin({"project_id": "p1"}))

    def test_non_comp_owner_raises(self, shared_session_factory, monkeypatch):
        session: Session = shared_session_factory()
        try:
            project_id = str(uuid.uuid4())
            session.add(Project(id=project_id, name="T", git_repo_path="/tmp/t"))
            session.flush()
            feat_id = mint(session, Kind.FEAT)
            append_event(
                session,
                project_id,
                ev.NodeCreated(
                    node_id=feat_id,
                    tier="feat",
                    kind="domain",
                    parent_id=None,
                    name="Bogus",
                ),
            )
            session.commit()
        finally:
            session.close()

        _patch_cli(monkeypatch)
        with pytest.raises(FanInHandlerError, match="is not a comp_"):
            asyncio.run(generate_fanin({"project_id": project_id, "owner_comp_id": feat_id}))


class TestPromptInputs:
    def test_prompt_includes_sub_pubapis_and_impls(self, shared_session_factory, monkeypatch):
        project_id, comp_id, _ = _seed_fanned_out_domain_comp(shared_session_factory)

        # Seed pubapi fragments for both subs so the prompt has
        # real content.
        session: Session = shared_session_factory()
        try:
            from backend.graph.fragments import FragmentKind, fragment_id

            subs = list(
                session.execute(
                    select(Node).where(
                        Node.project_id == project_id,
                        Node.tier == "comp",
                        Node.parent_id == comp_id,
                    )
                ).scalars()
            )
            for sub in subs:
                append_event(
                    session,
                    project_id,
                    ev.FragmentUpdated(
                        fragment_id=fragment_id(sub.id, FragmentKind.PUBAPI),
                        owner_id=sub.id,
                        fragment_kind=FragmentKind.PUBAPI,
                        new_content=f"<public-surface>{sub.name} PUBAPI</public-surface>",
                    ),
                )
            session.commit()
        finally:
            session.close()

        calls = _patch_cli(monkeypatch)
        asyncio.run(generate_fanin({"project_id": project_id, "owner_comp_id": comp_id}))
        assert len(calls) == 1
        prompt = calls[0]["prompt"]
        # Both subs' pubapi and impl sections should appear.
        assert "SubA PUBAPI" in prompt
        assert "SubB PUBAPI" in prompt
        assert "SubA B" in prompt  # behavior content
        assert "SubB B" in prompt
