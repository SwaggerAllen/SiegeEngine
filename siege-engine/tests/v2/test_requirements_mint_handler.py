"""Tests for backend.graph.handlers.requirements_mint.

Mirrors test_feature_mint_handler.py's shape. The mint handler
is deterministic (no LLM call) and idempotent.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database import Base
from backend.graph.handlers.requirements_mint import (
    RequirementsMintHandlerError,
    mint_requirements,
)
from backend.graph.requirements import bootstrap_reqs_node
from backend.models import Project
from backend.models.node import Node


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
    import backend.graph.handlers.requirements_mint as _handler_mod

    monkeypatch.setattr(_database_mod, "SessionLocal", factory)
    monkeypatch.setattr(_handler_mod, "SessionLocal", factory)
    yield factory
    engine.dispose()


def _seed_project_with_approved_reqs(session: Session, approved_content: str) -> str:
    """Create a project with a reqs node whose content is already
    set to ``approved_content`` (simulating post-DraftApproved state).
    """
    project_id = str(uuid.uuid4())
    session.add(Project(id=project_id, name="T", git_repo_path="/tmp/t"))
    session.flush()
    reqs_id = bootstrap_reqs_node(session, project_id)
    # Fake a DraftApproved by directly writing content. In the real
    # flow DraftApproved flows through the reducer; here we shortcut
    # because we're only testing the mint handler.
    reqs_node = session.get(Node, reqs_id)
    assert reqs_node is not None
    reqs_node.content = approved_content
    session.commit()
    return project_id


_VALID_REQS = (
    "<requirements>"
    "<responsibility><name>Auth</name><intent>Identify callers.</intent></responsibility>"
    "<responsibility><name>Billing</name><intent>Bill accounts.</intent></responsibility>"
    "<responsibility><name>Telemetry</name><intent>Record every call.</intent></responsibility>"
    "</requirements>"
)


class TestHappyPath:
    def test_mints_top_level_resp_nodes(self, shared_session_factory):
        factory = shared_session_factory
        s = factory()
        try:
            project_id = _seed_project_with_approved_reqs(s, _VALID_REQS)
        finally:
            s.close()

        asyncio.run(mint_requirements({"project_id": project_id}))

        s = factory()
        try:
            resps = list(
                s.execute(
                    select(Node)
                    .where(
                        Node.project_id == project_id,
                        Node.tier == "resp",
                        Node.parent_id.is_(None),
                    )
                    .order_by(Node.display_order)
                ).scalars()
            )
            assert [r.name for r in resps] == ["Auth", "Billing", "Telemetry"]
            assert [r.content for r in resps] == [
                "Identify callers.",
                "Bill accounts.",
                "Record every call.",
            ]
            assert all(r.id.startswith("resp_") for r in resps)
            assert [r.display_order for r in resps] == [0, 1, 2]
        finally:
            s.close()


class TestIdempotency:
    def test_second_run_skips(self, shared_session_factory):
        factory = shared_session_factory
        s = factory()
        try:
            project_id = _seed_project_with_approved_reqs(s, _VALID_REQS)
        finally:
            s.close()

        asyncio.run(mint_requirements({"project_id": project_id}))
        asyncio.run(mint_requirements({"project_id": project_id}))

        s = factory()
        try:
            count = s.execute(
                select(Node).where(
                    Node.project_id == project_id,
                    Node.tier == "resp",
                    Node.parent_id.is_(None),
                )
            ).all()
            assert len(count) == 3  # Not 6
        finally:
            s.close()


class TestFailureModes:
    def test_missing_project_id_raises(self, shared_session_factory):
        with pytest.raises(RequirementsMintHandlerError, match="project_id"):
            asyncio.run(mint_requirements({}))

    def test_missing_reqs_node_raises(self, shared_session_factory):
        factory = shared_session_factory
        s = factory()
        try:
            pid = str(uuid.uuid4())
            s.add(Project(id=pid, name="T", git_repo_path="/tmp/t"))
            s.commit()
        finally:
            s.close()
        with pytest.raises(RequirementsMintHandlerError, match="no reqs node"):
            asyncio.run(mint_requirements({"project_id": pid}))

    def test_empty_content_raises(self, shared_session_factory):
        factory = shared_session_factory
        s = factory()
        try:
            project_id = str(uuid.uuid4())
            s.add(Project(id=project_id, name="T", git_repo_path="/tmp/t"))
            s.flush()
            bootstrap_reqs_node(s, project_id)
            s.commit()
        finally:
            s.close()
        with pytest.raises(RequirementsMintHandlerError, match="empty content"):
            asyncio.run(mint_requirements({"project_id": project_id}))

    def test_malformed_content_raises(self, shared_session_factory):
        factory = shared_session_factory
        s = factory()
        try:
            project_id = _seed_project_with_approved_reqs(s, "not xml at all")
        finally:
            s.close()
        with pytest.raises(RequirementsMintHandlerError, match="could not parse"):
            asyncio.run(mint_requirements({"project_id": project_id}))
