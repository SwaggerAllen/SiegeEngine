"""Tests for backend.graph.handlers.requirements_generation.

Same scaffold as test_feature_expansion_handler.py — the reqs
handler is a near-clone, so these tests mirror its structure:
happy path, regen, CLI failure, parse-validate retry loop,
telemetry, project settings timeout wiring. Plus a couple of
reqs-specific tests for the features-summary plumbing and the
``<covers>`` many-to-many coverage check.

``cli_manager.generate_with_usage`` is monkeypatched so the real
CLI never runs; tests feed deterministic text through the parse-
validate loop.
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
from backend.graph.handlers.requirements_generation import (
    RequirementsHandlerError,
    RequirementsParseRetryExhausted,
    generate_requirements,
)
from backend.graph.reducer import append_event
from backend.graph.requirements import bootstrap_reqs_node
from backend.models import InputDocument, Project
from backend.models.node import Draft, Node
from backend.models.telemetry import GenerationTelemetry


@pytest.fixture(autouse=True)
def _fast_cli_retry_backoff(monkeypatch):
    """Zero out the transient-CLI-error backoff shared with feature_expansion."""
    import backend.graph.handlers.feature_expansion as _fe_handler

    monkeypatch.setattr(
        _fe_handler,
        "CLI_RETRY_BACKOFF_SECONDS",
        (0.0,) * (_fe_handler.CLI_MAX_TRANSIENT_RETRIES + 1),
    )


@pytest.fixture()
def shared_session_factory(monkeypatch):
    """In-memory engine shared with the handler's SessionLocal()."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    import backend.database as _database_mod
    import backend.graph.handlers.requirements_generation as _handler_mod

    monkeypatch.setattr(_database_mod, "SessionLocal", factory)
    monkeypatch.setattr(_handler_mod, "SessionLocal", factory)
    yield factory
    engine.dispose()


def _mint_feature(session: Session, project_id: str, name: str, intent: str, order: int) -> str:
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
            content=intent,
        ),
    )
    return feat_id


