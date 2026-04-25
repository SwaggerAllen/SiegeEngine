"""Tests for backend.graph.handlers.requirements_mint.

Mirrors test_feature_mint_handler.py's shape. The mint handler
is deterministic (no LLM call) and idempotent. It emits both
``resp_*`` nodes and ``decomposition`` edges (``feat_* → resp_*``)
in one transaction.
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
from backend.graph.handlers.requirements_mint import (
    RequirementsMintHandlerError,
    mint_requirements,
)
from backend.graph.reducer import append_event
from backend.graph.requirements import bootstrap_reqs_node
from backend.models import Project
from backend.models.job import Job
from backend.models.node import Edge, Node


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


def _seed_project_with_features_and_reqs(
    session: Session, feature_names: list[str]
) -> tuple[str, list[str]]:
    """Create a project with the given feature names plus a reqs
    node. Returns ``(project_id, [feat_id, ...])``. Caller is
    responsible for committing and for writing approved content
    to the reqs node via ``_set_reqs_content``.
    """
    project_id = str(uuid.uuid4())
    session.add(Project(id=project_id, name="T", git_repo_path="/tmp/t"))
    session.flush()
    feat_ids = [_mint_feature(session, project_id, name, i) for i, name in enumerate(feature_names)]
    bootstrap_reqs_node(session, project_id)
    session.commit()
    return project_id, feat_ids


def _set_reqs_content(session: Session, project_id: str, content: str) -> None:
    """Simulate DraftApproved by writing content directly to the
    reqs node. Avoids going through the reducer's approval
    machinery just to seed a test fixture.
    """
    node = session.execute(
        select(Node).where(Node.project_id == project_id, Node.tier == "reqs")
    ).scalar_one()
    node.content = content
    session.commit()


def _resp(name: str, feat_ids: tuple[str, ...]) -> str:
    feats_xml = "".join(f'<feat id="{fid}"/>' for fid in feat_ids)
    return f"<responsibility><name>{name}</name><feats>{feats_xml}</feats></responsibility>"


def _reqs_block(feat_ids: list[str], *names: str) -> str:
    """Build a valid <requirements> block where every atom tags
    every feature. Simplest fixture satisfying feat-coverage under
    the atomic grammar.
    """
    if not names:
        return "<requirements></requirements>"
    rows = [_resp(name, tuple(feat_ids)) for name in names]
    return f"<requirements>{''.join(rows)}</requirements>"


class TestHappyPath:
    def test_mints_top_level_resp_nodes_and_edges(self, shared_session_factory):
        factory = shared_session_factory
        s = factory()
        try:
            project_id, feat_ids = _seed_project_with_features_and_reqs(
                s, ["FeatA", "FeatB", "FeatC"]
            )
            content = _reqs_block(
                feat_ids,
                "session lifecycle",
                "invoice emission",
                "event log",
            )
            _set_reqs_content(s, project_id, content)
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
            assert [r.name for r in resps] == [
                "session lifecycle",
                "invoice emission",
                "event log",
            ]
            # Under the atomic grammar the resp's ``content`` is
            # just the atom name (the scope phrase verbatim).
            assert [r.content for r in resps] == [
                "session lifecycle",
                "invoice emission",
                "event log",
            ]
            assert all(r.id.startswith("resp_") for r in resps)
            assert [r.display_order for r in resps] == [0, 1, 2]

            # Every atom tags all 3 feats → 3 resps × 3 feats = 9
            # feat→resp decomposition edges. Plus one feat→reqs
            # decomposition edge per feat (3 feats) for the
            # staleness-cascade walk → 12 total.
            edges = list(
                s.execute(
                    select(Edge).where(
                        Edge.project_id == project_id,
                        Edge.edge_type == "decomposition",
                    )
                ).scalars()
            )
            assert len(edges) == 12
            resp_ids = {r.id for r in resps}
            reqs_node = s.execute(
                select(Node).where(Node.project_id == project_id, Node.tier == "reqs")
            ).scalar_one()
            feat_to_resp_edges = [e for e in edges if e.target_id in resp_ids]
            feat_to_reqs_edges = [e for e in edges if e.target_id == reqs_node.id]
            assert len(feat_to_resp_edges) == 9
            assert len(feat_to_reqs_edges) == 3
            for e in edges:
                assert e.source_id in feat_ids
                assert e.id.startswith("edge_")
            assert {e.source_id for e in feat_to_reqs_edges} == set(feat_ids)
        finally:
            s.close()

    def test_partial_coverage_across_resps(self, shared_session_factory):
        # Each atom tags one feat; together they cover both and
        # produce exactly 2 feat→resp edges. Plus 2 feat→reqs
        # edges (one per feat) → 4 total.
        factory = shared_session_factory
        s = factory()
        try:
            project_id, feat_ids = _seed_project_with_features_and_reqs(s, ["FeatA", "FeatB"])
            content = (
                "<requirements>"
                + _resp("session lifecycle", (feat_ids[0],))
                + _resp("invoice emission", (feat_ids[1],))
                + "</requirements>"
            )
            _set_reqs_content(s, project_id, content)
        finally:
            s.close()

        asyncio.run(mint_requirements({"project_id": project_id}))

        s = factory()
        try:
            edges = list(
                s.execute(
                    select(Edge).where(
                        Edge.project_id == project_id,
                        Edge.edge_type == "decomposition",
                    )
                ).scalars()
            )
            assert len(edges) == 4
            reqs_node = s.execute(
                select(Node).where(Node.project_id == project_id, Node.tier == "reqs")
            ).scalar_one()
            feat_to_reqs = [e for e in edges if e.target_id == reqs_node.id]
            feat_to_resp = [e for e in edges if e.target_id != reqs_node.id]
            assert len(feat_to_reqs) == 2
            assert len(feat_to_resp) == 2
            assert {e.source_id for e in edges} == set(feat_ids)
        finally:
            s.close()


class TestIdempotency:
    def test_second_run_skips(self, shared_session_factory):
        factory = shared_session_factory
        s = factory()
        try:
            project_id, feat_ids = _seed_project_with_features_and_reqs(
                s, ["FeatA", "FeatB", "FeatC"]
            )
            content = _reqs_block(
                feat_ids,
                "session lifecycle",
                "invoice emission",
                "event log",
            )
            _set_reqs_content(s, project_id, content)
        finally:
            s.close()

        asyncio.run(mint_requirements({"project_id": project_id}))
        asyncio.run(mint_requirements({"project_id": project_id}))

        s = factory()
        try:
            count_resps = len(
                list(
                    s.execute(
                        select(Node).where(
                            Node.project_id == project_id,
                            Node.tier == "resp",
                            Node.parent_id.is_(None),
                        )
                    ).scalars()
                )
            )
            assert count_resps == 3  # Not 6
            count_edges = len(
                list(
                    s.execute(
                        select(Edge).where(
                            Edge.project_id == project_id,
                            Edge.edge_type == "decomposition",
                        )
                    ).scalars()
                )
            )
            # 9 feat→resp edges + 3 feat→reqs edges = 12 (not 24
            # after second run — idempotency guard short-circuits).
            assert count_edges == 12
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
            project_id, _ = _seed_project_with_features_and_reqs(s, ["FeatA"])
        finally:
            s.close()
        with pytest.raises(RequirementsMintHandlerError, match="empty content"):
            asyncio.run(mint_requirements({"project_id": project_id}))

    def test_malformed_content_raises(self, shared_session_factory):
        factory = shared_session_factory
        s = factory()
        try:
            project_id, _ = _seed_project_with_features_and_reqs(s, ["FeatA"])
            _set_reqs_content(s, project_id, "not xml at all")
        finally:
            s.close()
        with pytest.raises(RequirementsMintHandlerError, match="could not parse"):
            asyncio.run(mint_requirements({"project_id": project_id}))

    def test_uncovered_feature_raises(self, shared_session_factory):
        # Mint-time coverage check: if content was approved with
        # coverage valid at generation time but a feature was added
        # after approval, the mint handler's parse-validate pass
        # catches it and refuses to mint rather than emit an
        # incomplete atom set.
        factory = shared_session_factory
        s = factory()
        try:
            project_id, feat_ids = _seed_project_with_features_and_reqs(s, ["FeatA", "FeatB"])
            partial = (
                "<requirements>" + _resp("session lifecycle", (feat_ids[0],)) + "</requirements>"
            )
            _set_reqs_content(s, project_id, partial)
        finally:
            s.close()
        with pytest.raises(RequirementsMintHandlerError, match="no atom tag"):
            asyncio.run(mint_requirements({"project_id": project_id}))


class TestSysarchBootstrapFanOut:
    def test_bootstraps_sysarch_node_and_enqueues_generation(self, shared_session_factory):
        factory = shared_session_factory
        s = factory()
        try:
            project_id, feat_ids = _seed_project_with_features_and_reqs(s, ["FeatA", "FeatB"])
            content = _reqs_block(feat_ids, "session lifecycle")
            _set_reqs_content(s, project_id, content)
        finally:
            s.close()

        asyncio.run(mint_requirements({"project_id": project_id}))

        s = factory()
        try:
            sysarch_nodes = list(
                s.execute(
                    select(Node).where(Node.project_id == project_id, Node.tier == "sysarch")
                ).scalars()
            )
            assert len(sysarch_nodes) == 1
            assert sysarch_nodes[0].id.startswith("sysarch_")
            assert sysarch_nodes[0].content == ""

            jobs = list(
                s.execute(select(Job).where(Job.job_type == "v2.generate_sysarch")).scalars()
            )
            assert any(j.payload.get("project_id") == project_id for j in jobs)
        finally:
            s.close()

    def test_does_not_re_bootstrap_on_idempotent_rerun(self, shared_session_factory):
        factory = shared_session_factory
        s = factory()
        try:
            project_id, feat_ids = _seed_project_with_features_and_reqs(s, ["FeatA"])
            _set_reqs_content(s, project_id, _reqs_block(feat_ids, "session lifecycle"))
        finally:
            s.close()

        asyncio.run(mint_requirements({"project_id": project_id}))
        asyncio.run(mint_requirements({"project_id": project_id}))

        s = factory()
        try:
            sysarch_nodes = list(
                s.execute(
                    select(Node).where(Node.project_id == project_id, Node.tier == "sysarch")
                ).scalars()
            )
            assert len(sysarch_nodes) == 1  # not 2
        finally:
            s.close()
