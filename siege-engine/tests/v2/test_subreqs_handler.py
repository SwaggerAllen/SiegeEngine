"""Tests for backend.graph.handlers.subreqs_generation and
backend.graph.handlers.subreqs_mint.

Per-component shape: each test seeds a project with a sysarch-
level component (via direct NodeCreated + FragmentUpdated events)
plus its assigned top-level resps (via decomposition edges),
then exercises the generation or mint handler scoped to that
component.
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
from backend.graph.handlers.subreqs_generation import (
    SubreqsHandlerError,
    SubreqsParseRetryExhausted,
    generate_subreqs,
)
from backend.graph.handlers.subreqs_mint import (
    SubreqsMintHandlerError,
    mint_subreqs,
)
from backend.graph.ids import Kind, mint
from backend.graph.reducer import append_event
from backend.graph.subrequirements import bootstrap_subreqs_node
from backend.models import Project
from backend.models.node import Draft, Edge, Node


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
    import backend.graph.handlers.subreqs_generation as _gen_mod
    import backend.graph.handlers.subreqs_mint as _mint_mod

    monkeypatch.setattr(_database_mod, "SessionLocal", factory)
    monkeypatch.setattr(_gen_mod, "SessionLocal", factory)
    monkeypatch.setattr(_mint_mod, "SessionLocal", factory)
    yield factory
    engine.dispose()


def _seed_component(
    session: Session,
    project_id: str,
    comp_name: str,
    role: str,
    api_intent: str,
    parent_resp_ids: list[str],
) -> str:
    """Create a comp_*, its techspec + pubapi fragments, resp→comp
    decomposition edges for the parent resps, and a bootstrapped
    subreqs_* node. Returns the comp_id.

    Caller must have already minted the parent resp_* nodes.
    """
    comp_id = mint(session, Kind.COMP)
    append_event(
        session,
        project_id,
        ev.NodeCreated(
            node_id=comp_id,
            tier="comp",
            kind="domain",
            parent_id=None,
            name=comp_name,
            display_order=0,
            content="",
        ),
    )
    append_event(
        session,
        project_id,
        ev.FragmentUpdated(
            fragment_id=fragment_id(comp_id, FragmentKind.TECHSPEC),
            owner_id=comp_id,
            fragment_kind=FragmentKind.TECHSPEC,
            new_content=role,
        ),
    )
    append_event(
        session,
        project_id,
        ev.FragmentUpdated(
            fragment_id=fragment_id(comp_id, FragmentKind.PUBAPI),
            owner_id=comp_id,
            fragment_kind=FragmentKind.PUBAPI,
            new_content=api_intent,
        ),
    )
    for parent_id in parent_resp_ids:
        edge_id = mint(session, Kind.EDGE)
        append_event(
            session,
            project_id,
            ev.EdgeCreated(
                edge_id=edge_id,
                edge_type="decomposition",
                source_id=parent_id,
                target_id=comp_id,
            ),
        )
    bootstrap_subreqs_node(session, project_id, comp_id)
    return comp_id


def _seed_top_level_resp(session: Session, project_id: str, name: str, order: int) -> str:
    resp_id = mint(session, Kind.RESP)
    append_event(
        session,
        project_id,
        ev.NodeCreated(
            node_id=resp_id,
            tier="resp",
            kind="domain",
            parent_id=None,
            name=name,
            display_order=order,
            content=f"{name} intent.",
        ),
    )
    return resp_id


@pytest.fixture()
def seeded(shared_session_factory):
    """A project + two top-level resps + one component with both resps assigned.

    Returns a dict with ``project_id``, ``comp_id``, and ``parent_ids``.
    """
    factory = shared_session_factory
    s: Session = factory()
    try:
        project_id = str(uuid.uuid4())
        s.add(Project(id=project_id, name="T", git_repo_path="/tmp/t"))
        s.flush()
        parent_a = _seed_top_level_resp(s, project_id, "Payment Collection", 0)
        parent_b = _seed_top_level_resp(s, project_id, "Invoicing", 1)
        comp_id = _seed_component(
            s,
            project_id,
            comp_name="Billing Service",
            role="Handle payment collection and invoicing.",
            api_intent="get_billing_state(id); record_payment(id).",
            parent_resp_ids=[parent_a, parent_b],
        )
        s.commit()
        yield {"project_id": project_id, "comp_id": comp_id, "parent_ids": [parent_a, parent_b]}
    finally:
        s.close()


def _derived(*ids: str) -> str:
    return "<derived-from>" + "".join(f'<resp id="{rid}"/>' for rid in ids) + "</derived-from>"


def _valid_subreqs(parent_ids: list[str]) -> str:
    """Two subresps, one per parent, for a clean happy-path fixture."""
    return (
        "<subrequirements>"
        "<subresponsibility>"
        "<name>Tokenization</name>"
        "<intent>Convert raw cards to opaque tokens.</intent>"
        + _derived(parent_ids[0])
        + "</subresponsibility>"
        "<subresponsibility>"
        "<name>Delivery</name>"
        "<intent>Send invoices to recipients.</intent>"
        + _derived(parent_ids[1])
        + "</subresponsibility>"
        "</subrequirements>"
    )


def _patch_cli(monkeypatch, output: str):
    import backend.graph.handlers.feature_expansion as _fe_handler
    from backend.cli.manager import GenerationResult

    calls: list[dict] = []

    async def fake(**kwargs):
        calls.append(kwargs)
        return GenerationResult(
            text=output, prompt_tokens=100, completion_tokens=50, model="claude-sonnet-4-6"
        )

    monkeypatch.setattr(_fe_handler.cli_manager, "generate_with_usage", fake)
    return calls


def _patch_cli_sequence(monkeypatch, outputs: list[str]):
    import backend.graph.handlers.feature_expansion as _fe_handler
    from backend.cli.manager import GenerationResult

    calls: list[dict] = []
    remaining = list(outputs)

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


# ── Generation handler tests ────────────────────────────────────────


class TestGenerationHappyPath:
    def test_generates_pending_draft(self, shared_session_factory, seeded, monkeypatch):
        xml = _valid_subreqs(seeded["parent_ids"])
        calls = _patch_cli(monkeypatch, xml)
        asyncio.run(
            generate_subreqs(
                {
                    "project_id": seeded["project_id"],
                    "component_id": seeded["comp_id"],
                    "feedback": None,
                }
            )
        )
        assert len(calls) == 1
        prompt = calls[0]["prompt"]
        # Component context
        assert "Billing Service" in prompt
        assert "Handle payment collection" in prompt
        # Parent resp IDs
        for pid in seeded["parent_ids"]:
            assert pid in prompt

        session = shared_session_factory()
        try:
            drafts = list(
                session.execute(
                    select(Draft).where(Draft.project_id == seeded["project_id"])
                ).scalars()
            )
            assert len(drafts) == 1
            assert drafts[0].content == xml
        finally:
            session.close()

    def test_regen_with_feedback(self, shared_session_factory, seeded, monkeypatch):
        first = _valid_subreqs(seeded["parent_ids"])
        _patch_cli(monkeypatch, first)
        asyncio.run(
            generate_subreqs(
                {
                    "project_id": seeded["project_id"],
                    "component_id": seeded["comp_id"],
                    "feedback": None,
                }
            )
        )
        calls = _patch_cli(monkeypatch, _valid_subreqs(seeded["parent_ids"]))
        asyncio.run(
            generate_subreqs(
                {
                    "project_id": seeded["project_id"],
                    "component_id": seeded["comp_id"],
                    "feedback": "Add backoff",
                }
            )
        )
        assert "Add backoff" in calls[0]["prompt"]


class TestGenerationDomainParentContext:
    """Coverage for the domain-parent subresps context block.

    The subreqs generation handler walks ``domain_parent`` edges
    when the owning component is presentational and renders the
    target domain component's already-minted subresps as a
    read-only context block so the LLM can write UI-side subresps
    that align with the domain side.
    """

    def test_domain_context_absent_for_domain_component(
        self, shared_session_factory, seeded, monkeypatch
    ):
        """A domain component (kind=domain) gets no domain-parent context
        block even if the codebase has domain_parent edges pointing
        somewhere."""
        xml = _valid_subreqs(seeded["parent_ids"])
        calls = _patch_cli(monkeypatch, xml)
        asyncio.run(
            generate_subreqs(
                {
                    "project_id": seeded["project_id"],
                    "component_id": seeded["comp_id"],
                    "feedback": None,
                }
            )
        )
        prompt = calls[0]["prompt"]
        assert "# Domain-parent context" not in prompt

    def test_domain_context_populated_for_presentational_with_minted_parent(
        self, shared_session_factory, monkeypatch
    ):
        """A presentational component whose domain parent has already-
        minted subresps gets a context block naming each one."""
        factory = shared_session_factory
        s = factory()
        try:
            project_id = str(uuid.uuid4())
            s.add(Project(id=project_id, name="T", git_repo_path="/tmp/t"))
            s.flush()

            # Two top-level resps: one domain (Payment Processing),
            # one presentational (Payment Form UX). Shape matches
            # what the extended reqs prompt would produce.
            domain_resp = _seed_top_level_resp(s, project_id, "Payment Processing", 0)
            ui_resp = _seed_top_level_resp(s, project_id, "Payment Form UX", 1)

            # Domain component: billing, assigned the domain resp
            billing_id = _seed_component(
                s,
                project_id,
                comp_name="Billing Service",
                role="Handle payment collection.",
                api_intent="get_billing_state(id).",
                parent_resp_ids=[domain_resp],
            )

            # Presentational component: billing_ui, assigned the UI resp
            billing_ui_id = _seed_component(
                s,
                project_id,
                comp_name="BillingUI",
                role="Render the payment dashboard.",
                api_intent="Dashboard view.",
                parent_resp_ids=[ui_resp],
            )
            # Mark billing_ui as presentational by updating its row
            from backend.models.node import Node as _Node

            billing_ui_row = s.get(_Node, billing_ui_id)
            assert billing_ui_row is not None
            billing_ui_row.kind = "presentational"

            # Domain-parent edge: billing_ui -> billing
            edge_id = mint(s, Kind.EDGE)
            append_event(
                s,
                project_id,
                ev.EdgeCreated(
                    edge_id=edge_id,
                    edge_type="domain_parent",
                    source_id=billing_ui_id,
                    target_id=billing_id,
                ),
            )

            # Domain parent's subresps (as if subreqs for billing
            # had already been approved and minted)
            tokenization_id = mint(s, Kind.RESP)
            append_event(
                s,
                project_id,
                ev.NodeCreated(
                    node_id=tokenization_id,
                    tier="resp",
                    kind="domain",
                    parent_id=billing_id,
                    name="Card Tokenization",
                    display_order=0,
                    content="Convert raw cards to opaque tokens at entry.",
                ),
            )
            retry_id = mint(s, Kind.RESP)
            append_event(
                s,
                project_id,
                ev.NodeCreated(
                    node_id=retry_id,
                    tier="resp",
                    kind="domain",
                    parent_id=billing_id,
                    name="Retry Scheduling",
                    display_order=1,
                    content="Backoff retries on payment failure.",
                ),
            )

            s.commit()
        finally:
            s.close()

        # Generate subreqs on the presentational component
        ui_subreqs = (
            "<subrequirements>"
            "<subresponsibility>"
            "<name>Card Input Rendering</name>"
            "<intent>Render the card input form.</intent>"
            + _derived(ui_resp)
            + "</subresponsibility>"
            "</subrequirements>"
        )
        calls = _patch_cli(monkeypatch, ui_subreqs)
        asyncio.run(
            generate_subreqs(
                {
                    "project_id": project_id,
                    "component_id": billing_ui_id,
                    "feedback": None,
                }
            )
        )

        prompt = calls[0]["prompt"]
        # The domain-parent context block is present
        assert "# Domain-parent context" in prompt
        # The domain parent component is named
        assert "## Billing Service" in prompt
        # Both domain subresps appear with their IDs
        assert tokenization_id in prompt
        assert "Card Tokenization" in prompt
        assert retry_id in prompt
        assert "Retry Scheduling" in prompt
        # And the warning-not-to-reference prose is there
        assert "Do not reference" in prompt

    def test_domain_context_absent_when_parent_has_no_subresps(
        self, shared_session_factory, monkeypatch
    ):
        """Presentational component whose domain parent exists but hasn't
        had subreqs approved yet: no context block."""
        factory = shared_session_factory
        s = factory()
        try:
            project_id = str(uuid.uuid4())
            s.add(Project(id=project_id, name="T", git_repo_path="/tmp/t"))
            s.flush()

            domain_resp = _seed_top_level_resp(s, project_id, "Payment Processing", 0)
            ui_resp = _seed_top_level_resp(s, project_id, "Payment Form UX", 1)

            billing_id = _seed_component(
                s,
                project_id,
                comp_name="Billing",
                role="Handle payments.",
                api_intent="get_billing_state(id).",
                parent_resp_ids=[domain_resp],
            )
            billing_ui_id = _seed_component(
                s,
                project_id,
                comp_name="BillingUI",
                role="Render dashboard.",
                api_intent="view.",
                parent_resp_ids=[ui_resp],
            )
            from backend.models.node import Node as _Node

            billing_ui_row = s.get(_Node, billing_ui_id)
            assert billing_ui_row is not None
            billing_ui_row.kind = "presentational"

            edge_id = mint(s, Kind.EDGE)
            append_event(
                s,
                project_id,
                ev.EdgeCreated(
                    edge_id=edge_id,
                    edge_type="domain_parent",
                    source_id=billing_ui_id,
                    target_id=billing_id,
                ),
            )
            # Note: no subresps minted under billing. Context
            # should skip this parent entirely.
            s.commit()
        finally:
            s.close()

        ui_subreqs = (
            "<subrequirements>"
            "<subresponsibility>"
            "<name>Dashboard Render</name>"
            "<intent>Render the dashboard.</intent>" + _derived(ui_resp) + "</subresponsibility>"
            "</subrequirements>"
        )
        calls = _patch_cli(monkeypatch, ui_subreqs)
        asyncio.run(
            generate_subreqs(
                {
                    "project_id": project_id,
                    "component_id": billing_ui_id,
                    "feedback": None,
                }
            )
        )

        prompt = calls[0]["prompt"]
        # No context block — the parent exists but has nothing to show
        assert "# Domain-parent context" not in prompt
        # The presentational component is still prompted normally
        assert "BillingUI" in prompt


class TestGenerationFailureModes:
    def test_missing_project_id_raises(self, shared_session_factory):
        with pytest.raises(SubreqsHandlerError, match="project_id"):
            asyncio.run(generate_subreqs({}))

    def test_missing_component_id_raises(self, shared_session_factory):
        with pytest.raises(SubreqsHandlerError, match="component_id"):
            asyncio.run(generate_subreqs({"project_id": "p"}))

    def test_unknown_component_raises(self, shared_session_factory):
        factory = shared_session_factory
        s = factory()
        try:
            pid = str(uuid.uuid4())
            s.add(Project(id=pid, name="T", git_repo_path="/tmp/t"))
            s.commit()
        finally:
            s.close()
        with pytest.raises(SubreqsHandlerError, match="not found"):
            asyncio.run(
                generate_subreqs(
                    {"project_id": pid, "component_id": "comp_nonexist", "feedback": None}
                )
            )


class TestGenerationParseValidate:
    def test_retry_on_cross_component_leak(self, shared_session_factory, seeded, monkeypatch):
        # First attempt references a resp ID that isn't assigned to
        # this component — triggers the leak check.
        bad = (
            "<subrequirements>"
            "<subresponsibility><name>A</name><intent>Ok.</intent>"
            '<derived-from><resp id="resp_strange01"/></derived-from>'
            "</subresponsibility>"
            "</subrequirements>"
        )
        good = _valid_subreqs(seeded["parent_ids"])
        calls = _patch_cli_sequence(monkeypatch, [bad, good])
        asyncio.run(
            generate_subreqs(
                {
                    "project_id": seeded["project_id"],
                    "component_id": seeded["comp_id"],
                    "feedback": None,
                }
            )
        )
        assert len(calls) == 2
        assert "Cross-component leaks" in calls[1]["prompt"]

    def test_retry_exhaustion_raises(self, shared_session_factory, seeded, monkeypatch):
        from backend.graph.handlers.feature_expansion import MAX_PARSE_RETRIES

        _patch_cli_sequence(monkeypatch, ["not xml"] * (MAX_PARSE_RETRIES + 1))
        with pytest.raises(SubreqsParseRetryExhausted):
            asyncio.run(
                generate_subreqs(
                    {
                        "project_id": seeded["project_id"],
                        "component_id": seeded["comp_id"],
                        "feedback": None,
                    }
                )
            )


# ── Mint handler tests ──────────────────────────────────────────────


def _set_subreqs_content(session: Session, comp_id: str, content: str) -> None:
    """Simulate DraftApproved: write content directly to the subreqs node."""
    node = session.execute(
        select(Node).where(Node.tier == "subreqs", Node.parent_id == comp_id)
    ).scalar_one()
    node.content = content
    session.commit()


class TestMintHappyPath:
    def test_mints_subresps_and_edges(self, shared_session_factory, seeded):
        factory = shared_session_factory
        s = factory()
        try:
            _set_subreqs_content(s, seeded["comp_id"], _valid_subreqs(seeded["parent_ids"]))
        finally:
            s.close()

        asyncio.run(
            mint_subreqs({"project_id": seeded["project_id"], "component_id": seeded["comp_id"]})
        )

        s = factory()
        try:
            subresps = list(
                s.execute(
                    select(Node)
                    .where(
                        Node.project_id == seeded["project_id"],
                        Node.tier == "resp",
                        Node.parent_id == seeded["comp_id"],
                    )
                    .order_by(Node.display_order)
                ).scalars()
            )
            assert [r.name for r in subresps] == ["Tokenization", "Delivery"]
            assert all(r.id.startswith("resp_") for r in subresps)

            # Two decomposition edges — one per (parent_id, subresp_id)
            # pairing from the <derived-from> blocks.
            decomp_edges = list(
                s.execute(
                    select(Edge).where(
                        Edge.project_id == seeded["project_id"],
                        Edge.edge_type == "decomposition",
                    )
                ).scalars()
            )
            # Include the original 2 resp→comp edges seeded at fixture time
            subresp_edges = [
                e for e in decomp_edges if any(e.target_id == sr.id for sr in subresps)
            ]
            assert len(subresp_edges) == 2
            pairs = {(e.source_id, e.target_id) for e in subresp_edges}
            assert (seeded["parent_ids"][0], subresps[0].id) in pairs
            assert (seeded["parent_ids"][1], subresps[1].id) in pairs
        finally:
            s.close()


class TestMintIdempotency:
    def test_second_run_skips(self, shared_session_factory, seeded):
        factory = shared_session_factory
        s = factory()
        try:
            _set_subreqs_content(s, seeded["comp_id"], _valid_subreqs(seeded["parent_ids"]))
        finally:
            s.close()

        asyncio.run(
            mint_subreqs({"project_id": seeded["project_id"], "component_id": seeded["comp_id"]})
        )
        asyncio.run(
            mint_subreqs({"project_id": seeded["project_id"], "component_id": seeded["comp_id"]})
        )

        s = factory()
        try:
            subresp_count = len(
                list(
                    s.execute(
                        select(Node).where(
                            Node.project_id == seeded["project_id"],
                            Node.tier == "resp",
                            Node.parent_id == seeded["comp_id"],
                        )
                    ).scalars()
                )
            )
            assert subresp_count == 2  # not 4
        finally:
            s.close()


class TestMintFailureModes:
    def test_missing_project_id_raises(self, shared_session_factory):
        with pytest.raises(SubreqsMintHandlerError, match="project_id"):
            asyncio.run(mint_subreqs({}))

    def test_missing_component_id_raises(self, shared_session_factory):
        with pytest.raises(SubreqsMintHandlerError, match="component_id"):
            asyncio.run(mint_subreqs({"project_id": "p"}))

    def test_unknown_component_raises(self, shared_session_factory):
        factory = shared_session_factory
        s = factory()
        try:
            pid = str(uuid.uuid4())
            s.add(Project(id=pid, name="T", git_repo_path="/tmp/t"))
            s.commit()
        finally:
            s.close()
        with pytest.raises(SubreqsMintHandlerError, match="not found"):
            asyncio.run(mint_subreqs({"project_id": pid, "component_id": "comp_nonexist"}))

    def test_empty_content_raises(self, shared_session_factory, seeded):
        with pytest.raises(SubreqsMintHandlerError, match="empty content"):
            asyncio.run(
                mint_subreqs(
                    {"project_id": seeded["project_id"], "component_id": seeded["comp_id"]}
                )
            )

    def test_malformed_content_raises(self, shared_session_factory, seeded):
        factory = shared_session_factory
        s = factory()
        try:
            _set_subreqs_content(s, seeded["comp_id"], "not xml")
        finally:
            s.close()
        with pytest.raises(SubreqsMintHandlerError, match="could not parse"):
            asyncio.run(
                mint_subreqs(
                    {"project_id": seeded["project_id"], "component_id": seeded["comp_id"]}
                )
            )
