"""Tests for backend.graph.handlers.subcomparch_generation.

Mirrors test_comparch_handler.py shape. The CLI is mocked; the
real parse-validate retry loop runs through the sub arch doc
validator from stage 1.
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
from backend.graph.fragments import FragmentKind, fragment_id
from backend.graph.handlers.subcomparch_generation import (
    SubcomparchHandlerError,
    SubcomparchParseRetryExhausted,
    SubcomparchPreconditionError,
    generate_subcomparch,
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
    import backend.graph.handlers.subcomparch_generation as _handler_mod

    monkeypatch.setattr(_database_mod, "SessionLocal", factory)
    monkeypatch.setattr(_handler_mod, "SessionLocal", factory)
    yield factory
    engine.dispose()


def _seed_top_comp(
    session: Session,
    project_id: str,
    name: str,
    order: int,
    *,
    techspec: str,
    pubapi: str,
    privapi: str = "",
    content: str = "",
) -> str:
    cid = mint(session, Kind.COMP)
    append_event(
        session,
        project_id,
        ev.NodeCreated(
            node_id=cid,
            tier="comp",
            kind="domain",
            parent_id=None,
            name=name,
            display_order=order,
            content=content,
        ),
    )
    for kind, body in (
        (FragmentKind.TECHSPEC, techspec),
        (FragmentKind.PUBAPI, pubapi),
        (FragmentKind.PRIVAPI, privapi),
    ):
        if body:
            append_event(
                session,
                project_id,
                ev.FragmentUpdated(
                    fragment_id=fragment_id(cid, kind),
                    owner_id=cid,
                    fragment_kind=kind,
                    new_content=body,
                ),
            )
    return cid


def _seed_sub_comp(
    session: Session,
    project_id: str,
    parent_comp_id: str,
    name: str,
    order: int,
    *,
    techspec: str,
    pubapi: str,
) -> str:
    sub_id = mint(session, Kind.COMP)
    append_event(
        session,
        project_id,
        ev.NodeCreated(
            node_id=sub_id,
            tier="comp",
            kind="domain",
            parent_id=parent_comp_id,
            name=name,
            display_order=order,
            content="",
        ),
    )
    for kind, body in (
        (FragmentKind.TECHSPEC, techspec),
        (FragmentKind.PUBAPI, pubapi),
    ):
        append_event(
            session,
            project_id,
            ev.FragmentUpdated(
                fragment_id=fragment_id(sub_id, kind),
                owner_id=sub_id,
                fragment_kind=kind,
                new_content=body,
            ),
        )
    return sub_id


def _seed_dep(session: Session, project_id: str, src: str, dst: str) -> None:
    edge_id = mint(session, Kind.EDGE)
    append_event(
        session,
        project_id,
        ev.EdgeCreated(
            edge_id=edge_id,
            edge_type="dependency",
            source_id=src,
            target_id=dst,
        ),
    )


@pytest.fixture()
def seeded_project(shared_session_factory):
    """Project with two top-level comps (billing approved, auth
    approved), and two subcomponents under billing."""
    factory = shared_session_factory
    s: Session = factory()
    try:
        project_id = str(uuid.uuid4())
        s.add(Project(id=project_id, name="T", git_repo_path="/tmp/t"))
        s.flush()

        comp_billing = _seed_top_comp(
            s,
            project_id,
            "BillingService",
            0,
            techspec="Handles payments.",
            pubapi="get_billing_state(id).",
            privapi="Internal: _tokenize.",
            content="<comparch>approved</comparch>",
        )
        comp_auth = _seed_top_comp(
            s,
            project_id,
            "AuthService",
            1,
            techspec="Identifies callers.",
            pubapi="authenticate(creds).",
            content="<comparch>approved</comparch>",
        )
        # Billing depends on auth
        _seed_dep(s, project_id, comp_billing, comp_auth)

        sub_store = _seed_sub_comp(
            s,
            project_id,
            comp_billing,
            "TokenStore",
            0,
            techspec="Skeletal: owns card tokenization.",
            pubapi="Skeletal: tokenize(raw).",
        )
        sub_found = _seed_sub_comp(
            s,
            project_id,
            comp_billing,
            "Foundation",
            1,
            techspec="Skeletal: component root + retry scheduler.",
            pubapi="Skeletal: init(); schedule_retry(ctx).",
        )
        s.commit()
        yield {
            "project_id": project_id,
            "comp_billing": comp_billing,
            "comp_auth": comp_auth,
            "sub_store": sub_store,
            "sub_found": sub_found,
        }
    finally:
        s.close()


def _valid_subcomparch(
    *,
    deps: str = "",
) -> str:
    return (
        "<subcomparch>"
        "<technical-specification>Tokenization pipeline for billing's payment flow."
        "</technical-specification>"
        "<public-surface>tokenize(raw) -> Token.</public-surface>"
        "<private-surface>Internal: _rotate_keys(cutoff).</private-surface>"
        f"<dependencies>{deps}</dependencies>"
        "</subcomparch>"
    )


def _patch_cli(monkeypatch, return_value: str):
    import backend.graph.handlers.feature_expansion as _fe_handler
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

    monkeypatch.setattr(_fe_handler.cli_manager, "generate_with_usage", fake)
    return calls


def _patch_cli_sequence(monkeypatch, values: list[str]):
    import backend.graph.handlers.feature_expansion as _fe_handler
    from backend.cli.manager import GenerationResult

    calls: list[dict] = []
    remaining = list(values)

    async def fake(**kwargs):
        calls.append(kwargs)
        if not remaining:
            raise RuntimeError("CLI mock exhausted")
        text = remaining.pop(0)
        return GenerationResult(
            text=text, prompt_tokens=100, completion_tokens=50, model="claude-sonnet-4-6"
        )

    monkeypatch.setattr(_fe_handler.cli_manager, "generate_with_usage", fake)
    return calls


class TestHappyPath:
    def test_generates_pending_draft(self, shared_session_factory, seeded_project, monkeypatch):
        draft_xml = _valid_subcomparch(deps=f'<dep to="{seeded_project["sub_found"]}"/>')
        calls = _patch_cli(monkeypatch, draft_xml)
        asyncio.run(
            generate_subcomparch(
                {
                    "project_id": seeded_project["project_id"],
                    "component_id": seeded_project["sub_store"],
                    "feedback": None,
                }
            )
        )
        assert len(calls) == 1
        prompt = calls[0]["prompt"]
        # Context includes subcomponent name + parent component +
        # sibling real comp_* id and parent's sibling comp id.
        assert "TokenStore" in prompt
        assert "BillingService" in prompt
        assert seeded_project["sub_found"] in prompt  # sibling real id
        assert seeded_project["comp_auth"] in prompt  # parent-sibling id

        session = shared_session_factory()
        try:
            drafts = list(
                session.execute(
                    select(Draft).where(Draft.project_id == seeded_project["project_id"])
                ).scalars()
            )
            assert len(drafts) == 1
            assert drafts[0].status == "pending"
            assert drafts[0].target_id == seeded_project["sub_store"]
            assert drafts[0].content == draft_xml
        finally:
            session.close()

    def test_accepts_mixed_sibling_and_parent_sibling_deps(
        self, shared_session_factory, seeded_project, monkeypatch
    ):
        """A subcomparch doc can list a same-parent sibling and a
        parent's sibling top-level in the same <dependencies>
        section — both use real comp_* IDs."""
        draft_xml = _valid_subcomparch(
            deps=(
                f'<dep to="{seeded_project["comp_auth"]}"/>'
                f'<dep to="{seeded_project["sub_found"]}"/>'
            )
        )
        _patch_cli(monkeypatch, draft_xml)
        asyncio.run(
            generate_subcomparch(
                {
                    "project_id": seeded_project["project_id"],
                    "component_id": seeded_project["sub_store"],
                    "feedback": None,
                }
            )
        )
        session = shared_session_factory()
        try:
            drafts = list(
                session.execute(
                    select(Draft).where(Draft.project_id == seeded_project["project_id"])
                ).scalars()
            )
            assert len(drafts) == 1
            assert drafts[0].status == "pending"
        finally:
            session.close()

    def test_empty_deps_accepted(self, shared_session_factory, seeded_project, monkeypatch):
        """Leaf subcomponent with empty <dependencies> is legal."""
        # Foundation is a leaf — has no deps. Generate for it.
        draft_xml = _valid_subcomparch()
        _patch_cli(monkeypatch, draft_xml)
        asyncio.run(
            generate_subcomparch(
                {
                    "project_id": seeded_project["project_id"],
                    "component_id": seeded_project["sub_found"],
                    "feedback": None,
                }
            )
        )
        session = shared_session_factory()
        try:
            drafts = list(
                session.execute(
                    select(Draft).where(Draft.project_id == seeded_project["project_id"])
                ).scalars()
            )
            assert len(drafts) == 1
            assert drafts[0].target_id == seeded_project["sub_found"]
        finally:
            session.close()

    def test_regen_with_feedback_discards_prior(
        self, shared_session_factory, seeded_project, monkeypatch
    ):
        first = _valid_subcomparch(deps=f'<dep to="{seeded_project["sub_found"]}"/>')
        _patch_cli(monkeypatch, first)
        asyncio.run(
            generate_subcomparch(
                {
                    "project_id": seeded_project["project_id"],
                    "component_id": seeded_project["sub_store"],
                    "feedback": None,
                }
            )
        )
        calls = _patch_cli(monkeypatch, first)
        asyncio.run(
            generate_subcomparch(
                {
                    "project_id": seeded_project["project_id"],
                    "component_id": seeded_project["sub_store"],
                    "feedback": "Tighten the rotation cadence.",
                }
            )
        )
        assert "Tighten the rotation cadence." in calls[0]["prompt"]

        session = shared_session_factory()
        try:
            drafts = list(
                session.execute(
                    select(Draft)
                    .where(Draft.project_id == seeded_project["project_id"])
                    .order_by(Draft.created_at.asc())
                ).scalars()
            )
            assert len(drafts) == 2
            statuses = [d.status for d in drafts]
            assert statuses.count("pending") == 1
            assert statuses.count("discarded") == 1
        finally:
            session.close()


class TestPrecondition:
    def test_parent_unapproved_raises(self, shared_session_factory, seeded_project, monkeypatch):
        # Clear the parent comparch approval
        s = shared_session_factory()
        try:
            parent = s.get(Node, seeded_project["comp_billing"])
            parent.content = ""
            s.commit()
        finally:
            s.close()

        with pytest.raises(SubcomparchPreconditionError, match="no approved comparch content"):
            asyncio.run(
                generate_subcomparch(
                    {
                        "project_id": seeded_project["project_id"],
                        "component_id": seeded_project["sub_store"],
                        "feedback": None,
                    }
                )
            )


class TestFailureModes:
    def test_missing_project_id_raises(self, shared_session_factory):
        with pytest.raises(SubcomparchHandlerError, match="project_id"):
            asyncio.run(generate_subcomparch({}))

    def test_missing_component_id_raises(self, shared_session_factory):
        with pytest.raises(SubcomparchHandlerError, match="component_id"):
            asyncio.run(generate_subcomparch({"project_id": "p"}))

    def test_unknown_component_raises(self, shared_session_factory, seeded_project):
        with pytest.raises(SubcomparchHandlerError, match="not found"):
            asyncio.run(
                generate_subcomparch(
                    {
                        "project_id": seeded_project["project_id"],
                        "component_id": "comp_unknown01",
                        "feedback": None,
                    }
                )
            )

    def test_top_level_comp_rejected(self, shared_session_factory, seeded_project):
        """A top-level comp is a comparch target, not subcomparch."""
        with pytest.raises(SubcomparchHandlerError, match="top-level component"):
            asyncio.run(
                generate_subcomparch(
                    {
                        "project_id": seeded_project["project_id"],
                        "component_id": seeded_project["comp_billing"],
                        "feedback": None,
                    }
                )
            )


class TestParseValidateRetry:
    def test_retry_on_unknown_sibling_id(self, shared_session_factory, seeded_project, monkeypatch):
        """First attempt targets an unknown sibling comp_ id; second attempt succeeds."""
        bad = _valid_subcomparch(deps='<dep to="comp_mystery1"/>')
        good = _valid_subcomparch(deps=f'<dep to="{seeded_project["sub_found"]}"/>')
        calls = _patch_cli_sequence(monkeypatch, [bad, good])
        asyncio.run(
            generate_subcomparch(
                {
                    "project_id": seeded_project["project_id"],
                    "component_id": seeded_project["sub_store"],
                    "feedback": None,
                }
            )
        )
        assert len(calls) == 2
        # The second call's prompt carries the parse error feedback
        assert "not in the allowed set" in calls[1]["prompt"]

    def test_retry_on_non_comp_prefix(self, shared_session_factory, seeded_project, monkeypatch):
        """Legacy alias-style targets are rejected with a clear error."""
        bad = _valid_subcomparch(deps='<dep to="mystery_sib"/>')
        good = _valid_subcomparch(deps=f'<dep to="{seeded_project["sub_found"]}"/>')
        calls = _patch_cli_sequence(monkeypatch, [bad, good])
        asyncio.run(
            generate_subcomparch(
                {
                    "project_id": seeded_project["project_id"],
                    "component_id": seeded_project["sub_store"],
                    "feedback": None,
                }
            )
        )
        assert len(calls) == 2
        assert "not a comp_* ID" in calls[1]["prompt"]

    def test_retry_on_unknown_parent_sibling_id(
        self, shared_session_factory, seeded_project, monkeypatch
    ):
        bad = _valid_subcomparch(deps='<dep to="comp_strange01"/>')
        good = _valid_subcomparch(deps=f'<dep to="{seeded_project["comp_auth"]}"/>')
        calls = _patch_cli_sequence(monkeypatch, [bad, good])
        asyncio.run(
            generate_subcomparch(
                {
                    "project_id": seeded_project["project_id"],
                    "component_id": seeded_project["sub_store"],
                    "feedback": None,
                }
            )
        )
        assert len(calls) == 2

    def test_exhausts_on_persistent_parse_error(
        self, shared_session_factory, seeded_project, monkeypatch
    ):
        bad = "<not-subcomparch/>"
        _patch_cli(monkeypatch, bad)
        with pytest.raises(SubcomparchParseRetryExhausted):
            asyncio.run(
                generate_subcomparch(
                    {
                        "project_id": seeded_project["project_id"],
                        "component_id": seeded_project["sub_store"],
                        "feedback": None,
                    }
                )
            )


class TestTelemetry:
    def test_telemetry_row_written_per_attempt(
        self, shared_session_factory, seeded_project, monkeypatch
    ):
        draft_xml = _valid_subcomparch(deps=f'<dep to="{seeded_project["sub_found"]}"/>')
        _patch_cli(monkeypatch, draft_xml)
        asyncio.run(
            generate_subcomparch(
                {
                    "project_id": seeded_project["project_id"],
                    "component_id": seeded_project["sub_store"],
                    "feedback": None,
                }
            )
        )
        session = shared_session_factory()
        try:
            rows = list(
                session.execute(
                    select(GenerationTelemetry).where(
                        GenerationTelemetry.project_id == seeded_project["project_id"]
                    )
                ).scalars()
            )
            assert len(rows) == 1
            assert rows[0].section == "subcomparch"
            assert rows[0].node_id == seeded_project["sub_store"]
        finally:
            session.close()
