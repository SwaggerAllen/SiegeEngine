"""B10 — Pin that apply-AI-feedback regens carry prior content forward.

When a user hits the "apply AI feedback" button on an approved
bootstrap tier (expansion / requirements / sysarch), the
generation handler must include the approved prior content in
the user prompt so the LLM iterates on the existing draft
rather than starting from scratch. This test is defensive —
the exploration confirmed ``prior_pending or prior_approved``
flows through ``render_user_prompt()`` today; we pin the
invariant so a future prompt refactor doesn't silently regress.
"""

from __future__ import annotations

import asyncio
import os
import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

os.environ.setdefault("SIEGE_DISABLE_WORKER_LOOP", "1")
os.environ.setdefault("SIEGE_DISABLE_AI_REVIEW", "1")

from backend.cli.manager import GenerationResult
from backend.database import Base
from backend.graph import events as ev
from backend.graph.expansion import bootstrap_expansion_node
from backend.graph.handlers import feature_expansion as fe_handler
from backend.graph.handlers import requirements_generation as rq_handler
from backend.graph.handlers import sysarch_generation as sa_handler
from backend.graph.reducer import append_event
from backend.graph.requirements import bootstrap_reqs_node, get_reqs_node
from backend.graph.sysarch import bootstrap_sysarch_node, get_sysarch_node
from backend.models import InputDocument, Project