@pytest.fixture()
def seeded_project(shared_session_factory):
    """Project + input doc + two minted features + reqs node.

    Returns the project id as a plain string; the feature ids
    are looked up via the ``seeded_feat_ids`` fixture.
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
                content="Build a widget tracker.",
                doc_type="project_doc",
            )
        )
        _mint_feature(session, project_id, "Billing", "Users pay for plans.", 0)
        _mint_feature(session, project_id, "Auth", "Users sign in.", 1)
        bootstrap_reqs_node(session, project_id)
        session.commit()
        yield project_id
    finally:
        session.close()


@pytest.fixture()
def seeded_feat_ids(shared_session_factory, seeded_project) -> list[str]:
    """Return the feature IDs seeded by ``seeded_project`` in display order."""
    factory = shared_session_factory
    s: Session = factory()
    try:
        return [
            fid
            for (fid,) in s.execute(
                select(Node.id)
                .where(Node.project_id == seeded_project, Node.tier == "feat")
                .order_by(Node.display_order)
            ).all()
        ]
    finally:
        s.close()


def _covers_all(feat_ids: list[str]) -> str:
    """Build a ``<covers>`` block listing every known feature id.

    Using all-features-per-responsibility keeps the coverage
    check happy in a maximally-boring way. Tests that want to
    exercise specific subsets can build their own covers blocks.
    """
    return "<covers>" + "".join(f'<feat id="{fid}"/>' for fid in feat_ids) + "</covers>"


def _reqs_xml(feat_ids: list[str], *entries: tuple[str, str]) -> str:
    """Build a valid ``<requirements>`` block where every entry
    covers every feature in ``feat_ids``.

    Phase-11 followup B4 made ``<introduction>`` a required
    sibling block; this helper prepends a stub intro.
    """
    covers = _covers_all(feat_ids)
    inner = "".join(
        f"<responsibility><name>{name}</name><intent>{intent}</intent>{covers}</responsibility>"
        for name, intent in entries
    )
    return (
        "<introduction>Stub intro for requirements handler tests.</introduction>"
        f"<requirements>{inner}</requirements>"
    )


def _valid_xml(feat_ids: list[str]) -> str:
    return _reqs_xml(
        feat_ids,
        ("User Authentication", "Identify callers and make them available downstream."),
    )


def _patch_cli(
    monkeypatch,
    return_value: str,
    *,
    prompt_tokens: int = 100,
    completion_tokens: int = 50,
    model: str = "claude-sonnet-4-6",
):
    """Patch the CLI manager used by the requirements handler."""
    import backend.graph.handlers.feature_expansion as _fe_handler
    from backend.cli.manager import GenerationResult

    calls: list[dict] = []

    async def fake(**kwargs):
        calls.append(kwargs)
        return GenerationResult(
            text=return_value,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            model=model,
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
        self, shared_session_factory, seeded_project, seeded_feat_ids, monkeypatch
    ):
        draft_xml = _reqs_xml(seeded_feat_ids, ("Auth", "Identify callers."))
        calls = _patch_cli(monkeypatch, draft_xml)
        asyncio.run(generate_requirements({"project_id": seeded_project, "feedback": None}))

        # Feature list is embedded in the prompt so the LLM sees it
        assert len(calls) == 1
        prompt = calls[0]["prompt"]
        assert "Billing" in prompt
        assert "Users pay for plans." in prompt
        assert "Auth" in prompt
        # Feature IDs must appear in the prompt — LLM echoes them in <covers>
        for fid in seeded_feat_ids:
            assert fid in prompt

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
        self, shared_session_factory, seeded_project, seeded_feat_ids, monkeypatch
    ):
        first = _reqs_xml(seeded_feat_ids, ("One", "First draft."))
        second = _reqs_xml(seeded_feat_ids, ("Two", "Second draft."))

        _patch_cli(monkeypatch, first)
        asyncio.run(generate_requirements({"project_id": seeded_project, "feedback": None}))

        _patch_cli(monkeypatch, second)
        asyncio.run(
            generate_requirements({"project_id": seeded_project, "feedback": "Make it better"})
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
            pending = next(d for d in drafts if d.status == "pending")
            assert pending.content == second
        finally:
            session.close()

    def test_feedback_appears_in_prompt(
        self, shared_session_factory, seeded_project, seeded_feat_ids, monkeypatch
    ):
        first = _reqs_xml(seeded_feat_ids, ("Auth", "v1."))
        _patch_cli(monkeypatch, first)
        asyncio.run(generate_requirements({"project_id": seeded_project, "feedback": None}))

        calls = _patch_cli(monkeypatch, _reqs_xml(seeded_feat_ids, ("Auth", "v2.")))
        asyncio.run(
            generate_requirements({"project_id": seeded_project, "feedback": "Add rate limiting"})
        )
        assert "Add rate limiting" in calls[0]["prompt"]


class TestFailureModes:
    def test_missing_project_id_raises(self, shared_session_factory):
        with pytest.raises(RequirementsHandlerError, match="project_id"):
            asyncio.run(generate_requirements({}))

    def test_missing_reqs_node_raises(self, shared_session_factory):
        factory = shared_session_factory
        s = factory()
        try:
            pid = str(uuid.uuid4())
            s.add(Project(id=pid, name="T2", git_repo_path="/tmp/t2"))
            s.commit()
        finally:
            s.close()
        with pytest.raises(RequirementsHandlerError, match="no reqs node"):
            asyncio.run(generate_requirements({"project_id": pid, "feedback": None}))

    def test_cli_failure_leaves_no_events(
        self, shared_session_factory, seeded_project, monkeypatch
    ):
        import backend.graph.handlers.feature_expansion as _fe_handler

        async def boom(**kwargs):
            raise RuntimeError("LLM exploded")

        monkeypatch.setattr(_fe_handler.cli_manager, "generate_with_usage", boom)

        with pytest.raises(RuntimeError, match="LLM exploded"):
            asyncio.run(generate_requirements({"project_id": seeded_project, "feedback": None}))

        session = shared_session_factory()
        try:
            drafts = list(
                session.execute(select(Draft).where(Draft.project_id == seeded_project)).scalars()
            )
            assert drafts == []
        finally:
            session.close()


class TestParseValidateRetry:
    def test_retry_succeeds_on_second_attempt(
        self, shared_session_factory, seeded_project, seeded_feat_ids, monkeypatch
    ):
        first_bad = "Here are the requirements but I forgot the tags."
        second_good = _reqs_xml(seeded_feat_ids, ("Auth", "Ok."))
        calls = _patch_cli_sequence(monkeypatch, [first_bad, second_good])
        asyncio.run(generate_requirements({"project_id": seeded_project, "feedback": None}))
        assert len(calls) == 2
        retry_prompt = calls[1]["prompt"]
        assert "Previous output failed structural validation" in retry_prompt
        assert "<requirements>" in retry_prompt

    def test_retry_on_missing_covers_block(
        self, shared_session_factory, seeded_project, seeded_feat_ids, monkeypatch
    ):
        # First attempt: no <covers> block (regression of the v2
        # retrofit — the LLM forgot to include it).
        first_bad = (
            "<introduction>stub</introduction>"
            "<requirements>"
            "<responsibility><name>Auth</name><intent>Ok.</intent></responsibility>"
            "</requirements>"
        )
        second_good = _reqs_xml(seeded_feat_ids, ("Auth", "Ok."))
        calls = _patch_cli_sequence(monkeypatch, [first_bad, second_good])
        asyncio.run(generate_requirements({"project_id": seeded_project, "feedback": None}))
        assert len(calls) == 2
        retry_prompt = calls[1]["prompt"]
        # The retry prompt surfaces the specific validation error.
        assert "missing a <covers>" in retry_prompt

    def test_retry_on_missing_feature_coverage(
        self, shared_session_factory, seeded_project, seeded_feat_ids, monkeypatch
    ):
        # First attempt: covers only the first feature, leaving
        # the second uncovered.
        partial_covers = "<covers>" + f'<feat id="{seeded_feat_ids[0]}"/>' + "</covers>"
        first_bad = (
            "<introduction>stub</introduction>"
            "<requirements>"
            f"<responsibility><name>Auth</name><intent>Ok.</intent>{partial_covers}</responsibility>"
            "</requirements>"
        )
        second_good = _reqs_xml(seeded_feat_ids, ("Auth", "Ok."))
        calls = _patch_cli_sequence(monkeypatch, [first_bad, second_good])
        asyncio.run(generate_requirements({"project_id": seeded_project, "feedback": None}))
        assert len(calls) == 2
        retry_prompt = calls[1]["prompt"]
        assert "does not cover every feature" in retry_prompt
        # The uncovered id is named in the error feedback
        assert seeded_feat_ids[1] in retry_prompt

    def test_retry_on_unknown_feature_id(
        self, shared_session_factory, seeded_project, seeded_feat_ids, monkeypatch
    ):
        fake_covers = '<covers><feat id="feat_bogus01"/></covers>'
        first_bad = (
            "<introduction>stub</introduction>"
            "<requirements>"
            f"<responsibility><name>Auth</name><intent>Ok.</intent>{fake_covers}</responsibility>"
            "</requirements>"
        )
        second_good = _reqs_xml(seeded_feat_ids, ("Auth", "Ok."))
        calls = _patch_cli_sequence(monkeypatch, [first_bad, second_good])
        asyncio.run(generate_requirements({"project_id": seeded_project, "feedback": None}))
        assert len(calls) == 2
        assert "unknown feature id" in calls[1]["prompt"]

    def test_retry_exhaustion_raises(
        self, shared_session_factory, seeded_project, seeded_feat_ids, monkeypatch
    ):
        from backend.graph.handlers.feature_expansion import MAX_PARSE_RETRIES

        total = MAX_PARSE_RETRIES + 1
        _patch_cli_sequence(monkeypatch, ["not xml"] * total)
        with pytest.raises(RequirementsParseRetryExhausted):
            asyncio.run(generate_requirements({"project_id": seeded_project, "feedback": None}))
        # No draft, no telemetry
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
        self, shared_session_factory, seeded_project, seeded_feat_ids, monkeypatch
    ):
        _patch_cli(
            monkeypatch,
            _reqs_xml(seeded_feat_ids, ("Auth", "Ok.")),
            prompt_tokens=1234,
            completion_tokens=567,
            model="claude-sonnet-4-6",
        )
        asyncio.run(generate_requirements({"project_id": seeded_project, "feedback": None}))

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
            assert row.section == "requirements"
            assert row.prompt_tokens == 1234
            assert row.completion_tokens == 567
            assert row.model == "claude-sonnet-4-6"
            assert row.node_id is not None and row.node_id.startswith("reqs_")
        finally:
            session.close()


class TestProjectSettingsTimeout:
    def test_default_timeout_is_1800_when_settings_is_null(
        self, shared_session_factory, seeded_project, seeded_feat_ids, monkeypatch
    ):
        calls = _patch_cli(monkeypatch, _valid_xml(seeded_feat_ids))
        asyncio.run(generate_requirements({"project_id": seeded_project, "feedback": None}))
        assert len(calls) == 1
        assert calls[0]["timeout"] == 1800

    def test_uses_override_when_settings_is_populated(
        self, shared_session_factory, seeded_project, seeded_feat_ids, monkeypatch
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
        calls = _patch_cli(monkeypatch, _valid_xml(seeded_feat_ids))
        asyncio.run(generate_requirements({"project_id": seeded_project, "feedback": None}))
        assert calls[0]["timeout"] == 1500


class TestFeaturesInPrompt:
    def test_features_summary_includes_all_minted_features(
        self, shared_session_factory, seeded_project, seeded_feat_ids, monkeypatch
    ):
        calls = _patch_cli(monkeypatch, _valid_xml(seeded_feat_ids))
        asyncio.run(generate_requirements({"project_id": seeded_project, "feedback": None}))
        prompt = calls[0]["prompt"]
        assert "Billing" in prompt
        assert "Users pay for plans." in prompt
        assert "Auth" in prompt
        assert "Users sign in." in prompt
        # IDs are prominent in the rendered feature list
        for fid in seeded_feat_ids:
            assert fid in prompt


class TestInputDocInclusion:
    """The handler feeds the project input document into every
    requirements generation — initial bootstrap *and* feedback
    regens on a pending draft. The freeze-on-approval rule at
    the HTTP route layer (see ``backend/graph/routes.py``, which
    returns 409 once ``reqs_has_been_approved`` is true)
    guarantees this handler never runs against approved state,
    so every invocation is either an initial pass or a pre-
    approval iteration, and both need the original framing."""

    def test_initial_generation_includes_input_doc(
        self, shared_session_factory, seeded_project, seeded_feat_ids, monkeypatch
    ):
        calls = _patch_cli(monkeypatch, _valid_xml(seeded_feat_ids))
        asyncio.run(generate_requirements({"project_id": seeded_project, "feedback": None}))
        prompt = calls[0]["prompt"]
        assert "# Project input document" in prompt
        # Content from the seeded_project fixture's InputDocument.
        assert "Build a widget tracker." in prompt

    def test_regen_with_feedback_still_includes_input_doc(
        self, shared_session_factory, seeded_project, seeded_feat_ids, monkeypatch
    ):
        # First generation lands a pending draft.
        first_calls = _patch_cli(monkeypatch, _valid_xml(seeded_feat_ids))
        asyncio.run(generate_requirements({"project_id": seeded_project, "feedback": None}))
        assert "# Project input document" in first_calls[0]["prompt"]

        # Second call with feedback: user is iterating on the
        # pending draft and needs the LLM to reshape with the
        # original framing still visible. The doc must stay.
        second_calls = _patch_cli(monkeypatch, _reqs_xml(seeded_feat_ids, ("Auth", "v2.")))
        asyncio.run(
            generate_requirements({"project_id": seeded_project, "feedback": "Tighten it up"})
        )
        prompt = second_calls[0]["prompt"]
        assert "# Project input document" in prompt
        assert "Build a widget tracker." in prompt
        # Sanity-check that this is actually the regen path and
        # not a false pass from the handler short-circuiting
        # back to the initial code path.
        assert "Tighten it up" in prompt

    def test_regen_prompt_contains_most_recent_pending_draft(
        self, shared_session_factory, seeded_project, seeded_feat_ids, monkeypatch
    ):
        # Regression for "is the LLM seeing the draft it's being
        # asked to refine?". The handler reads pending_reqs_draft
        # each call (which is guaranteed-unique-per-node by the
        # pending partial index), so each regen reads the most
        # recent pending and renders it under "# Current draft
        # (not yet approved)". Without this test, a future change
        # to the prompt-render ordering could silently drop the
        # section and we'd only notice in a quality regression.
        distinctive_first = _reqs_xml(
            seeded_feat_ids,
            ("DraftOneMarker", "A distinctive first-draft intent."),
        )
        _patch_cli(monkeypatch, distinctive_first)
        asyncio.run(generate_requirements({"project_id": seeded_project, "feedback": None}))

        distinctive_second = _reqs_xml(
            seeded_feat_ids,
            ("DraftTwoMarker", "A distinctive second-draft intent."),
        )
        second_calls = _patch_cli(monkeypatch, distinctive_second)
        asyncio.run(
            generate_requirements({"project_id": seeded_project, "feedback": "Make it more pithy"})
        )
        second_prompt = second_calls[0]["prompt"]
        # The first draft's distinguishing strings must appear in
        # the second regen's prompt under the "Current draft"
        # section, so the LLM knows what it's refining.
        assert "# Current version" in second_prompt
        assert "DraftOneMarker" in second_prompt
        assert "A distinctive first-draft intent." in second_prompt

        # And the third call's pending is D2, not D1 — proving the
        # "most recent" part of the contract. D1 was discarded by
        # the second call's DraftDiscarded event, so the third call
        # should see D2 (which contains DraftTwoMarker) but not D1.
        distinctive_third = _reqs_xml(
            seeded_feat_ids,
            ("DraftThreeMarker", "A distinctive third-draft intent."),
        )
        third_calls = _patch_cli(monkeypatch, distinctive_third)
        asyncio.run(
            generate_requirements(
                {"project_id": seeded_project, "feedback": "Actually, different direction"}
            )
        )
        third_prompt = third_calls[0]["prompt"]
        assert "DraftTwoMarker" in third_prompt
        assert "A distinctive second-draft intent." in third_prompt
        assert "DraftOneMarker" not in third_prompt
        assert "A distinctive first-draft intent." not in third_prompt

    def test_missing_input_document_row_does_not_crash(self, shared_session_factory, monkeypatch):
        # Edge case: a project without an InputDocument row (e.g.
        # created through a legacy path or mid-test). Initial gen
        # should still succeed; the input doc section is just
        # omitted.
        factory = shared_session_factory
        session: Session = factory()
        try:
            pid = str(uuid.uuid4())
            session.add(Project(id=pid, name="T3", git_repo_path="/tmp/t3"))
            session.flush()
            fid = _mint_feature(session, pid, "Auth", "Users sign in.", 0)
            bootstrap_reqs_node(session, pid)
            session.commit()
        finally:
            session.close()

        calls = _patch_cli(
            monkeypatch,
            _reqs_xml(
                [fid],
                ("Auth", "Identify callers and make them available downstream."),
            ),
        )
        asyncio.run(generate_requirements({"project_id": pid, "feedback": None}))
        prompt = calls[0]["prompt"]
        assert "# Project input document" not in prompt
        # The rest of the prompt still renders.
        assert "# Project features" in prompt


class TestDomainUiSplitGuidance:
    """The reqs system prompt tells the LLM NOT to split features into
    domain/presentational sibling responsibilities — that split is
    sysarch's job. Guard the guidance text so it can't be silently
    removed during a prompt rewrite."""

    def test_system_prompt_includes_no_split_guidance(
        self, shared_session_factory, seeded_project, seeded_feat_ids, monkeypatch
    ):
        calls = _patch_cli(monkeypatch, _valid_xml(seeded_feat_ids))
        asyncio.run(generate_requirements({"project_id": seeded_project, "feedback": None}))
        system_prompt = calls[0]["system_prompt"]
        assert "not UI/backend splits" in system_prompt
        assert "sysarch pass makes" in system_prompt
