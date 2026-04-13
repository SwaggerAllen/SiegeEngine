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
    CLI_MAX_TRANSIENT_RETRIES,
    MAX_PARSE_RETRIES,
    FeatureExpansionHandlerError,
    FeatureExpansionParseRetryExhausted,
    generate_feature_expansion,
)
from backend.graph.reducer import append_event
from backend.models import InputDocument, Project
from backend.models.node import Draft
from backend.models.telemetry import GenerationTelemetry


@pytest.fixture(autouse=True)
def _fast_cli_retry_backoff(monkeypatch):
    """Zero out the transient-CLI-error backoff so tests don't sleep.

    The real handler waits seconds between retries; in tests we just
    want the retry *count* and *control flow* to exercise, not the
    wall-clock pauses.
    """
    import backend.graph.handlers.feature_expansion as _handler_mod

    monkeypatch.setattr(
        _handler_mod,
        "CLI_RETRY_BACKOFF_SECONDS",
        (0.0,) * (_handler_mod.CLI_MAX_TRANSIENT_RETRIES + 1),
    )


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


# A minimal valid <features> block for use as the default CLI
# output in tests that don't care about the specific feature set.
# Under Phase 2's parse-validate retry loop, every mock CLI
# response must parse and validate as a <features> block or the
# handler will retry until its budget is exhausted.
_VALID_FEATURES_XML = (
    "<features>"
    "<feature>"
    "<name>Default Feature</name>"
    "<intent>A default test feature with paragraph-length intent "
    "for round-trip coverage.</intent>"
    "</feature>"
    "</features>"
)


def _feature_xml(*features: tuple[str, str]) -> str:
    """Build a valid <features> XML string from (name, intent) pairs."""
    inner = "".join(
        f"<feature><name>{name}</name><intent>{intent}</intent></feature>"
        for name, intent in features
    )
    return f"<features>{inner}</features>"


def _patch_cli(
    monkeypatch,
    return_value: str = _VALID_FEATURES_XML,
    *,
    prompt_tokens: int = 100,
    completion_tokens: int = 50,
    model: str = "claude-sonnet-4-6",
):
    """Patch the ``cli_manager.generate_with_usage`` bound method used by the handler.

    ``return_value`` defaults to a minimal valid <features> block;
    tests that exercise the parse-validate retry loop pass in a
    sequence instead (see ``_patch_cli_sequence``).
    """
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


def _patch_cli_sequence(
    monkeypatch,
    return_values: list[str],
    *,
    prompt_tokens: int = 100,
    completion_tokens: int = 50,
    model: str = "claude-sonnet-4-6",
):
    """Patch the CLI to return different outputs on successive calls.

    Used by parse-validate retry tests where the first attempt
    deliberately produces invalid output. The CLI raises
    ``RuntimeError`` if called more times than ``return_values``
    has entries, which catches tests that misconfigure the mock.
    """
    import backend.graph.handlers.feature_expansion as _handler_mod
    from backend.cli.manager import GenerationResult

    calls: list[dict] = []
    remaining = list(return_values)

    async def fake_generate_with_usage(**kwargs):
        calls.append(kwargs)
        if not remaining:
            raise RuntimeError("CLI mock exhausted — test called it too many times")
        text = remaining.pop(0)
        return GenerationResult(
            text=text,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            model=model,
        )

    monkeypatch.setattr(_handler_mod.cli_manager, "generate_with_usage", fake_generate_with_usage)
    return calls


