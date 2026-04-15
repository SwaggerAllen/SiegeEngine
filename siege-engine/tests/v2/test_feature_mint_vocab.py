"""Vocab-integration tests for backend.graph.handlers.feature_mint.

Stage 3 of Phase 5.5 extends ``mint_features`` to also project
``vocab_*`` nodes from the approved expansion's optional
``<vocabulary>`` sibling block. These tests exercise the vocab
side of the mint handler alongside the existing feat side.
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
    import backend.graph.handlers.feature_mint as _handler_mod

    monkeypatch.setattr(_database_mod, "SessionLocal", factory)
    monkeypatch.setattr(_handler_mod, "SessionLocal", factory)
    yield factory
    engine.dispose()


def _seed_project_with_approved_content(
    factory: sessionmaker,
    approved_content: str,
) -> str:
    session: Session = factory()
    try:
        project_id = str(uuid.uuid4())
        session.add(Project(id=project_id, name="T", git_repo_path="/tmp/t"))
        session.flush()
        session.add(
            InputDocument(
                project_id=project_id,
                name="Project Document",
                content="Test project.",
                doc_type="project_doc",
            )
        )
        exp_id = bootstrap_expansion_node(session, project_id)
        session.flush()
        exp_node = session.get(Node, exp_id)
        assert exp_node is not None
        exp_node.content = approved_content
        session.commit()
        return project_id
    finally:
        session.close()


FEATURES_ONLY = (
    "<features>"
    "<feature><name>Billing</name><intent>Users pay for plans.</intent></feature>"
    "<feature><name>Auth</name><intent>Users sign in.</intent></feature>"
    "</features>"
)

FEATURES_PLUS_PROJECT_VOCAB = (
    "<features>"
    "<feature><name>Billing</name><intent>Users pay for plans.</intent></feature>"
    "<feature><name>Auth</name><intent>Users sign in.</intent></feature>"
    "</features>"
    "<vocabulary>"
    '<term name="boulder" scope="project">'
    "<vocab-entry>"
    "<definition>A unit of structured work with its own sub-DAG.</definition>"
    "<disambiguation>Not a leaf node in the decomposition graph.</disambiguation>"
    "</vocab-entry>"
    "</term>"
    '<term name="foundation" scope="project">'
    "<vocab-entry>"
    "<definition>The catch-all component at each decomposition level.</definition>"
    "</vocab-entry>"
    "</term>"
    "</vocabulary>"
)

FEATURES_PLUS_FEATURE_VOCAB = (
    "<features>"
    "<feature><name>Billing</name><intent>Users pay for plans.</intent></feature>"
    "<feature><name>Auth</name><intent>Users sign in.</intent></feature>"
    "</features>"
    "<vocabulary>"
    '<term name="tranche" scope="feature" feature-name="Billing">'
    "<vocab-entry>"
    "<definition>A time-bounded batch of invoices.</definition>"
    "</vocab-entry>"
    "</term>"
    '<term name="session" scope="feature" feature-name="Auth">'
    "<vocab-entry>"
    "<definition>An authenticated interaction context.</definition>"
    "</vocab-entry>"
    "</term>"
    "</vocabulary>"
)

FEATURES_PLUS_MIXED_VOCAB = (
    "<features>"
    "<feature><name>Billing</name><intent>Users pay for plans.</intent></feature>"
    "</features>"
    "<vocabulary>"
    '<term name="boulder" scope="project">'
    "<vocab-entry>"
    "<definition>Project term.</definition>"
    "</vocab-entry>"
    "</term>"
    '<term name="tranche" scope="feature" feature-name="Billing">'
    "<vocab-entry>"
    "<definition>Billing term.</definition>"
    "</vocab-entry>"
    "</term>"
    "</vocabulary>"
)


class TestFeatureMintVocabBackwardCompat:
    def test_no_vocabulary_section_mints_only_feats(self, shared_session_factory):
        project_id = _seed_project_with_approved_content(shared_session_factory, FEATURES_ONLY)
        asyncio.run(mint_features({"project_id": project_id}))

        session = shared_session_factory()
        try:
            feats = list(
                session.execute(
                    select(Node).where(Node.project_id == project_id, Node.tier == "feat")
                ).scalars()
            )
            vocab = list(
                session.execute(
                    select(Node).where(Node.project_id == project_id, Node.tier == "vocab")
                ).scalars()
            )
            assert len(feats) == 2
            assert vocab == []
        finally:
            session.close()


class TestFeatureMintProjectLevelVocab:
    def test_project_level_vocab_minted_with_null_parent(self, shared_session_factory):
        project_id = _seed_project_with_approved_content(
            shared_session_factory, FEATURES_PLUS_PROJECT_VOCAB
        )
        asyncio.run(mint_features({"project_id": project_id}))

        session = shared_session_factory()
        try:
            vocab = list(
                session.execute(
                    select(Node)
                    .where(Node.project_id == project_id, Node.tier == "vocab")
                    .order_by(Node.name)
                ).scalars()
            )
            assert len(vocab) == 2
            assert [v.name for v in vocab] == ["boulder", "foundation"]
            # Both project-level → parent_id is None
            assert all(v.parent_id is None for v in vocab)
            # Content is the raw <vocab-entry> XML
            for v in vocab:
                assert "<vocab-entry>" in v.content
                assert "<definition>" in v.content
        finally:
            session.close()

    def test_disambiguation_preserved_in_content(self, shared_session_factory):
        project_id = _seed_project_with_approved_content(
            shared_session_factory, FEATURES_PLUS_PROJECT_VOCAB
        )
        asyncio.run(mint_features({"project_id": project_id}))

        session = shared_session_factory()
        try:
            boulder = session.execute(
                select(Node).where(
                    Node.project_id == project_id,
                    Node.tier == "vocab",
                    Node.name == "boulder",
                )
            ).scalar_one()
            assert "<disambiguation>" in boulder.content
            assert "leaf node" in boulder.content
        finally:
            session.close()


class TestFeatureMintFeatureLocalVocab:
    def test_feature_local_vocab_parented_to_correct_feat(self, shared_session_factory):
        project_id = _seed_project_with_approved_content(
            shared_session_factory, FEATURES_PLUS_FEATURE_VOCAB
        )
        asyncio.run(mint_features({"project_id": project_id}))

        session = shared_session_factory()
        try:
            feats = {
                f.name: f.id
                for f in session.execute(
                    select(Node).where(Node.project_id == project_id, Node.tier == "feat")
                ).scalars()
            }
            vocab = list(
                session.execute(
                    select(Node)
                    .where(Node.project_id == project_id, Node.tier == "vocab")
                    .order_by(Node.name)
                ).scalars()
            )
            assert len(vocab) == 2
            tranche = next(v for v in vocab if v.name == "tranche")
            session_term = next(v for v in vocab if v.name == "session")
            # Each vocab entry is parented to its target feature's id.
            assert tranche.parent_id == feats["Billing"]
            assert session_term.parent_id == feats["Auth"]
        finally:
            session.close()


class TestFeatureMintMixedScopeVocab:
    def test_mixed_scope_mint(self, shared_session_factory):
        project_id = _seed_project_with_approved_content(
            shared_session_factory, FEATURES_PLUS_MIXED_VOCAB
        )
        asyncio.run(mint_features({"project_id": project_id}))

        session = shared_session_factory()
        try:
            feats = list(
                session.execute(
                    select(Node).where(Node.project_id == project_id, Node.tier == "feat")
                ).scalars()
            )
            assert len(feats) == 1
            billing = feats[0]

            vocab = list(
                session.execute(
                    select(Node)
                    .where(Node.project_id == project_id, Node.tier == "vocab")
                    .order_by(Node.name)
                ).scalars()
            )
            assert len(vocab) == 2

            boulder = next(v for v in vocab if v.name == "boulder")
            tranche = next(v for v in vocab if v.name == "tranche")
            assert boulder.parent_id is None  # project-level
            assert tranche.parent_id == billing.id  # feature-local
        finally:
            session.close()


class TestFeatureMintVocabIdempotency:
    def test_second_run_is_noop_for_vocab(self, shared_session_factory):
        """The existing feat_* idempotency guard short-circuits the
        handler, so vocab mint doesn't run again on replay either."""
        project_id = _seed_project_with_approved_content(
            shared_session_factory, FEATURES_PLUS_PROJECT_VOCAB
        )
        asyncio.run(mint_features({"project_id": project_id}))

        session = shared_session_factory()
        try:
            vocab_count_1 = (
                session.query(Node)
                .filter(Node.project_id == project_id, Node.tier == "vocab")
                .count()
            )
        finally:
            session.close()
        assert vocab_count_1 == 2

        # Second run should be a no-op.
        asyncio.run(mint_features({"project_id": project_id}))

        session = shared_session_factory()
        try:
            vocab_count_2 = (
                session.query(Node)
                .filter(Node.project_id == project_id, Node.tier == "vocab")
                .count()
            )
        finally:
            session.close()
        assert vocab_count_2 == 2  # unchanged


