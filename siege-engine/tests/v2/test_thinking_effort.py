"""B6 — Confirm the first three tiers pass ``thinking_effort="max"`` to the CLI.

The three top-of-chain tiers (feature expansion, requirements,
sysarch) are the ones whose output quality shapes every downstream
tier. They opt into max-effort thinking via the
``thinking_effort`` kwarg on ``cli_manager.generate_with_usage``.
Propagation tiers (comparch, subcomparch, impl, fanin, reviews)
deliberately leave it unset to keep their CLI budgets from
being consumed by thinking tokens.
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

from backend.cli.manager import GenerationResult, _build_subprocess_env
from backend.database import Base
from backend.graph.expansion import bootstrap_expansion_node
from backend.graph.handlers import feature_expansion as fe_handler
from backend.models import InputDocument, Project


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
    yield factory
    engine.dispose()


def _seed_expansion(factory: sessionmaker) -> str:
    session: Session = factory()
    try:
        project_id = str(uuid.uuid4())
        session.add(Project(id=project_id, name="T", git_repo_path="/tmp/t"))
        session.flush()
        session.add(
            InputDocument(
                project_id=project_id,
                name="Project Document",
                content="Smoke test input.",
                doc_type="project_doc",
            )
        )
        bootstrap_expansion_node(session, project_id)
        session.commit()
        return project_id
    finally:
        session.close()


def _valid_features_xml() -> str:
    # Sibling <introduction> (B4) and <vocabulary> (B2) blocks
    # are both mandatory.
    return (
        "<introduction>Stub intro.</introduction>"
        "<features>"
        "<feature>"
        "<name>Onboarding</name>"
        "<intent>A new user completes first-run setup end-to-end.</intent>"
        "</feature>"
        "</features>"
        "<vocabulary>"
        '<term name="default" scope="project">'
        "<vocab-entry><definition>Stub.</definition></vocab-entry>"
        "</term>"
        "</vocabulary>"
    )


class TestBuildSubprocessEnv:
    """``_build_subprocess_env`` constructs the per-call subprocess env."""

    def test_sets_effort_level_when_provided(self):
        env = _build_subprocess_env("max")
        assert env["CLAUDE_CODE_EFFORT_LEVEL"] == "max"

    def test_strips_claudecode_and_api_key(self, monkeypatch):
        monkeypatch.setenv("CLAUDECODE", "1")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-secret")
        env = _build_subprocess_env(None)
        assert "CLAUDECODE" not in env
        assert "ANTHROPIC_API_KEY" not in env

    def test_clears_stale_effort_level_when_none(self, monkeypatch):
        monkeypatch.setenv("CLAUDE_CODE_EFFORT_LEVEL", "high")
        env = _build_subprocess_env(None)
        assert "CLAUDE_CODE_EFFORT_LEVEL" not in env

    def test_preserves_other_env(self, monkeypatch):
        monkeypatch.setenv("PATH", "/custom/path")
        env = _build_subprocess_env("max")
        assert env["PATH"] == "/custom/path"


class TestHandlerForwardsThinkingEffort:
    """The three top-of-chain handlers pass ``thinking_effort='max'``."""

    def test_feature_expansion_passes_max(self, shared_session_factory, monkeypatch):
        captured: list[dict] = []

        async def fake(**kwargs):
            captured.append(kwargs)
            return GenerationResult(
                text=_valid_features_xml(),
                prompt_tokens=1,
                completion_tokens=1,
                model="stub",
            )

        monkeypatch.setattr(fe_handler.cli_manager, "generate_with_usage", fake)

        pid = _seed_expansion(shared_session_factory)
        asyncio.run(fe_handler.generate_feature_expansion({"project_id": pid, "feedback": None}))

        assert captured, "cli_manager.generate_with_usage was never called"
        assert captured[0].get("thinking_effort") == "max", (
            f"feature expansion must pass thinking_effort='max'; kwargs keys: {list(captured[0])}"
        )