class TestHappyPath:
    def test_generates_pending_draft(self, shared_session_factory, seeded_project, monkeypatch):
        first_draft = _feature_xml(("First", "First feature intent."))
        calls = _patch_cli(monkeypatch, first_draft)
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
            assert drafts[0].content == first_draft
            assert drafts[0].target_type == "node"
            assert drafts[0].id.startswith("draft_")
        finally:
            session.close()

    def test_regeneration_discards_old_pending(
        self, shared_session_factory, seeded_project, monkeypatch
    ):
        draft_one = _feature_xml(("One", "Draft one intent."))
        draft_two = _feature_xml(("Two", "Draft two intent."))

        # First generation
        _patch_cli(monkeypatch, draft_one)
        asyncio.run(generate_feature_expansion({"project_id": seeded_project, "feedback": None}))

        # Second generation with feedback
        _patch_cli(monkeypatch, draft_two)
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
            assert pending.content == draft_two
        finally:
            session.close()

    def test_regeneration_passes_prior_pending_to_prompt(
        self, shared_session_factory, seeded_project, monkeypatch
    ):
        draft_one = _feature_xml(("One", "Draft one intent."))
        draft_two = _feature_xml(("Two", "Draft two intent."))

        _patch_cli(monkeypatch, draft_one)
        asyncio.run(generate_feature_expansion({"project_id": seeded_project, "feedback": None}))

        calls = _patch_cli(monkeypatch, draft_two)
        asyncio.run(
            generate_feature_expansion(
                {"project_id": seeded_project, "feedback": "Shorten section 2"}
            )
        )

        assert len(calls) == 1
        prompt = calls[0]["prompt"]
        assert "Draft one intent." in prompt
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
        approved = _feature_xml(("Approved", "Approved content intent."))
        _patch_cli(monkeypatch, approved)
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
            assert node.content == approved
        finally:
            session.close()