class TestFeatureMintVocabFailureModes:
    def test_malformed_vocabulary_raises(self, shared_session_factory):
        """A structurally-broken <vocabulary> block in approved
        content is a bug state (the generation handler's retry loop
        should have caught it). Raise rather than silently drop
        vocab."""
        broken = (
            "<features>"
            "<feature><name>Billing</name><intent>Pay.</intent></feature>"
            "</features>"
            "<vocabulary>"
            '<term name="boulder" scope="project">'
            "<vocab-entry>"
            "<!-- missing required definition -->"
            "<disambiguation>no def</disambiguation>"
            "</vocab-entry>"
            "</term>"
            "</vocabulary>"
        )
        project_id = _seed_project_with_approved_content(shared_session_factory, broken)
        with pytest.raises(FeatureMintHandlerError, match="could not parse approved vocabulary"):
            asyncio.run(mint_features({"project_id": project_id}))

    def test_vocabulary_with_unknown_feature_name_raises(self, shared_session_factory):
        broken = (
            "<features>"
            "<feature><name>Billing</name><intent>Pay.</intent></feature>"
            "</features>"
            "<vocabulary>"
            '<term name="tranche" scope="feature" feature-name="Marketing">'
            "<vocab-entry><definition>d</definition></vocab-entry>"
            "</term>"
            "</vocabulary>"
        )
        project_id = _seed_project_with_approved_content(shared_session_factory, broken)
        with pytest.raises(FeatureMintHandlerError, match="could not parse approved vocabulary"):
            asyncio.run(mint_features({"project_id": project_id}))