@pytest.fixture(autouse=True)
def _fast_cli_retry_backoff(monkeypatch):
    import backend.graph.handlers.feature_expansion as _fe

    monkeypatch.setattr(
        _fe,
        "CLI_RETRY_BACKOFF_SECONDS",
        (0.0,) * (_fe.CLI_MAX_TRANSIENT_RETRIES + 1),
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

    monkeypatch.setattr(_database_mod, "SessionLocal", factory)
    monkeypatch.setattr(fe_handler, "SessionLocal", factory)
    monkeypatch.setattr(rq_handler, "SessionLocal", factory)
    monkeypatch.setattr(sa_handler, "SessionLocal", factory)
    yield factory
    engine.dispose()


_APPROVED_EXPANSION_MARKER = "APPROVED_EXPANSION_SENTINEL_TOKEN"
_APPROVED_REQS_MARKER = "APPROVED_REQS_SENTINEL_TOKEN"
_APPROVED_SYSARCH_MARKER = "APPROVED_SYSARCH_SENTINEL_TOKEN"


def _valid_expansion_output() -> str:
    return (
        "<introduction>Regenerated intro.</introduction>"
        "<features>"
        "<feature><name>X</name><intent>Ok intent.</intent></feature>"
        "</features>"
        "<vocabulary>"
        '<term name="t" scope="project">'
        "<vocab-entry><definition>stub.</definition></vocab-entry>"
        "</term>"
        "</vocabulary>"
    )


def _valid_reqs_output(feat_id: str) -> str:
    feats = f'<feats><feat id="{feat_id}"/></feats>'
    return (
        "<introduction>Regenerated reqs intro.</introduction>"
        "<requirements>"
        f"<responsibility><name>session lifecycle</name>{feats}</responsibility>"
        "</requirements>"
    )


def _valid_sysarch_output(resp_id: str) -> str:
    return (
        "<introduction>Regenerated sysarch intro.</introduction>"
        "<sysarch>"
        "<techspec>Typical Python + React stack.</techspec>"
        "<components>"
        '<component alias="foundation">'
        "<name>Foundation</name><kind>domain</kind>"
        "<role>Project root.</role>"
        "<api-intent>load_settings().</api-intent>"
        "<failure-surface>Settings crash aborts startup.</failure-surface>"
        f'<responsibilities><resp id="{resp_id}"/></responsibilities>'
        "<foundation/>"
        "</component>"
        "</components>"
        "<policies></policies>"
        "<dependencies></dependencies>"
        "<domain-parent></domain-parent>"
        "</sysarch>"
    )


def _seed_project(factory: sessionmaker) -> str:
    session: Session = factory()
    try:
        pid = str(uuid.uuid4())
        session.add(Project(id=pid, name="T", git_repo_path="/tmp/t"))
        session.flush()
        session.add(
            InputDocument(
                project_id=pid,
                name="Project Document",
                content="Pin test input doc.",
                doc_type="project_doc",
            )
        )
        bootstrap_expansion_node(session, pid)
        session.commit()
        return pid
    finally:
        session.close()


class TestExpansionRegenCarriesPrior:
    def test_prior_approved_content_reaches_prompt(self, shared_session_factory, monkeypatch):
        pid = _seed_project(shared_session_factory)

        # Set approved content containing a distinctive sentinel string.
        session = shared_session_factory()
        try:
            from backend.graph.expansion import get_expansion_node

            node = get_expansion_node(session, pid)
            assert node is not None
            node.content = f"<features>{_APPROVED_EXPANSION_MARKER}</features>"
            session.commit()
        finally:
            session.close()

        captured: list[dict] = []

        async def fake(**kwargs):
            captured.append(kwargs)
            return GenerationResult(
                text=_valid_expansion_output(),
                prompt_tokens=1,
                completion_tokens=1,
                model="stub",
            )

        monkeypatch.setattr(fe_handler.cli_manager, "generate_with_usage", fake)

        asyncio.run(fe_handler.generate_feature_expansion({"project_id": pid, "feedback": "tweak"}))

        assert captured, "CLI was never called"
        user_prompt = captured[0]["prompt"]
        assert _APPROVED_EXPANSION_MARKER in user_prompt, (
            "Regeneration with feedback must include the approved prior "
            "content in the user prompt. The LLM can only iterate on the "
            "existing draft when it sees the prior version."
        )


class TestRequirementsRegenCarriesPrior:
    def test_prior_approved_content_reaches_prompt(self, shared_session_factory, monkeypatch):
        pid = _seed_project(shared_session_factory)

        # Mint a feature + reqs node so the handler can run.
        session = shared_session_factory()
        try:
            feat_id = "feat_TESTAAAA"
            append_event(
                session,
                pid,
                ev.NodeCreated(
                    node_id=feat_id,
                    tier="feat",
                    kind="domain",
                    parent_id=None,
                    name="Billing",
                    content="Users pay.",
                ),
            )
            bootstrap_reqs_node(session, pid)
            reqs = get_reqs_node(session, pid)
            assert reqs is not None
            reqs.content = f"<requirements>{_APPROVED_REQS_MARKER}</requirements>"
            session.commit()
        finally:
            session.close()

        captured: list[dict] = []

        async def fake(**kwargs):
            captured.append(kwargs)
            return GenerationResult(
                text=_valid_reqs_output(feat_id),
                prompt_tokens=1,
                completion_tokens=1,
                model="stub",
            )

        # All tier handlers route through the shared CLI manager
        # via ``_bootstrap_generation._call_cli_with_transient_retry``,
        # which imports ``cli_manager`` from the feature_expansion
        # module. Patch once, reach every tier.
        monkeypatch.setattr(fe_handler.cli_manager, "generate_with_usage", fake)

        asyncio.run(rq_handler.generate_requirements({"project_id": pid, "feedback": "tighten"}))

        assert captured, "CLI was never called"
        user_prompt = captured[0]["prompt"]
        assert _APPROVED_REQS_MARKER in user_prompt


class TestSysarchRegenCarriesPrior:
    def test_prior_approved_content_reaches_prompt(self, shared_session_factory, monkeypatch):
        pid = _seed_project(shared_session_factory)

        session = shared_session_factory()
        try:
            # Mint a top-level resp the sysarch output references.
            resp_id = "resp_TESTAAAA"
            append_event(
                session,
                pid,
                ev.NodeCreated(
                    node_id=resp_id,
                    tier="resp",
                    kind="domain",
                    parent_id=None,
                    name="Foundation",
                    content="Project root.",
                ),
            )
            bootstrap_sysarch_node(session, pid)
            sa = get_sysarch_node(session, pid)
            assert sa is not None
            sa.content = f"<sysarch>{_APPROVED_SYSARCH_MARKER}</sysarch>"
            session.commit()
        finally:
            session.close()

        captured: list[dict] = []

        async def fake(**kwargs):
            captured.append(kwargs)
            return GenerationResult(
                text=_valid_sysarch_output(resp_id),
                prompt_tokens=1,
                completion_tokens=1,
                model="stub",
            )

        monkeypatch.setattr(fe_handler.cli_manager, "generate_with_usage", fake)

        asyncio.run(sa_handler.generate_sysarch({"project_id": pid, "feedback": "adjust"}))

        assert captured, "CLI was never called"
        user_prompt = captured[0]["prompt"]
        assert _APPROVED_SYSARCH_MARKER in user_prompt
