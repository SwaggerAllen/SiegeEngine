"""Tests for backend.graph.handlers.sysarch_generation.

Mirrors test_requirements_handler.py's shape. The CLI is mocked;
the real generation loop runs through the shared parse-validate
retry helper and the actual validator, so these tests exercise
the full handler wiring end to end (short of the mint step,
which is a separate handler).
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
from backend.graph.handlers.sysarch_generation import (
    SysarchHandlerError,
    SysarchParseRetryExhausted,
    generate_sysarch,
)
from backend.graph.reducer import append_event
from backend.graph.sysarch import bootstrap_sysarch_node
from backend.models import InputDocument, Project
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
    import backend.graph.handlers.sysarch_generation as _handler_mod

    monkeypatch.setattr(_database_mod, "SessionLocal", factory)
    monkeypatch.setattr(_handler_mod, "SessionLocal", factory)
    yield factory
    engine.dispose()


def _mint_feature(session: Session, project_id: str, name: str, order: int) -> str:
    from backend.graph.ids import Kind, mint

    feat_id = mint(session, Kind.FEAT)
    append_event(
        session,
        project_id,
        ev.NodeCreated(
            node_id=feat_id,
            tier="feat",
            kind="domain",
            parent_id=None,
            name=name,
            display_order=order,
            content=f"{name} intent.",
        ),
    )
    return feat_id


def _mint_top_level_resp(
    session: Session, project_id: str, name: str, intent: str, order: int
) -> str:
    from backend.graph.ids import Kind, mint

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
            content=intent,
        ),
    )
    return resp_id


@pytest.fixture()
def seeded_project(shared_session_factory):
    """Project with features + top-level resps + sysarch bootstrap node.

    Returns just the project_id as a string; use ``seeded_resp_ids``
    to look up the minted resps in happy-path tests.
    """
    factory = shared_session_factory
    session: Session = factory()
    try:
        project_id = str(uuid.uuid4())
        session.add(Project(id=project_id, name="T", git_repo_path="/tmp/t"))
        session.flush()
        session.add(
            InputDocument(
                project_id=project_id,
                name="Project Document",
                content="A task tracker.",
                doc_type="project_doc",
            )
        )
        _mint_feature(session, project_id, "Billing", 0)
        _mint_feature(session, project_id, "Auth", 1)
        _mint_top_level_resp(session, project_id, "Authentication", "Identify callers.", 0)
        _mint_top_level_resp(session, project_id, "BillingService", "Handle payments.", 1)
        _mint_top_level_resp(
            session, project_id, "Foundation", "Project root and shared utilities.", 2
        )
        bootstrap_sysarch_node(session, project_id)
        session.commit()
        yield project_id
    finally:
        session.close()


@pytest.fixture()
def seeded_resp_ids(shared_session_factory, seeded_project) -> list[str]:
    """Top-level resp IDs seeded into ``seeded_project``, display order."""
    factory = shared_session_factory
    s: Session = factory()
    try:
        return [
            rid
            for (rid,) in s.execute(
                select(Node.id)
                .where(
                    Node.project_id == seeded_project,
                    Node.tier == "resp",
                    Node.parent_id.is_(None),
                )
                .order_by(Node.display_order)
            ).all()
        ]
    finally:
        s.close()


def _valid_sysarch(resp_ids: list[str]) -> str:
    """Build a valid <sysarch> block that assigns every seeded resp.

    Three components matching the three seeded resps; foundation on
    the third. Deterministic so retry-prompt tests can inspect it.

    Phase-11 followup B4 made ``<introduction>`` a required sibling
    block; this helper prepends a stub intro.
    """
    auth_id, billing_id, foundation_id = resp_ids
    return (
        "<introduction>Stub intro for sysarch handler tests.</introduction>"
        "<sysarch>"
        + _TECHSPEC_STUB
        + "<components>"
        + _comp_xml("auth", "Authentication", "Identify callers.", (auth_id,))
        + _comp_xml("billing", "Billing Service", "Handle payments.", (billing_id,))
        + _comp_xml(
            "foundation",
            "Foundation",
            "Own project root.",
            (foundation_id,),
            foundation=True,
        )
        + "</components>"
        "<policies></policies>"
        "<dependencies>"
        '<dep from="billing" to="foundation"/>'
        '<dep from="auth" to="foundation"/>'
        "</dependencies>"
        "<domain-parent></domain-parent>"
        "</sysarch>"
    )


# Shared stubs for the post-Phase-13 micro-field sysarch grammar.
# Kept at module scope so ``_make_valid_sysarch_xml`` and any ad-hoc
# fixture assembly in this file can reach them.
_TECHSPEC_STUB = (
    "<techspec>"
    "<runtime>Python 3.11 FastAPI async loop.</runtime>"
    "<persistence>PostgreSQL via SQLAlchemy.</persistence>"
    "<write-path>Event-sourced reducer; no direct ORM writes.</write-path>"
    "<concurrency>Async handlers + worker pool.</concurrency>"
    "<testing>pytest with an integration drain harness.</testing>"
    "<deploy>Docker on Fly.io with a Postgres sidecar.</deploy>"
    "<technologies>FastAPI, SQLAlchemy, PostgreSQL.</technologies>"
    "</techspec>"
)


def _comp_xml(
    alias: str,
    name: str,
    purpose: str,
    resp_ids: tuple[str, ...],
    *,
    foundation: bool = False,
) -> str:
    """Render a ``<component>`` in the micro-field grammar."""
    resp_xml = "".join(f'<resp id="{rid}"/>' for rid in resp_ids)
    foundation_marker = "<foundation/>" if foundation else ""
    return (
        f'<component alias="{alias}">'
        f"<name>{name}</name>"
        f"<kind>domain</kind>"
        f"<purpose>{purpose}</purpose>"
        f"<owned-invariants>"
        f"<invariant>{alias} owns state A</invariant>"
        f"<invariant>{alias} owns state B</invariant>"
        f"</owned-invariants>"
        f"<primary-operations>"
        f"<operation>do {alias} thing one</operation>"
        f"<operation>do {alias} thing two</operation>"
        f"<operation>do {alias} thing three</operation>"
        f"</primary-operations>"
        f"<responsibilities>{resp_xml}</responsibilities>"
        f"{foundation_marker}"
        "</component>"
    )


def _patch_cli(monkeypatch, return_value: str, **kw):
    import backend.graph.handlers.feature_expansion as _fe_handler
    from backend.cli.manager import GenerationResult

    calls: list[dict] = []

    async def fake(**kwargs):
        calls.append(kwargs)
        return GenerationResult(
            text=return_value,
            prompt_tokens=kw.get("prompt_tokens", 100),
            completion_tokens=kw.get("completion_tokens", 50),
            model=kw.get("model", "claude-sonnet-4-6"),
        )

    monkeypatch.setattr(_fe_handler.cli_manager, "generate_with_usage", fake)
    return calls


def _patch_cli_sequence(monkeypatch, return_values: list[str]):
    import backend.graph.handlers.feature_expansion as _fe_handler
    from backend.cli.manager import GenerationResult

    calls: list[dict] = []
    remaining = list(return_values)

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
    def test_generates_pending_draft(
        self, shared_session_factory, seeded_project, seeded_resp_ids, monkeypatch
    ):
        draft_xml = _valid_sysarch(seeded_resp_ids)
        calls = _patch_cli(monkeypatch, draft_xml)
        asyncio.run(generate_sysarch({"project_id": seeded_project, "feedback": None}))

        assert len(calls) == 1
        prompt = calls[0]["prompt"]
        # Resp IDs must appear in the prompt so the LLM echoes them
        for rid in seeded_resp_ids:
            assert rid in prompt
        # Features summary rendered in the prompt for context
        assert "Billing" in prompt
        assert "Auth" in prompt

        session = shared_session_factory()
        try:
            drafts = list(
                session.execute(select(Draft).where(Draft.project_id == seeded_project)).scalars()
            )
            assert len(drafts) == 1
            assert drafts[0].status == "pending"
            assert drafts[0].content == draft_xml
        finally:
            session.close()

    def test_regeneration_discards_old_pending(
        self, shared_session_factory, seeded_project, seeded_resp_ids, monkeypatch
    ):
        first = _valid_sysarch(seeded_resp_ids)
        second = _valid_sysarch(seeded_resp_ids).replace("A typical Python", "A revised Python")

        _patch_cli(monkeypatch, first)
        asyncio.run(generate_sysarch({"project_id": seeded_project, "feedback": None}))

        _patch_cli(monkeypatch, second)
        asyncio.run(generate_sysarch({"project_id": seeded_project, "feedback": "tighten scope"}))

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
            pending = next(d for d in drafts if d.status == "pending")
            assert pending.content == second
        finally:
            session.close()


class TestFailureModes:
    def test_missing_project_id_raises(self, shared_session_factory):
        with pytest.raises(SysarchHandlerError, match="project_id"):
            asyncio.run(generate_sysarch({}))

    def test_missing_sysarch_node_raises(self, shared_session_factory):
        factory = shared_session_factory
        s = factory()
        try:
            pid = str(uuid.uuid4())
            s.add(Project(id=pid, name="T2", git_repo_path="/tmp/t2"))
            s.commit()
        finally:
            s.close()
        with pytest.raises(SysarchHandlerError, match="no sysarch node"):
            asyncio.run(generate_sysarch({"project_id": pid, "feedback": None}))

    def test_cli_failure_leaves_no_events(
        self, shared_session_factory, seeded_project, monkeypatch
    ):
        import backend.graph.handlers.feature_expansion as _fe_handler

        async def boom(**kwargs):
            raise RuntimeError("LLM exploded")

        monkeypatch.setattr(_fe_handler.cli_manager, "generate_with_usage", boom)
        with pytest.raises(RuntimeError, match="LLM exploded"):
            asyncio.run(generate_sysarch({"project_id": seeded_project, "feedback": None}))
        session = shared_session_factory()
        try:
            drafts = list(
                session.execute(select(Draft).where(Draft.project_id == seeded_project)).scalars()
            )
            assert drafts == []
        finally:
            session.close()


class TestParseValidateRetry:
    def test_retry_on_missing_foundation(
        self, shared_session_factory, seeded_project, seeded_resp_ids, monkeypatch
    ):
        # First attempt: valid structure but no foundation component.
        bad = _valid_sysarch(seeded_resp_ids).replace("<foundation/>", "")
        good = _valid_sysarch(seeded_resp_ids)
        calls = _patch_cli_sequence(monkeypatch, [bad, good])
        asyncio.run(generate_sysarch({"project_id": seeded_project, "feedback": None}))
        assert len(calls) == 2
        # Retry prompt mentions the foundation error verbatim
        assert "no foundation component" in calls[1]["prompt"]

    def test_retry_on_missing_foundation_dep(
        self, shared_session_factory, seeded_project, seeded_resp_ids, monkeypatch
    ):
        # First attempt: valid foundation + valid components but
        # omits the required foundation dep from 'auth'. The
        # validator catches it and the retry prompt surfaces the
        # specific missing-alias list.
        good = _valid_sysarch(seeded_resp_ids)
        bad = good.replace('<dep from="auth" to="foundation"/>', "")
        calls = _patch_cli_sequence(monkeypatch, [bad, good])
        asyncio.run(generate_sysarch({"project_id": seeded_project, "feedback": None}))
        assert len(calls) == 2
        assert "Missing foundation dependency from: auth" in calls[1]["prompt"]

    def test_retry_on_dep_cycle(
        self, shared_session_factory, seeded_project, seeded_resp_ids, monkeypatch
    ):
        # First attempt introduces a 2-cycle between billing and auth.
        good = _valid_sysarch(seeded_resp_ids)
        good_deps = (
            "<dependencies>"
            '<dep from="billing" to="foundation"/>'
            '<dep from="auth" to="foundation"/>'
            "</dependencies>"
        )
        bad_deps = (
            "<dependencies>"
            '<dep from="billing" to="auth"/>'
            '<dep from="auth" to="billing"/>'
            "</dependencies>"
        )
        bad = good.replace(good_deps, bad_deps)
        calls = _patch_cli_sequence(monkeypatch, [bad, good])
        asyncio.run(generate_sysarch({"project_id": seeded_project, "feedback": None}))
        assert len(calls) == 2
        assert "Dependency cycle detected" in calls[1]["prompt"]

    def test_retry_on_unknown_resp_id(
        self, shared_session_factory, seeded_project, seeded_resp_ids, monkeypatch
    ):
        # First attempt references a resp ID that doesn't exist in
        # the project. Validator catches it with "unknown top-level
        # responsibility" and the retry prompt surfaces the error.
        good = _valid_sysarch(seeded_resp_ids)
        foundation_id = seeded_resp_ids[2]
        bad = good.replace(f'<resp id="{foundation_id}"/>', '<resp id="resp_bogusbog"/>')
        calls = _patch_cli_sequence(monkeypatch, [bad, good])
        asyncio.run(generate_sysarch({"project_id": seeded_project, "feedback": None}))
        assert len(calls) == 2
        assert "unknown top-level responsibility" in calls[1]["prompt"]

    def test_retry_exhaustion_raises(
        self, shared_session_factory, seeded_project, seeded_resp_ids, monkeypatch
    ):
        from backend.graph.handlers.feature_expansion import MAX_PARSE_RETRIES

        total = MAX_PARSE_RETRIES + 1
        _patch_cli_sequence(monkeypatch, ["not xml"] * total)
        with pytest.raises(SysarchParseRetryExhausted):
            asyncio.run(generate_sysarch({"project_id": seeded_project, "feedback": None}))
        session = shared_session_factory()
        try:
            drafts = list(
                session.execute(select(Draft).where(Draft.project_id == seeded_project)).scalars()
            )
            assert drafts == []
        finally:
            session.close()


class TestTelemetry:
    def test_records_telemetry_row(
        self, shared_session_factory, seeded_project, seeded_resp_ids, monkeypatch
    ):
        _patch_cli(
            monkeypatch,
            _valid_sysarch(seeded_resp_ids),
            prompt_tokens=3000,
            completion_tokens=800,
            model="claude-sonnet-4-6",
        )
        asyncio.run(generate_sysarch({"project_id": seeded_project, "feedback": None}))
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
            assert row.section == "sysarch"
            assert row.prompt_tokens == 3000
            assert row.completion_tokens == 800
            assert row.node_id.startswith("sysarch_")
        finally:
            session.close()


class TestProjectSettingsTimeout:
    def test_default_7200(
        self, shared_session_factory, seeded_project, seeded_resp_ids, monkeypatch
    ):
        calls = _patch_cli(monkeypatch, _valid_sysarch(seeded_resp_ids))
        asyncio.run(generate_sysarch({"project_id": seeded_project, "feedback": None}))
        assert calls[0]["config"].timeout_seconds == 7200

    def test_override_honored(
        self, shared_session_factory, seeded_project, seeded_resp_ids, monkeypatch
    ):
        factory = shared_session_factory
        s = factory()
        try:
            project = s.get(Project, seeded_project)
            assert project is not None
            project.settings = {"generation_timeout_seconds": 1500}
            s.commit()
        finally:
            s.close()
        calls = _patch_cli(monkeypatch, _valid_sysarch(seeded_resp_ids))
        asyncio.run(generate_sysarch({"project_id": seeded_project, "feedback": None}))
        assert calls[0]["config"].timeout_seconds == 1500


class TestInputDocInclusion:
    """The handler feeds the project input document into every
    sysarch generation — initial bootstrap *and* feedback regens
    on a pending draft. The freeze-on-approval rule at the HTTP
    route layer (see ``backend/graph/routes.py``, which returns
    409 once ``sysarch_has_been_approved`` is true) guarantees
    this handler never runs against approved state, so every
    invocation is either an initial pass or a pre-approval
    iteration, and both need the original framing."""

    def test_initial_generation_includes_input_doc(
        self, shared_session_factory, seeded_project, seeded_resp_ids, monkeypatch
    ):
        calls = _patch_cli(monkeypatch, _valid_sysarch(seeded_resp_ids))
        asyncio.run(generate_sysarch({"project_id": seeded_project, "feedback": None}))
        prompt = calls[0]["prompt"]
        assert "# Project input document" in prompt
        # Content from the seeded_project fixture's InputDocument.
        assert "A task tracker." in prompt

    def test_regen_with_feedback_still_includes_input_doc(
        self, shared_session_factory, seeded_project, seeded_resp_ids, monkeypatch
    ):
        # First generation lands a pending draft.
        first_calls = _patch_cli(monkeypatch, _valid_sysarch(seeded_resp_ids))
        asyncio.run(generate_sysarch({"project_id": seeded_project, "feedback": None}))
        assert "# Project input document" in first_calls[0]["prompt"]

        # Second call with feedback: user is iterating on the
        # pending draft and needs the LLM to reshape with the
        # original framing still visible.
        second_calls = _patch_cli(monkeypatch, _valid_sysarch(seeded_resp_ids))
        asyncio.run(
            generate_sysarch(
                {"project_id": seeded_project, "feedback": "Split billing into two comps"}
            )
        )
        prompt = second_calls[0]["prompt"]
        assert "# Project input document" in prompt
        assert "A task tracker." in prompt
        # Sanity-check that this is actually the regen path.
        assert "Split billing into two comps" in prompt

    def test_regen_prompt_contains_most_recent_pending_draft(
        self, shared_session_factory, seeded_project, seeded_resp_ids, monkeypatch
    ):
        # Regression for "is the LLM seeing the draft it's being
        # asked to refine?". Same shape as the matching test in
        # test_requirements_handler.py.
        #
        # We use the same _valid_sysarch() XML both times (there's
        # only one deterministic valid shape for the seeded resps)
        # and distinguish drafts by feedback + by the rendered
        # "# Current draft (not yet approved)" section text, which
        # must contain the raw XML from the previous generation.
        first_xml = _valid_sysarch(seeded_resp_ids)
        _patch_cli(monkeypatch, first_xml)
        asyncio.run(generate_sysarch({"project_id": seeded_project, "feedback": None}))

        second_calls = _patch_cli(monkeypatch, first_xml)
        asyncio.run(
            generate_sysarch(
                {"project_id": seeded_project, "feedback": "Reconsider dependency shape"}
            )
        )
        second_prompt = second_calls[0]["prompt"]
        # The first draft's actual XML must appear inside the
        # "# Current draft" section so the LLM knows what it's
        # refining.
        assert "# Current version" in second_prompt
        assert "Python 3.11 FastAPI async loop" in second_prompt
        assert "Reconsider dependency shape" in second_prompt

    def test_missing_input_document_row_does_not_crash(self, shared_session_factory, monkeypatch):
        # A project with no InputDocument row. Initial gen should
        # still succeed; the input doc section is just omitted.
        factory = shared_session_factory
        session: Session = factory()
        try:
            pid = str(uuid.uuid4())
            session.add(Project(id=pid, name="T3", git_repo_path="/tmp/t3"))
            session.flush()
            _mint_feature(session, pid, "Auth", 0)
            auth_resp = _mint_top_level_resp(session, pid, "Authentication", "Identify.", 0)
            billing_resp = _mint_top_level_resp(session, pid, "Billing", "Bill.", 1)
            foundation_resp = _mint_top_level_resp(session, pid, "Foundation", "Shared.", 2)
            bootstrap_sysarch_node(session, pid)
            session.commit()
        finally:
            session.close()

        calls = _patch_cli(
            monkeypatch,
            _valid_sysarch([auth_resp, billing_resp, foundation_resp]),
        )
        asyncio.run(generate_sysarch({"project_id": pid, "feedback": None}))
        prompt = calls[0]["prompt"]
        assert "# Project input document" not in prompt
        # The rest of the prompt still renders.
        assert "# Project features" in prompt
