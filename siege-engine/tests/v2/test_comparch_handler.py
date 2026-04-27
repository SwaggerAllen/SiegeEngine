"""Tests for backend.graph.handlers.comparch_generation.

Mirrors test_sysarch_handler.py / test_subreqs_handler.py shape.
The CLI is mocked; the real parse-validate retry loop runs
through the arch doc validator from stage 1.
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
from backend.graph.handlers.comparch_generation import (
    ComparchHandlerError,
    ComparchParseRetryExhausted,
    ComparchPreconditionError,
    generate_comparch,
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
    import backend.graph.handlers.comparch_generation as _handler_mod

    monkeypatch.setattr(_database_mod, "SessionLocal", factory)
    monkeypatch.setattr(_handler_mod, "SessionLocal", factory)
    yield factory
    engine.dispose()


def _seed_feat(session: Session, project_id: str, name: str, order: int) -> str:
    fid = mint(session, Kind.FEAT)
    append_event(
        session,
        project_id,
        ev.NodeCreated(
            node_id=fid,
            tier="feat",
            kind="domain",
            parent_id=None,
            name=name,
            display_order=order,
            content=f"{name}.",
        ),
    )
    return fid


def _seed_top_resp(session: Session, project_id: str, name: str, order: int) -> str:
    rid = mint(session, Kind.RESP)
    append_event(
        session,
        project_id,
        ev.NodeCreated(
            node_id=rid,
            tier="resp",
            kind="domain",
            parent_id=None,
            name=name,
            display_order=order,
            content=f"{name} intent.",
        ),
    )
    return rid


def _seed_comp(
    session: Session,
    project_id: str,
    name: str,
    order: int,
    parent_resp_ids: list[str],
    *,
    techspec: str = "",
    pubapi: str = "",
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
            content="",
        ),
    )
    if techspec:
        append_event(
            session,
            project_id,
            ev.FragmentUpdated(
                fragment_id=fragment_id(cid, FragmentKind.TECHSPEC),
                owner_id=cid,
                fragment_kind=FragmentKind.TECHSPEC,
                new_content=techspec,
            ),
        )
    if pubapi:
        append_event(
            session,
            project_id,
            ev.FragmentUpdated(
                fragment_id=fragment_id(cid, FragmentKind.PUBAPI),
                owner_id=cid,
                fragment_kind=FragmentKind.PUBAPI,
                new_content=pubapi,
            ),
        )
    for pid in parent_resp_ids:
        edge_id = mint(session, Kind.EDGE)
        append_event(
            session,
            project_id,
            ev.EdgeCreated(
                edge_id=edge_id,
                edge_type="decomposition",
                source_id=pid,
                target_id=cid,
            ),
        )
    return cid


def _seed_subresp(
    session: Session, project_id: str, parent_comp: str, name: str, order: int
) -> str:
    sid = mint(session, Kind.RESP)
    append_event(
        session,
        project_id,
        ev.NodeCreated(
            node_id=sid,
            tier="resp",
            kind="domain",
            parent_id=parent_comp,
            name=name,
            display_order=order,
            content=f"{name} intent.",
        ),
    )
    return sid


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


def _approve_subreqs(session: Session, project_id: str, comp_id: str) -> None:
    """Simulate subreqs approval by writing content to the subreqs node."""
    node = session.execute(
        select(Node).where(
            Node.project_id == project_id,
            Node.tier == "subreqs",
            Node.parent_id == comp_id,
        )
    ).scalar_one()
    node.content = "<subrequirements>approved</subrequirements>"
    session.commit()


@pytest.fixture()
def seeded_project(shared_session_factory):
    """Project with features + top-level resps + three components +
    subreqs approved on billing + two subresps under billing.

    Return dict with project_id, comp IDs, subresp IDs.
    """
    factory = shared_session_factory
    s: Session = factory()
    try:
        project_id = str(uuid.uuid4())
        s.add(Project(id=project_id, name="T", git_repo_path="/tmp/t"))
        s.flush()

        feat_pay = _seed_feat(s, project_id, "Accept payments", 0)

        resp_bill = _seed_top_resp(s, project_id, "Billing", 0)
        resp_auth = _seed_top_resp(s, project_id, "Authentication", 1)
        resp_found = _seed_top_resp(s, project_id, "Foundation", 2)

        # feat → resp
        for rid in (resp_bill, resp_found):
            edge_id = mint(s, Kind.EDGE)
            append_event(
                s,
                project_id,
                ev.EdgeCreated(
                    edge_id=edge_id,
                    edge_type="decomposition",
                    source_id=feat_pay,
                    target_id=rid,
                ),
            )

        comp_billing = _seed_comp(
            s,
            project_id,
            "BillingService",
            0,
            [resp_bill],
            techspec="Handles payments.",
            pubapi="get_billing_state(id).",
        )
        comp_auth = _seed_comp(
            s,
            project_id,
            "AuthService",
            1,
            [resp_auth],
            techspec="Identifies callers.",
            pubapi="authenticate(creds).",
        )
        comp_foundation = _seed_comp(
            s,
            project_id,
            "Foundation",
            2,
            [resp_found],
            techspec="Owns project root.",
            pubapi="load_settings().",
        )

        _seed_dep(s, project_id, comp_billing, comp_auth)
        _seed_dep(s, project_id, comp_billing, comp_foundation)
        _seed_dep(s, project_id, comp_auth, comp_foundation)

        sub_token = _seed_subresp(s, project_id, comp_billing, "Tokenization", 0)
        sub_retry = _seed_subresp(s, project_id, comp_billing, "Retry", 1)

        s.commit()
        # Simulate subreqs approval on billing so the precondition passes
        _approve_subreqs(s, project_id, comp_billing)
        yield {
            "project_id": project_id,
            "comp_billing": comp_billing,
            "comp_auth": comp_auth,
            "comp_foundation": comp_foundation,
            "sub_token": sub_token,
            "sub_retry": sub_retry,
            "resp_bill": resp_bill,
        }
    finally:
        s.close()


def _sub_xml(
    alias: str,
    name: str,
    resp_ids: tuple[str, ...],
    *,
    foundation: bool = False,
) -> str:
    """Render a ``<subcomponent>`` in the micro-field grammar."""
    resp_xml = "".join(f'<resp id="{rid}"/>' for rid in resp_ids)
    foundation_marker = "<foundation/>" if foundation else ""
    return (
        f'<subcomponent alias="{alias}">'
        f"<name>{name}</name>"
        f"<purpose>Owns {name} territory.</purpose>"
        f"<owned-invariants>"
        f"<invariant>{name} holds state</invariant>"
        f"<invariant>{name} is journaled</invariant>"
        f"</owned-invariants>"
        f"<primary-operations>"
        f"<operation>read {name}</operation>"
        f"<operation>mutate {name}</operation>"
        f"<operation>emit {name}</operation>"
        f"</primary-operations>"
        f"<responsibilities>{resp_xml}</responsibilities>"
        f"{foundation_marker}"
        "</subcomponent>"
    )


def _valid_comparch_simple(sub_ids: list[str], sibling_comp_ids: list[str]) -> str:
    """A simpler valid comparch with 2 subs (one foundation) covering 2 subresps."""
    sibling_dep = f'<dep to="{sibling_comp_ids[0]}"/>' if sibling_comp_ids else ""
    return (
        "<comparch>"
        "<technical-specification>Python + PostgreSQL. FastAPI.</technical-specification>"
        "<public-surface>get_billing_state(id); record_payment().</public-surface>"
        "<private-surface>Internal helpers.</private-surface>"
        "<failure-surface>billing corruption silently double-charges cards.</failure-surface>"
        "<policies></policies>"
        f"<dependencies>{sibling_dep}</dependencies>"
        "<subcomponents>"
        + _sub_xml("token_store", "TokenStore", (sub_ids[0],))
        + _sub_xml("foundation", "Foundation", (sub_ids[1],), foundation=True)
        + "</subcomponents>"
        "<sub-dependencies>"
        '<dep from="token_store" to="foundation"/>'
        "</sub-dependencies>"
        "</comparch>"
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
        draft_xml = _valid_comparch_simple(
            [seeded_project["sub_token"], seeded_project["sub_retry"]],
            [seeded_project["comp_auth"]],
        )
        calls = _patch_cli(monkeypatch, draft_xml)
        asyncio.run(
            generate_comparch(
                {
                    "project_id": seeded_project["project_id"],
                    "component_id": seeded_project["comp_billing"],
                    "feedback": None,
                }
            )
        )
        assert len(calls) == 1
        prompt = calls[0]["prompt"]
        # Context includes component name + subresp IDs + sibling IDs
        assert "BillingService" in prompt
        assert seeded_project["sub_token"] in prompt
        assert seeded_project["comp_auth"] in prompt

        session = shared_session_factory()
        try:
            drafts = list(
                session.execute(
                    select(Draft).where(Draft.project_id == seeded_project["project_id"])
                ).scalars()
            )
            assert len(drafts) == 1
            assert drafts[0].status == "pending"
            assert drafts[0].target_id == seeded_project["comp_billing"]
            assert drafts[0].content == draft_xml
        finally:
            session.close()

    def test_regen_with_feedback_discards_prior(
        self, shared_session_factory, seeded_project, monkeypatch
    ):
        first = _valid_comparch_simple(
            [seeded_project["sub_token"], seeded_project["sub_retry"]],
            [seeded_project["comp_auth"]],
        )
        _patch_cli(monkeypatch, first)
        asyncio.run(
            generate_comparch(
                {
                    "project_id": seeded_project["project_id"],
                    "component_id": seeded_project["comp_billing"],
                    "feedback": None,
                }
            )
        )
        calls = _patch_cli(monkeypatch, first)
        asyncio.run(
            generate_comparch(
                {
                    "project_id": seeded_project["project_id"],
                    "component_id": seeded_project["comp_billing"],
                    "feedback": "Add async token refresh.",
                }
            )
        )
        assert "Add async token refresh." in calls[0]["prompt"]

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
    def test_subreqs_not_approved_raises(self, shared_session_factory, seeded_project, monkeypatch):
        # Clear the subreqs approval
        s = shared_session_factory()
        try:
            node = s.execute(
                select(Node).where(
                    Node.project_id == seeded_project["project_id"],
                    Node.tier == "subreqs",
                    Node.parent_id == seeded_project["comp_billing"],
                )
            ).scalar_one()
            node.content = ""
            s.commit()
        finally:
            s.close()

        with pytest.raises(ComparchPreconditionError, match="has not been approved"):
            asyncio.run(
                generate_comparch(
                    {
                        "project_id": seeded_project["project_id"],
                        "component_id": seeded_project["comp_billing"],
                        "feedback": None,
                    }
                )
            )


class TestFailureModes:
    def test_missing_project_id_raises(self, shared_session_factory):
        with pytest.raises(ComparchHandlerError, match="project_id"):
            asyncio.run(generate_comparch({}))

    def test_missing_component_id_raises(self, shared_session_factory):
        with pytest.raises(ComparchHandlerError, match="component_id"):
            asyncio.run(generate_comparch({"project_id": "p"}))

    def test_unknown_component_raises(self, shared_session_factory, seeded_project):
        with pytest.raises(ComparchHandlerError, match="not found"):
            asyncio.run(
                generate_comparch(
                    {
                        "project_id": seeded_project["project_id"],
                        "component_id": "comp_unknown01",
                        "feedback": None,
                    }
                )
            )

    def test_subcomponent_rejected(self, shared_session_factory, seeded_project):
        # Create a subcomponent with parent_id=billing, try to run
        # comparch on it — should reject because comparch is
        # top-level only.
        s = shared_session_factory()
        try:
            sub_id = mint(s, Kind.COMP)
            append_event(
                s,
                seeded_project["project_id"],
                ev.NodeCreated(
                    node_id=sub_id,
                    tier="comp",
                    kind="domain",
                    parent_id=seeded_project["comp_billing"],
                    name="SubThing",
                    display_order=0,
                    content="",
                ),
            )
            s.commit()
        finally:
            s.close()

        with pytest.raises(ComparchHandlerError, match="subcomponent"):
            asyncio.run(
                generate_comparch(
                    {
                        "project_id": seeded_project["project_id"],
                        "component_id": sub_id,
                        "feedback": None,
                    }
                )
            )


class TestParseValidateRetry:
    def test_retry_on_missing_foundation_subcomponent(
        self, shared_session_factory, seeded_project, monkeypatch
    ):
        good = _valid_comparch_simple(
            [seeded_project["sub_token"], seeded_project["sub_retry"]],
            [seeded_project["comp_auth"]],
        )
        bad = good.replace("<foundation/>", "")
        calls = _patch_cli_sequence(monkeypatch, [bad, good])
        asyncio.run(
            generate_comparch(
                {
                    "project_id": seeded_project["project_id"],
                    "component_id": seeded_project["comp_billing"],
                    "feedback": None,
                }
            )
        )
        assert len(calls) == 2
        assert "no foundation subcomponent" in calls[1]["prompt"]

    def test_retry_on_unknown_subresp(self, shared_session_factory, seeded_project, monkeypatch):
        good = _valid_comparch_simple(
            [seeded_project["sub_token"], seeded_project["sub_retry"]],
            [seeded_project["comp_auth"]],
        )
        bad = good.replace(seeded_project["sub_token"], "resp_mystery01")
        calls = _patch_cli_sequence(monkeypatch, [bad, good])
        asyncio.run(
            generate_comparch(
                {
                    "project_id": seeded_project["project_id"],
                    "component_id": seeded_project["comp_billing"],
                    "feedback": None,
                }
            )
        )
        assert len(calls) == 2
        assert "unknown subresponsibility" in calls[1]["prompt"]

    def test_retry_exhaustion_raises(self, shared_session_factory, seeded_project, monkeypatch):
        from backend.graph.handlers.feature_expansion import MAX_PARSE_RETRIES

        total = MAX_PARSE_RETRIES + 1
        _patch_cli_sequence(monkeypatch, ["not xml"] * total)
        with pytest.raises(ComparchParseRetryExhausted):
            asyncio.run(
                generate_comparch(
                    {
                        "project_id": seeded_project["project_id"],
                        "component_id": seeded_project["comp_billing"],
                        "feedback": None,
                    }
                )
            )


class TestTelemetry:
    def test_records_telemetry_row(self, shared_session_factory, seeded_project, monkeypatch):
        _patch_cli(
            monkeypatch,
            _valid_comparch_simple(
                [seeded_project["sub_token"], seeded_project["sub_retry"]],
                [seeded_project["comp_auth"]],
            ),
        )
        asyncio.run(
            generate_comparch(
                {
                    "project_id": seeded_project["project_id"],
                    "component_id": seeded_project["comp_billing"],
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
            assert rows[0].section == "comparch"
            assert rows[0].node_id == seeded_project["comp_billing"]
        finally:
            session.close()
