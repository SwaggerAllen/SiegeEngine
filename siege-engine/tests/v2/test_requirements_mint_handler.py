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


def _owns(*feat_ids: str) -> str:
    return "<owns>" + "".join(f'<feat id="{fid}"/>' for fid in feat_ids) + "</owns>"


def _supports(*feat_ids: str) -> str:
    return "<supports>" + "".join(f'<feat id="{fid}"/>' for fid in feat_ids) + "</supports>"


def _reqs_block(feat_ids: list[str], *entries: tuple[str, str]) -> str:
    """Build a valid <requirements> block that satisfies the
    single-owner rule: the first responsibility primary-owns
    every feature in ``feat_ids``; subsequent responsibilities
    list every feature under ``<supports>``. Keeps the "all
    responsibilities touch every feature" semantics the tests
    rely on while remaining valid under the ownership split.
    """
    if not entries:
        return "<requirements></requirements>"
    rows: list[str] = []
    for i, (name, intent) in enumerate(entries):
        if i == 0:
            body = _owns(*feat_ids)
        else:
            # Secondary responsibilities need at least one owned
            # feature of their own. Give each a distinct stub by
            # having it primary-own the feature at its index
            # (wrapping if entries exceed feat_ids), and support
            # the rest. The first responsibility then primary-owns
            # everything not claimed by a later one — the loop
            # rewrites its owns block at the end.
            owned = (feat_ids[i % len(feat_ids)],)
            supported = tuple(f for f in feat_ids if f not in owned)
            body = _owns(*owned) + (_supports(*supported) if supported else "")
        rows.append(
            f"<responsibility><name>{name}</name>"
            f"<scope><item>scope for {name}</item></scope>"
            f"<failure-surface>{name} failure surface.</failure-surface>"
            f"{body}</responsibility>"
        )
    # Re-bind the first entry's owned set to be feat_ids minus
    # everything the later entries claimed, so we don't double-own.
    claimed_by_others: set[str] = set()
    for i in range(1, len(entries)):
        claimed_by_others.add(feat_ids[i % len(feat_ids)])
    first_owned = tuple(f for f in feat_ids if f not in claimed_by_others)
    if not first_owned:
        # Every feature got claimed by a later entry — give the
        # first resp supports-only with a stub owned feat so it
        # still has a single-owner. Rare in tests, but possible
        # when entries > feat_ids.
        first_owned = (feat_ids[0],)
        claimed_by_others.discard(feat_ids[0])
    first_supports = tuple(f for f in feat_ids if f not in first_owned)
    first_name, first_intent = entries[0]
    first_body = _owns(*first_owned) + (_supports(*first_supports) if first_supports else "")
    rows[0] = (
        f"<responsibility><name>{first_name}</name>"
        f"<scope><item>scope for {first_name}</item></scope>"
        f"<failure-surface>{first_name} failure surface.</failure-surface>"
        f"{first_body}</responsibility>"
    )
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
                ("Auth", "Identify callers."),
                ("Billing", "Bill accounts."),
                ("Telemetry", "Record every call."),
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
            assert [r.name for r in resps] == ["Auth", "Billing", "Telemetry"]
            # Under the scope-list grammar the resp's ``content`` is
            # synthesized from ``scope`` + ``failure_surface`` —
            # prose intent is gone.
            assert [r.content for r in resps] == [
                "Owns: scope for Auth.\nFailure surface: Auth failure surface.",
                "Owns: scope for Billing.\nFailure surface: Billing failure surface.",
                "Owns: scope for Telemetry.\nFailure surface: Telemetry failure surface.",
            ]
            assert all(r.id.startswith("resp_") for r in resps)
            assert [r.display_order for r in resps] == [0, 1, 2]

            # Each of the 3 resps primary-owns one of the 3
            # features and supports the other two (per the
            # _reqs_block helper's single-owner distribution).
            # Total decomposition edges: 3 owns + 6 supports = 9.
            edges = list(
                s.execute(
                    select(Edge).where(
                        Edge.project_id == project_id,
                        Edge.edge_type == "decomposition",
                    )
                ).scalars()
            )
            assert len(edges) == 9
            for e in edges:
                assert e.source_id in feat_ids
                assert any(e.target_id == r.id for r in resps)
                assert e.id.startswith("edge_")
        finally:
            s.close()

    def test_partial_coverage_across_resps(self, shared_session_factory):
        # Each resp covers only one feature; together they cover
        # both features (coverage check passes) and produce exactly
        # 2 edges.
        factory = shared_session_factory
        s = factory()
        try:
            project_id, feat_ids = _seed_project_with_features_and_reqs(s, ["FeatA", "FeatB"])
            content = (
                "<requirements>"
                f"<responsibility><name>Auth</name><scope><item>test scope phrase 3</item></scope><failure-surface>Test failure surface 3.</failure-surface>"  # noqa: E501
                f'<owns><feat id="{feat_ids[0]}"/></owns>'
                "</responsibility>"
                f"<responsibility><name>Billing</name><scope><item>test scope phrase 4</item></scope><failure-surface>Test failure surface 4.</failure-surface>"  # noqa: E501
                f'<owns><feat id="{feat_ids[1]}"/></owns>'
                "</responsibility>"
                "</requirements>"
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
            assert len(edges) == 2
            sources = {e.source_id for e in edges}
            assert sources == set(feat_ids)
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
                ("Auth", "A."),
                ("Billing", "B."),
                ("Telemetry", "T."),
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
            assert count_edges == 9  # Not 18 (after second run)
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
        # orphaned resp set.
        factory = shared_session_factory
        s = factory()
        try:
            project_id, feat_ids = _seed_project_with_features_and_reqs(s, ["FeatA", "FeatB"])
            # Content covers only the first feature
            partial = (
                "<requirements>"
                f"<responsibility><name>Auth</name><scope><item>test scope phrase 5</item></scope><failure-surface>Test failure surface 5.</failure-surface>"  # noqa: E501
                f'<owns><feat id="{feat_ids[0]}"/></owns>'
                "</responsibility>"
                "</requirements>"
            )
            _set_reqs_content(s, project_id, partial)
        finally:
            s.close()
        with pytest.raises(RequirementsMintHandlerError, match="features with no owner"):
            asyncio.run(mint_requirements({"project_id": project_id}))


class TestSysarchBootstrapFanOut:
    def test_bootstraps_sysarch_node_and_enqueues_generation(self, shared_session_factory):
        factory = shared_session_factory
        s = factory()
        try:
            project_id, feat_ids = _seed_project_with_features_and_reqs(s, ["FeatA", "FeatB"])
            content = _reqs_block(feat_ids, ("Auth", "Identify."))
            _set_reqs_content(s, project_id, content)
        finally:
            s.close()

        asyncio.run(mint_requirements({"project_id": project_id}))

        s = factory()
        try:
            # Sysarch bootstrap node exists
            sysarch_nodes = list(
                s.execute(
                    select(Node).where(Node.project_id == project_id, Node.tier == "sysarch")
                ).scalars()
            )
            assert len(sysarch_nodes) == 1
            assert sysarch_nodes[0].id.startswith("sysarch_")
            # Empty content until the generation handler produces a draft
            assert sysarch_nodes[0].content == ""

            # v2.generate_sysarch job enqueued
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
            _set_reqs_content(s, project_id, _reqs_block(feat_ids, ("Auth", "Ok.")))
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
