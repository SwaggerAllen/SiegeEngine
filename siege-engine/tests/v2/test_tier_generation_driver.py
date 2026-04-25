"""Tests for backend.graph.handlers._tier_generation.

Exercises the shared driver against a minimal synthetic config so
the per-tier callables don't pollute the test surface. The driver
delegates to ``run_parse_validate_loop`` and ``persist_draft``
which are tested elsewhere — these tests verify driver-level
ordering, payload parsing, readiness handling, and post-persist
hook semantics.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.cli.config import CliInvocationConfig
from backend.cli.manager import GenerationResult
from backend.database import Base
from backend.graph import events as ev
from backend.graph.handlers._tier_generation import (
    MAX_AUTO_REVISIONS,
    TierDeferredError,
    TierGenerationConfig,
    TierPreconditionError,
    is_ready_to_generate,
    run_tier_generation,
)
from backend.graph.ids import Kind, mint
from backend.graph.reducer import append_event
from backend.models import Project
from backend.models.node import Draft


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
    import backend.graph.handlers._bootstrap_generation as _bootstrap_mod
    import backend.graph.handlers._tier_generation as _driver_mod
    import backend.pipeline.queue as _pipeline_queue_mod

    monkeypatch.setattr(_database_mod, "SessionLocal", factory)
    monkeypatch.setattr(_bootstrap_mod, "SessionLocal", factory, raising=False)
    monkeypatch.setattr(_driver_mod, "SessionLocal", factory, raising=False)
    monkeypatch.setattr(_pipeline_queue_mod, "SessionLocal", factory, raising=False)
    yield factory
    engine.dispose()


@dataclass
class _MinimalState:
    """Smallest possible TierState satisfying the driver's reads."""

    node_id: str
    prior_approved: str | None
    prior_pending: str | None
    prior_pending_id: str | None
    cli_config: CliInvocationConfig
    system_prompt: str
    # Extra fields the synthetic render/validate use:
    seen_kwargs: dict


def _seed_project_and_node(factory, *, content: str = "") -> tuple[str, str]:
    s: Session = factory()
    try:
        project_id = str(uuid.uuid4())
        s.add(Project(id=project_id, name="T", git_repo_path="/tmp/t"))
        s.flush()
        node_id = mint(s, Kind.RESP)
        append_event(
            s,
            project_id,
            ev.NodeCreated(
                node_id=node_id,
                tier="resp",
                kind="domain",
                parent_id=None,
                name="TestNode",
                content=content,
            ),
        )
        s.commit()
        return project_id, node_id
    finally:
        s.close()


_VALID_OUTPUT = "<test><body>ok</body></test>"


def _patch_cli(monkeypatch, return_value: str = _VALID_OUTPUT):
    """Stub _call_cli_with_transient_retry inside _bootstrap_generation."""
    import backend.graph.handlers._bootstrap_generation as _mod

    async def fake(*, prompt, system_prompt, tools, config):
        return GenerationResult(
            text=return_value,
            prompt_tokens=10,
            completion_tokens=5,
            model="test-model",
        )

    monkeypatch.setattr(_mod, "_call_cli_with_transient_retry", fake)


def _make_config(
    *,
    tier_name="test_tier",
    readiness_check=None,
    post_persist_hooks=(),
    max_auto_revisions=0,
    review_job_type="",
    scope_payload_keys=(),
    capture_render: list | None = None,
) -> TierGenerationConfig:
    cli_config = CliInvocationConfig(
        timeout_seconds=10,
        max_budget_usd=1.0,
        max_output_tokens=1000,
    )

    def gather_state(db, project_id, scope_ids):
        from backend.models.node import Node

        # The first scope id (if any) is the node id; otherwise the
        # synthetic test seeds a single resp_*.
        if scope_ids:
            node_id = scope_ids[0]
        else:
            node = db.query(Node).filter(Node.project_id == project_id, Node.tier == "resp").first()
            assert node is not None
            node_id = node.id
        from backend.models.node import Node as NodeModel

        node = db.get(NodeModel, node_id)
        assert node is not None
        return _MinimalState(
            node_id=node_id,
            prior_approved=node.content or None,
            prior_pending=None,
            prior_pending_id=None,
            cli_config=cli_config,
            system_prompt="test system prompt",
            seen_kwargs={},
        )

    def render_prompt(state, *, prior_pending, parse_error, feedback, prior_review):
        if capture_render is not None:
            capture_render.append(
                {
                    "prior_pending": prior_pending,
                    "parse_error": parse_error,
                    "feedback": feedback,
                    "prior_review": prior_review,
                }
            )
        return f"USER PROMPT for {state.node_id}"

    def validate(tree, raw, state):
        # No-op — _VALID_OUTPUT parses cleanly under root_tag="test".
        return None

    return TierGenerationConfig(
        tier_name=tier_name,
        generate_job_type=f"v2.generate_{tier_name}",
        section=tier_name,
        root_tag="test",
        exhausted_exception_cls=RuntimeError,
        gather_state=gather_state,
        render_prompt=render_prompt,
        validate=validate,
        review_job_type=review_job_type,
        scope_payload_keys=scope_payload_keys,
        max_auto_revisions=max_auto_revisions,
        readiness_check=readiness_check,
        post_persist_hooks=post_persist_hooks,
    )


class TestPayloadParsing:
    def test_missing_project_id_raises(self, shared_session_factory):
        config = _make_config()
        with pytest.raises(ValueError, match="project_id"):
            asyncio.run(run_tier_generation({}, config))

    def test_missing_scope_id_raises(self, shared_session_factory):
        config = _make_config(scope_payload_keys=("component_id",))
        with pytest.raises(ValueError, match="component_id"):
            asyncio.run(run_tier_generation({"project_id": "p"}, config))


