"""Tests for backend.graph.handlers.feature_mint.

The mint handler runs on the pipeline worker after the expansion
approve route enqueues it. Its job is to parse the now-committed
expansion content and mint one ``feat_*`` node per validated
``<feature>``. No LLM call — parse-validate retries live in the
generation handler.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database import Base
from backend.graph.expansion import bootstrap_expansion_node
from backend.graph.handlers.feature_mint import (
    FeatureMintHandlerError,
    mint_features,
)
from backend.models import InputDocument, Project
from backend.models.node import Node

# ── Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture()
def shared_session_factory(monkeypatch):
    """Shared in-memory engine — same pattern as the expansion handler tests.

    Points ``backend.database.SessionLocal`` and
    ``backend.graph.handlers.feature_mint.SessionLocal`` at the
    same StaticPool engine so the handler and the test see the
    same state.
    """
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    import backend.database as _database_mod
    import backend.graph.handlers.feature_mint as _handler_mod

    monkeypatch.setattr(_database_mod, "SessionLocal", factory)
    monkeypatch.setattr(_handler_mod, "SessionLocal", factory)
    yield factory
    engine.dispose()


def _seed_project_with_approved_expansion(
    factory: sessionmaker,
    approved_content: str,
) -> str:
    """Create a project with an expansion node whose content is set.

    Simulates the post-``DraftApproved`` state the mint handler
    sees in production: the expansion node's ``content`` has the
    approved ``<features>`` block committed to it, and no feat_*
    nodes have been minted yet.
    """
    session: Session = factory()
    try:
        project_id = str(uuid.uuid4())
        session.add(Project(id=project_id, name="T", git_repo_path="/tmp/t"))
        session.flush()
        session.add(
            InputDocument(
                project_id=project_id,
                name="Project Document",
                content="A mint test project.",
                doc_type="project_doc",
            )
        )
        exp_id = bootstrap_expansion_node(session, project_id)
        session.flush()
        # Simulate DraftApproved committing content to the node.
        exp_node = session.get(Node, exp_id)
        assert exp_node is not None
        exp_node.content = approved_content
        session.commit()
        return project_id
    finally:
        session.close()


def _features_xml(*features: tuple[str, str]) -> str:
    """Build a valid <features> XML string from (name, intent) pairs."""
    inner = "".join(
        f"<feature><name>{name}</name><intent>{intent}</intent></feature>"
        for name, intent in features
    )
    return f"<features>{inner}</features>"


# ── Happy path ───────────────────────────────────────────────────────


class TestHappyPath:
    def test_mints_one_feat_per_feature(self, shared_session_factory):
        approved = _features_xml(
            ("Billing", "Users pay for tiered plans via credit card."),
            ("Auth", "Users sign in with email and password."),
            ("Reporting", "Users view usage stats on a dashboard."),
        )
        pid = _seed_project_with_approved_expansion(shared_session_factory, approved)

        asyncio.run(mint_features({"project_id": pid}))

        session = shared_session_factory()
        try:
            feats = list(
                session.execute(
                    select(Node)
                    .where(Node.project_id == pid, Node.tier == "feat")
                    .order_by(Node.display_order)
                ).scalars()
            )
            assert len(feats) == 3
            assert [f.name for f in feats] == ["Billing", "Auth", "Reporting"]
            assert feats[0].content == "Users pay for tiered plans via credit card."
            assert feats[1].content == "Users sign in with email and password."
            assert feats[2].content == "Users view usage stats on a dashboard."
            # display_order reflects parse order.
            assert [f.display_order for f in feats] == [0, 1, 2]
            # parent_id is None — features are top-level siblings.
            assert all(f.parent_id is None for f in feats)
            # kind is domain by default.
            assert all(f.kind == "domain" for f in feats)
            # Each feat_* id has the expected prefix.
            assert all(f.id.startswith("feat_") for f in feats)
        finally:
            session.close()

    def test_single_feature(self, shared_session_factory):
        approved = _features_xml(("Only", "The only feature."))
        pid = _seed_project_with_approved_expansion(shared_session_factory, approved)

        asyncio.run(mint_features({"project_id": pid}))

        session = shared_session_factory()
        try:
            feats = list(
                session.execute(
                    select(Node).where(Node.project_id == pid, Node.tier == "feat")
                ).scalars()
            )
            assert len(feats) == 1
            assert feats[0].name == "Only"
            assert feats[0].content == "The only feature."
            assert feats[0].display_order == 0
        finally:
            session.close()


# ── Idempotency ──────────────────────────────────────────────────────


class TestIdempotency:
    def test_second_run_is_noop_when_features_already_exist(self, shared_session_factory):
        approved = _features_xml(("One", "first"), ("Two", "second"))
        pid = _seed_project_with_approved_expansion(shared_session_factory, approved)

        # First run mints.
        asyncio.run(mint_features({"project_id": pid}))

        session = shared_session_factory()
        try:
            first_ids = sorted(
                row[0]
                for row in session.execute(
                    select(Node.id).where(Node.project_id == pid, Node.tier == "feat")
                )
            )
        finally:
            session.close()

        # Second run is a no-op — same IDs, no new rows.
        asyncio.run(mint_features({"project_id": pid}))

        session = shared_session_factory()
        try:
            second_ids = sorted(
                row[0]
                for row in session.execute(
                    select(Node.id).where(Node.project_id == pid, Node.tier == "feat")
                )
            )
            assert second_ids == first_ids
            assert len(second_ids) == 2
        finally:
            session.close()


# ── Failure modes ────────────────────────────────────────────────────


class TestFailureModes:
    def test_missing_project_id_raises(self, shared_session_factory):
        with pytest.raises(FeatureMintHandlerError, match="project_id"):
            asyncio.run(mint_features({}))

    def test_missing_expansion_node_raises(self, shared_session_factory):
        factory = shared_session_factory
        s = factory()
        try:
            pid = str(uuid.uuid4())
            s.add(Project(id=pid, name="T", git_repo_path="/tmp/t"))
            s.commit()
        finally:
            s.close()

        with pytest.raises(FeatureMintHandlerError, match="no expansion node"):
            asyncio.run(mint_features({"project_id": pid}))

    def test_empty_expansion_content_raises(self, shared_session_factory):
        factory = shared_session_factory
        s = factory()
        try:
            pid = str(uuid.uuid4())
            s.add(Project(id=pid, name="T", git_repo_path="/tmp/t"))
            s.flush()
            bootstrap_expansion_node(s, pid)
            s.commit()
        finally:
            s.close()

        # Expansion exists but has no approved content yet — the
        # handler should refuse to run because minting from
        # nothing is a bug state.
        with pytest.raises(FeatureMintHandlerError, match="empty content"):
            asyncio.run(mint_features({"project_id": pid}))

    def test_unparseable_content_raises(self, shared_session_factory):
        # Content without a <features> block. The mint handler's
        # parse fails — this should never happen in practice
        # because generate_feature_expansion runs parse-validate
        # first, but defensive.
        pid = _seed_project_with_approved_expansion(
            shared_session_factory,
            "This is just prose, no tags at all.",
        )

        with pytest.raises(FeatureMintHandlerError, match="could not parse"):
            asyncio.run(mint_features({"project_id": pid}))

        # No feat_* nodes landed.
        session = shared_session_factory()
        try:
            count = session.query(Node).filter(Node.project_id == pid, Node.tier == "feat").count()
            assert count == 0
        finally:
            session.close()

    def test_validation_failure_raises(self, shared_session_factory):
        # <features> block is present but empty — validate_features
        # rejects zero <feature> children.
        pid = _seed_project_with_approved_expansion(
            shared_session_factory,
            "<features></features>",
        )

        with pytest.raises(FeatureMintHandlerError, match="could not parse"):
            asyncio.run(mint_features({"project_id": pid}))


# ── Event-log round trip ─────────────────────────────────────────────


class TestEventLog:
    def test_mint_emits_nodecreated_events(self, shared_session_factory):
        """Each feat_* mint should appear in the graph_events log as NodeCreated."""

        approved = _features_xml(("A", "alpha"), ("B", "beta"))
        pid = _seed_project_with_approved_expansion(shared_session_factory, approved)

        asyncio.run(mint_features({"project_id": pid}))

        session = shared_session_factory()
        try:
            # Rebuild projections from the event log and verify
            # the feat_* nodes come through. This confirms the
            # mint writes proper events, not just direct row
            # inserts.
            from backend.graph.reducer import rebuild_projections

            rebuild_projections(session, pid)
            feats = list(
                session.execute(
                    select(Node).where(Node.project_id == pid, Node.tier == "feat")
                ).scalars()
            )
            assert len(feats) == 2
            assert {f.name for f in feats} == {"A", "B"}
        finally:
            session.close()


# ── Groups + implicit mint paths ─────────────────────────────────────


class TestMintGroupsAndImplicit:
    def test_grouped_features_carry_group_label(self, shared_session_factory):
        approved = (
            "<features>"
            "<group>"
            "<name>User Management</name>"
            "<feature><name>Login</name><intent>Users sign in.</intent></feature>"
            "<feature>"
            "<name>Password Reset</name>"
            "<intent>Users reset via email.</intent>"
            "<implicit/>"
            "</feature>"
            "</group>"
            "<group>"
            "<name>Billing</name>"
            "<feature>"
            "<name>Subscription</name>"
            "<intent>Tiered plans.</intent>"
            "</feature>"
            "</group>"
            "</features>"
        )
        pid = _seed_project_with_approved_expansion(shared_session_factory, approved)
        asyncio.run(mint_features({"project_id": pid}))

        session = shared_session_factory()
        try:
            feats = list(
                session.execute(
                    select(Node)
                    .where(Node.project_id == pid, Node.tier == "feat")
                    .order_by(Node.display_order)
                ).scalars()
            )
            assert len(feats) == 3
            assert [f.name for f in feats] == ["Login", "Password Reset", "Subscription"]
            assert [f.group_label for f in feats] == [
                "User Management",
                "User Management",
                "Billing",
            ]
            assert [f.is_implicit for f in feats] == [False, True, False]
            # display_order reflects document order across groups.
            assert [f.display_order for f in feats] == [0, 1, 2]
        finally:
            session.close()

    def test_ungrouped_features_have_null_group_label(self, shared_session_factory):
        approved = _features_xml(
            ("Billing", "Users pay."),
            ("Search", "Global search."),
        )
        pid = _seed_project_with_approved_expansion(shared_session_factory, approved)
        asyncio.run(mint_features({"project_id": pid}))

        session = shared_session_factory()
        try:
            feats = list(
                session.execute(
                    select(Node).where(Node.project_id == pid, Node.tier == "feat")
                ).scalars()
            )
            assert len(feats) == 2
            assert all(f.group_label is None for f in feats)
            assert all(f.is_implicit is False for f in feats)
        finally:
            session.close()

    def test_mixed_grouped_and_ungrouped(self, shared_session_factory):
        approved = (
            "<features>"
            "<group>"
            "<name>Content</name>"
            "<feature><name>Posting</name><intent>Create posts.</intent></feature>"
            "</group>"
            "<feature><name>Search</name><intent>Global search.</intent></feature>"
            "</features>"
        )
        pid = _seed_project_with_approved_expansion(shared_session_factory, approved)
        asyncio.run(mint_features({"project_id": pid}))

        session = shared_session_factory()
        try:
            feats = list(
                session.execute(
                    select(Node)
                    .where(Node.project_id == pid, Node.tier == "feat")
                    .order_by(Node.display_order)
                ).scalars()
            )
            assert len(feats) == 2
            assert feats[0].name == "Posting"
            assert feats[0].group_label == "Content"
            assert feats[1].name == "Search"
            assert feats[1].group_label is None
        finally:
            session.close()

    def test_rebuild_preserves_group_and_implicit(self, shared_session_factory):
        """Event-log round trip restores group_label and is_implicit."""
        approved = (
            "<features>"
            "<group>"
            "<name>Auth</name>"
            "<feature>"
            "<name>Password Reset</name>"
            "<intent>Via email.</intent>"
            "<implicit/>"
            "</feature>"
            "</group>"
            "</features>"
        )
        pid = _seed_project_with_approved_expansion(shared_session_factory, approved)
        asyncio.run(mint_features({"project_id": pid}))

        session = shared_session_factory()
        try:
            from backend.graph.reducer import rebuild_projections

            rebuild_projections(session, pid)
            feat = session.execute(
                select(Node).where(Node.project_id == pid, Node.tier == "feat")
            ).scalar_one()
            assert feat.name == "Password Reset"
            assert feat.group_label == "Auth"
            assert feat.is_implicit is True
        finally:
            session.close()


class TestBroadcast:
    """B1 — Mint must fan-out NodeCreated events over SSE so the
    frontend's Requirements tab appears without a manual refresh.
    """

    def test_mint_publishes_node_created_via_broadcast(self, shared_session_factory, monkeypatch):
        import backend.graph.broadcast as broadcast_mod
        from backend.graph.broadcast import (
            BroadcastMessage,
            reset_broadcaster_for_tests,
        )

        captured: list[BroadcastMessage] = []
        reset_broadcaster_for_tests()
        broadcast_mod.get_broadcaster().publish = (  # type: ignore[method-assign]
            lambda _pid, msg: captured.append(msg)
        )

        try:
            approved = _features_xml(
                ("Billing", "Users pay for tiered plans."),
            )
            pid = _seed_project_with_approved_expansion(shared_session_factory, approved)
            asyncio.run(mint_features({"project_id": pid}))

            event_types = [m.event_type for m in captured]
            # The feat_* mint and the reqs bootstrap both emit
            # NodeCreated events that must broadcast.
            assert "NodeCreated" in event_types
            # Assert the reqs-tier bootstrap specifically broadcast —
            # that's what drives the Requirements tab to appear.
            reqs_broadcasts = [
                m
                for m in captured
                if m.event_type == "NodeCreated"
                and any(nid.startswith("reqs_") for nid in m.node_ids)
            ]
            assert reqs_broadcasts, (
                "NodeCreated(tier=reqs) was not broadcast — the frontend "
                "Requirements tab won't appear without a manual refresh."
            )
        finally:
            reset_broadcaster_for_tests()