class TestTelemetry:
    """Every successful generation call records a telemetry row."""

    def test_records_telemetry_row(self, shared_session_factory, seeded_project, monkeypatch):
        _patch_cli(
            monkeypatch,
            _feature_xml(("Draft", "Short paragraph intent.")),
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
            _feature_xml(("First", "First intent.")),
            prompt_tokens=100,
            completion_tokens=50,
        )
        asyncio.run(generate_feature_expansion({"project_id": seeded_project, "feedback": None}))
        _patch_cli(
            monkeypatch,
            _feature_xml(("Second", "Second intent.")),
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


class TestParseValidateRetry:
    """The expansion handler re-invokes the LLM when its first output
    fails to parse or validate as a <features> block, feeding the
    error back into the prompt. The final committed draft is the
    validated one; every LLM call records telemetry.
    """

    def test_retry_succeeds_on_second_attempt(
        self, shared_session_factory, seeded_project, monkeypatch
    ):
        first_bad = "Here are some features, but I forgot the tags."
        second_good = _feature_xml(("Fixed", "Corrected after retry."))
        calls = _patch_cli_sequence(monkeypatch, [first_bad, second_good])

        asyncio.run(generate_feature_expansion({"project_id": seeded_project, "feedback": None}))

        # Two CLI calls were made.
        assert len(calls) == 2
        # The second call's prompt must carry the parse-error section
        # telling the LLM what was wrong with its first attempt.
        retry_prompt = calls[1]["prompt"]
        assert "Previous output failed structural validation" in retry_prompt
        assert "<features>" in retry_prompt  # error message mentions the expected tag

        # Only one DraftGenerated event landed, with the validated content.
        session = shared_session_factory()
        try:
            drafts = list(
                session.execute(select(Draft).where(Draft.project_id == seeded_project)).scalars()
            )
            assert len(drafts) == 1
            assert drafts[0].content == second_good
        finally:
            session.close()

    def test_retry_records_telemetry_for_every_attempt(
        self, shared_session_factory, seeded_project, monkeypatch
    ):
        first_bad = "<features></features>"  # validation fails: no children
        second_good = _feature_xml(("OK", "Second attempt worked."))
        _patch_cli_sequence(
            monkeypatch,
            [first_bad, second_good],
            prompt_tokens=150,
            completion_tokens=75,
        )

        asyncio.run(generate_feature_expansion({"project_id": seeded_project, "feedback": None}))

        session = shared_session_factory()
        try:
            rows = list(
                session.execute(
                    select(GenerationTelemetry)
                    .where(GenerationTelemetry.project_id == seeded_project)
                    .order_by(GenerationTelemetry.created_at)
                ).scalars()
            )
            # One row per LLM call — the failed attempt AND the success.
            assert len(rows) == 2
            assert all(r.prompt_tokens == 150 for r in rows)
            assert all(r.completion_tokens == 75 for r in rows)
        finally:
            session.close()

    def test_retry_exhaustion_raises_and_leaves_no_draft(
        self, shared_session_factory, seeded_project, monkeypatch
    ):
        # Every attempt returns invalid output. The handler retries
        # MAX_PARSE_RETRIES + 1 times total before raising.
        total_attempts = MAX_PARSE_RETRIES + 1
        bad_outputs = ["not xml at all"] * total_attempts
        calls = _patch_cli_sequence(monkeypatch, bad_outputs)

        with pytest.raises(FeatureExpansionParseRetryExhausted):
            asyncio.run(
                generate_feature_expansion({"project_id": seeded_project, "feedback": None})
            )

        # Exactly the configured number of attempts were made.
        assert len(calls) == total_attempts

        # No draft and no telemetry rows landed — the handler raised
        # before committing.
        session = shared_session_factory()
        try:
            drafts = list(
                session.execute(select(Draft).where(Draft.project_id == seeded_project)).scalars()
            )
            assert drafts == []
            tlm = list(
                session.execute(
                    select(GenerationTelemetry).where(
                        GenerationTelemetry.project_id == seeded_project
                    )
                ).scalars()
            )
            assert tlm == []
        finally:
            session.close()

    def test_retry_prompt_uses_previous_bad_output_as_prior_pending(
        self, shared_session_factory, seeded_project, monkeypatch
    ):
        # The retry should show the LLM its own previous output (not
        # the original prior_pending) so it has context for the fix.
        first_bad = (
            "<features><feature><name>OnlyName</name></feature></features>"  # missing <intent>
        )
        second_good = _feature_xml(("Fixed", "Now with intent."))
        calls = _patch_cli_sequence(monkeypatch, [first_bad, second_good])

        asyncio.run(generate_feature_expansion({"project_id": seeded_project, "feedback": None}))

        retry_prompt = calls[1]["prompt"]
        # The retry prompt should reference the previous bad output
        # (via the "Current draft" section) and the parse error.
        assert "<name>OnlyName</name>" in retry_prompt
        assert "missing an <intent>" in retry_prompt


class TestProjectSettingsTimeout:
    """The handler reads ``generation_timeout_seconds`` from the
    project's settings column and passes it to the CLI invocation.
    """

    def test_default_timeout_is_900_when_settings_is_null(
        self, shared_session_factory, seeded_project, monkeypatch
    ):
        calls = _patch_cli(monkeypatch)
        asyncio.run(generate_feature_expansion({"project_id": seeded_project, "feedback": None}))
        assert len(calls) == 1
        assert calls[0]["timeout"] == 900

    def test_uses_override_when_settings_is_populated(
        self, shared_session_factory, seeded_project, monkeypatch
    ):
        # Set a custom timeout on the project row.
        factory = shared_session_factory
        s = factory()
        try:
            from backend.models import Project

            project = s.get(Project, seeded_project)
            assert project is not None
            project.settings = {"generation_timeout_seconds": 1500}
            s.commit()
        finally:
            s.close()

        calls = _patch_cli(monkeypatch)
        asyncio.run(generate_feature_expansion({"project_id": seeded_project, "feedback": None}))
        assert len(calls) == 1
        assert calls[0]["timeout"] == 1500


def _patch_cli_mixed(
    monkeypatch,
    outcomes: list,  # list of str | Exception
    *,
    prompt_tokens: int = 100,
    completion_tokens: int = 50,
    model: str = "claude-sonnet-4-6",
):
    """Patch the CLI with a sequence of outcomes where each entry is
    either a string (returned as GenerationResult text) or an
    Exception instance (raised). Used by transient-retry tests to
    simulate 'upstream 500 then success' patterns.
    """
    import backend.graph.handlers.feature_expansion as _handler_mod
    from backend.cli.manager import GenerationResult

    calls: list[dict] = []
    remaining = list(outcomes)

    async def fake(**kwargs):
        calls.append(kwargs)
        if not remaining:
            raise RuntimeError("CLI mock exhausted — test called it too many times")
        outcome = remaining.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return GenerationResult(
            text=outcome,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            model=model,
        )

    monkeypatch.setattr(_handler_mod.cli_manager, "generate_with_usage", fake)
    return calls


class TestTransientCLIRetry:
    """The handler retries the CLI when it fails non-deterministically
    (upstream Anthropic 5xx, process crash, etc.) with exponential
    backoff. This is separate from the parse-validate retry loop:
    this handles "we never got output" rather than "we got bad
    output".
    """

    def test_transient_failure_then_success(
        self, shared_session_factory, seeded_project, monkeypatch
    ):
        good = _feature_xml(("Recovered", "After one flake."))
        calls = _patch_cli_mixed(
            monkeypatch,
            [RuntimeError("API Error: 500 transient blip"), good],
        )

        asyncio.run(generate_feature_expansion({"project_id": seeded_project, "feedback": None}))

        # Two CLI calls: the failed one and the successful retry.
        assert len(calls) == 2
        session = shared_session_factory()
        try:
            drafts = list(
                session.execute(select(Draft).where(Draft.project_id == seeded_project)).scalars()
            )
            assert len(drafts) == 1
            assert drafts[0].content == good
            # Only the successful call produced telemetry — failed
            # CLI calls never reach the attempts list.
            rows = list(
                session.execute(
                    select(GenerationTelemetry).where(
                        GenerationTelemetry.project_id == seeded_project
                    )
                ).scalars()
            )
            assert len(rows) == 1
        finally:
            session.close()

    def test_transient_retry_exhaustion_raises(
        self, shared_session_factory, seeded_project, monkeypatch
    ):
        # Every CLI call fails with a RuntimeError. The handler retries
        # CLI_MAX_TRANSIENT_RETRIES + 1 times total before bubbling
        # the final error.
        total_attempts = CLI_MAX_TRANSIENT_RETRIES + 1
        failures = [RuntimeError(f"API Error: 500 #{i}") for i in range(total_attempts)]
        calls = _patch_cli_mixed(monkeypatch, failures)

        with pytest.raises(RuntimeError, match="API Error: 500"):
            asyncio.run(
                generate_feature_expansion({"project_id": seeded_project, "feedback": None})
            )

        assert len(calls) == total_attempts

        # No draft, no telemetry: the handler bubbled out before
        # committing anything.
        session = shared_session_factory()
        try:
            drafts = list(
                session.execute(select(Draft).where(Draft.project_id == seeded_project)).scalars()
            )
            assert drafts == []
            tlm = list(
                session.execute(
                    select(GenerationTelemetry).where(
                        GenerationTelemetry.project_id == seeded_project
                    )
                ).scalars()
            )
            assert tlm == []
        finally:
            session.close()

    def test_transient_retry_composes_with_parse_retry(
        self, shared_session_factory, seeded_project, monkeypatch
    ):
        # First call flakes (RuntimeError), retry succeeds but with
        # malformed output, parse-retry triggers another CLI call that
        # returns valid output. Verify the whole chain: 3 total calls,
        # final draft is the validated one.
        good = _feature_xml(("Ok", "Good output."))
        calls = _patch_cli_mixed(
            monkeypatch,
            [
                RuntimeError("API Error: 500 transient"),
                "not xml at all",
                good,
            ],
        )

        asyncio.run(generate_feature_expansion({"project_id": seeded_project, "feedback": None}))

        assert len(calls) == 3
        session = shared_session_factory()
        try:
            drafts = list(
                session.execute(select(Draft).where(Draft.project_id == seeded_project)).scalars()
            )
            assert len(drafts) == 1
            assert drafts[0].content == good
            # Two telemetry rows: the malformed-but-returned attempt
            # and the good attempt. The transient failure never made
            # it into the attempts list.
            rows = list(
                session.execute(
                    select(GenerationTelemetry).where(
                        GenerationTelemetry.project_id == seeded_project
                    )
                ).scalars()
            )
            assert len(rows) == 2
        finally:
            session.close()