class TestReadinessGate:
    def test_predicate_returning_false_raises_precondition_error(
        self, shared_session_factory, monkeypatch
    ):
        _patch_cli(monkeypatch)
        factory = shared_session_factory
        project_id, _ = _seed_project_and_node(factory)

        def always_blocked(_db, _pid, _scope):
            return (False, "blocked for testing")

        config = _make_config(readiness_check=always_blocked)
        with pytest.raises(TierPreconditionError, match="blocked for testing"):
            asyncio.run(run_tier_generation({"project_id": project_id}, config))

    def test_predicate_can_raise_deferred_directly(self, shared_session_factory, monkeypatch):
        # Phase F: the predicate may raise TierDeferredError directly
        # for the retry-later path. The driver propagates it; the
        # worker (Phase F infrastructure) is responsible for the
        # clean-completion semantics.
        _patch_cli(monkeypatch)
        factory = shared_session_factory
        project_id, _ = _seed_project_and_node(factory)

        def defer(_db, _pid, _scope):
            raise TierDeferredError("dep regen still in flight")

        config = _make_config(readiness_check=defer)
        with pytest.raises(TierDeferredError, match="dep regen still in flight"):
            asyncio.run(run_tier_generation({"project_id": project_id}, config))

    def test_no_predicate_proceeds(self, shared_session_factory, monkeypatch):
        _patch_cli(monkeypatch)
        factory = shared_session_factory
        project_id, node_id = _seed_project_and_node(factory)

        config = _make_config()  # no readiness_check
        asyncio.run(run_tier_generation({"project_id": project_id}, config))

        s = factory()
        try:
            drafts = s.query(Draft).filter_by(project_id=project_id).all()
            assert len(drafts) == 1
        finally:
            s.close()

    def test_is_ready_to_generate_helper_returns_true_when_no_predicate(
        self, shared_session_factory
    ):
        config = _make_config()
        s = shared_session_factory()
        try:
            ready, reason = is_ready_to_generate(config, s, "p", ())
        finally:
            s.close()
        assert ready is True
        assert reason == ""


class TestRenderArguments:
    def test_render_receives_feedback_and_prior_review(self, shared_session_factory, monkeypatch):
        _patch_cli(monkeypatch)
        factory = shared_session_factory
        project_id, _ = _seed_project_and_node(factory)
        captured: list[dict] = []
        config = _make_config(capture_render=captured)

        asyncio.run(
            run_tier_generation(
                {
                    "project_id": project_id,
                    "feedback": "user said: tighten the boundary",
                    "prior_review_text": "## Handles\nthings to fix",
                },
                config,
            )
        )

        assert len(captured) >= 1
        first = captured[0]
        assert first["feedback"] == "user said: tighten the boundary"
        assert first["prior_review"] == "## Handles\nthings to fix"
        # parse_error is None on first attempt; prior_pending starts
        # as the gather_state-supplied value (None here since no
        # pending draft exists).
        assert first["parse_error"] is None


class TestPostPersistHooks:
    def test_hooks_run_in_declared_order(self, shared_session_factory, monkeypatch):
        _patch_cli(monkeypatch)
        factory = shared_session_factory
        project_id, _ = _seed_project_and_node(factory)

        order: list[str] = []

        def hook_a(_db, _pid, draft_id, _scope):
            order.append(f"a:{draft_id}")

        def hook_b(_db, _pid, draft_id, _scope):
            order.append(f"b:{draft_id}")

        config = _make_config(post_persist_hooks=(hook_a, hook_b))
        asyncio.run(run_tier_generation({"project_id": project_id}, config))

        assert len(order) == 2
        assert order[0].startswith("a:")
        assert order[1].startswith("b:")
        assert order[0].split(":")[1] == order[1].split(":")[1]

    def test_hook_exception_does_not_fail_job(self, shared_session_factory, monkeypatch):
        _patch_cli(monkeypatch)
        factory = shared_session_factory
        project_id, _ = _seed_project_and_node(factory)
        ran_after: list[bool] = []

        def boom(_db, _pid, _draft, _scope):
            raise RuntimeError("hook crashed")

        def survives(_db, _pid, _draft, _scope):
            ran_after.append(True)

        config = _make_config(post_persist_hooks=(boom, survives))
        # Driver should swallow the hook exception and keep going.
        asyncio.run(run_tier_generation({"project_id": project_id}, config))
        assert ran_after == [True]


class TestAutoRevisionContinuation:
    def test_disabled_when_max_auto_revisions_zero(self, shared_session_factory, monkeypatch):
        # max_auto_revisions=0 (default) — even if the payload
        # carries auto_revisions_remaining the loop is dormant.
        _patch_cli(monkeypatch)
        factory = shared_session_factory
        project_id, _ = _seed_project_and_node(factory)

        called: list[bool] = []

        async def fail_review(_payload):
            called.append(True)

        import backend.pipeline.queue as _pq_mod

        monkeypatch.setitem(_pq_mod._JOB_HANDLERS, "v2.review_test_tier", fail_review)

        config = _make_config(
            max_auto_revisions=0,
            review_job_type="v2.review_test_tier",
        )
        asyncio.run(
            run_tier_generation(
                {"project_id": project_id, "auto_revisions_remaining": 3},
                config,
            )
        )
        assert called == [], (
            "Inline review must not run when max_auto_revisions=0 regardless of payload."
        )

    def test_max_auto_revisions_constant_clamp(self):
        assert MAX_AUTO_REVISIONS == 5
