"""Tests for the vocab node tier infrastructure.

Stage 1 of Phase 5.5 adds the ``vocab`` tier to the schema, IDs,
events, reducer, and a small helpers module. This test file
exercises:

- ``Kind.VOCAB`` mints ``vocab_*`` ids that round-trip through
  ``validate``.
- The reducer accepts ``NodeCreated`` with tier=vocab and
  ``parent_id=None`` (project-level) and tier=vocab with
  ``parent_id`` pointing at a feat_* (feature-local).
- The reducer rejects tier=vocab with ``parent_id`` pointing at a
  comp_*, resp_*, or other non-feat node.
- The same constraint applies to ``NodeReparented``: reparenting
  a vocab node to a non-feat parent is rejected; reparenting to
  ``None`` or to a feat_* is accepted.
- Rebuild-from-log replay produces the same state as incremental
  apply when vocab nodes are present in the event stream,
  including nodes that went through rename + reparent cycles.
- The ``backend.graph.vocabulary`` helpers return the correct
  shapes for project-level, feature-local, and reachability
  queries.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database import Base
from backend.graph import events as ev
from backend.graph import vocabulary
from backend.graph.ids import Kind, mint, validate
from backend.graph.reducer import ReducerError, append_event, rebuild_projections
from backend.models import Project
from backend.models.node import Node


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = factory()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def project(db):
    project = Project(id=str(uuid.uuid4()), name="T", git_repo_path="/tmp/t")
    db.add(project)
    db.commit()
    return project


def _seed_feat(db: Session, project_id: str, name: str = "Billing") -> str:
    """Seed a feat_* node we can parent vocab entries to."""
    feat_id = mint(db, Kind.FEAT)
    append_event(
        db,
        project_id,
        ev.NodeCreated(
            node_id=feat_id,
            tier="feat",
            kind="domain",
            parent_id=None,
            name=name,
            display_order=0,
            content="",
        ),
    )
    return feat_id


def _seed_comp(db: Session, project_id: str, name: str = "BillingService") -> str:
    comp_id = mint(db, Kind.COMP)
    append_event(
        db,
        project_id,
        ev.NodeCreated(
            node_id=comp_id,
            tier="comp",
            kind="domain",
            parent_id=None,
            name=name,
            display_order=0,
            content="",
        ),
    )
    return comp_id


def _seed_resp(db: Session, project_id: str, name: str = "Authentication") -> str:
    resp_id = mint(db, Kind.RESP)
    append_event(
        db,
        project_id,
        ev.NodeCreated(
            node_id=resp_id,
            tier="resp",
            kind="domain",
            parent_id=None,
            name=name,
            display_order=0,
            content="",
        ),
    )
    return resp_id


def _seed_vocab(
    db: Session,
    project_id: str,
    name: str,
    *,
    parent_id: str | None = None,
    content: str = "<vocab-entry><definition>Stub definition.</definition></vocab-entry>",
) -> str:
    vocab_id = mint(db, Kind.VOCAB)
    append_event(
        db,
        project_id,
        ev.NodeCreated(
            node_id=vocab_id,
            tier="vocab",
            kind="domain",
            parent_id=parent_id,
            name=name,
            display_order=0,
            content=content,
        ),
    )
    return vocab_id


class TestVocabKind:
    def test_mint_produces_vocab_prefixed_id(self, db):
        vocab_id = mint(db, Kind.VOCAB)
        assert vocab_id.startswith("vocab_")
        kind, suffix = validate(vocab_id)
        assert kind == Kind.VOCAB
        assert len(suffix) == 8

    def test_vocab_kind_in_enum(self):
        assert Kind.VOCAB.value == "vocab"


class TestVocabReducerCreate:
    def test_project_level_vocab_accepted(self, db, project):
        vocab_id = _seed_vocab(db, project.id, "Boulder")
        row = db.get(Node, vocab_id)
        assert row is not None
        assert row.tier == "vocab"
        assert row.parent_id is None
        assert row.name == "Boulder"

    def test_feature_local_vocab_accepted(self, db, project):
        feat_id = _seed_feat(db, project.id, "Billing")
        vocab_id = _seed_vocab(db, project.id, "Tranche", parent_id=feat_id)
        row = db.get(Node, vocab_id)
        assert row is not None
        assert row.parent_id == feat_id

    def test_vocab_parent_on_comp_rejected(self, db, project):
        comp_id = _seed_comp(db, project.id)
        with pytest.raises(ReducerError, match="may only be scoped"):
            _seed_vocab(db, project.id, "BadTerm", parent_id=comp_id)

    def test_vocab_parent_on_resp_rejected(self, db, project):
        resp_id = _seed_resp(db, project.id)
        with pytest.raises(ReducerError, match="may only be scoped"):
            _seed_vocab(db, project.id, "BadTerm", parent_id=resp_id)

    def test_vocab_parent_on_vocab_rejected(self, db, project):
        # A vocab node cannot parent another vocab node — even vocab
        # itself isn't in the allowed parent set, only feat_* is.
        v1 = _seed_vocab(db, project.id, "Boulder")
        with pytest.raises(ReducerError, match="may only be scoped"):
            _seed_vocab(db, project.id, "SubTerm", parent_id=v1)

    def test_vocab_parent_on_missing_id_rejected(self, db, project):
        with pytest.raises(ReducerError, match="not found"):
            _seed_vocab(db, project.id, "BadTerm", parent_id="feat_MISSING0")


class TestVocabReducerReparent:
    def test_reparent_to_null_accepted(self, db, project):
        feat_id = _seed_feat(db, project.id)
        vocab_id = _seed_vocab(db, project.id, "Tranche", parent_id=feat_id)
        append_event(
            db,
            project.id,
            ev.NodeReparented(node_id=vocab_id, new_parent_id=None),
        )
        row = db.get(Node, vocab_id)
        assert row.parent_id is None

    def test_reparent_to_other_feat_accepted(self, db, project):
        feat_a = _seed_feat(db, project.id, "Billing")
        feat_b = _seed_feat(db, project.id, "Auth")
        vocab_id = _seed_vocab(db, project.id, "Tranche", parent_id=feat_a)
        append_event(
            db,
            project.id,
            ev.NodeReparented(node_id=vocab_id, new_parent_id=feat_b),
        )
        row = db.get(Node, vocab_id)
        assert row.parent_id == feat_b

    def test_reparent_to_comp_rejected(self, db, project):
        feat_id = _seed_feat(db, project.id)
        comp_id = _seed_comp(db, project.id)
        vocab_id = _seed_vocab(db, project.id, "Tranche", parent_id=feat_id)
        with pytest.raises(ReducerError, match="may only be scoped"):
            append_event(
                db,
                project.id,
                ev.NodeReparented(node_id=vocab_id, new_parent_id=comp_id),
            )


class TestVocabRebuild:
    def test_rebuild_after_vocab_lifecycle(self, db, project):
        """Incremental apply and rebuild-from-log produce identical state.

        Mint a few vocab nodes under different scopes, rename one,
        reparent one, delete one — then snapshot state, rebuild
        projections from the event log, and compare.
        """
        feat_id = _seed_feat(db, project.id, "Billing")
        v1 = _seed_vocab(db, project.id, "Boulder")
        v2 = _seed_vocab(db, project.id, "Tranche", parent_id=feat_id)
        v3 = _seed_vocab(db, project.id, "Temp")
        # Rename v1
        append_event(db, project.id, ev.NodeRenamed(node_id=v1, new_name="LargeBoulder"))
        # Promote v2 to project-level
        append_event(db, project.id, ev.NodeReparented(node_id=v2, new_parent_id=None))
        # Delete v3
        append_event(db, project.id, ev.NodeDeleted(node_id=v3))
        db.commit()

        # Snapshot current state
        before = {
            n.id: (n.tier, n.name, n.parent_id)
            for n in db.execute(
                Node.__table__.select().where(Node.project_id == project.id)
            ).fetchall()
        }

        # Rebuild and re-snapshot
        rebuild_projections(db, project.id)
        db.commit()
        after = {
            n.id: (n.tier, n.name, n.parent_id)
            for n in db.execute(
                Node.__table__.select().where(Node.project_id == project.id)
            ).fetchall()
        }

        assert before == after
        # Sanity: v3 is gone, v1 is renamed, v2 is project-level
        assert v3 not in before
        assert before[v1] == ("vocab", "LargeBoulder", None)
        assert before[v2] == ("vocab", "Tranche", None)


class TestVocabularyHelpers:
    def test_list_project_vocab(self, db, project):
        feat_id = _seed_feat(db, project.id)
        _seed_vocab(db, project.id, "Boulder")  # project-level
        _seed_vocab(db, project.id, "Tranche", parent_id=feat_id)  # feature-local
        _seed_vocab(db, project.id, "Foundation")  # project-level
        db.commit()

        entries = vocabulary.list_project_vocab(db, project.id)
        names = [e.name for e in entries]
        assert names == ["Boulder", "Foundation"]  # name-sorted
        assert all(e.parent_id is None for e in entries)

    def test_list_feature_vocab(self, db, project):
        feat_billing = _seed_feat(db, project.id, "Billing")
        feat_auth = _seed_feat(db, project.id, "Auth")
        _seed_vocab(db, project.id, "Tranche", parent_id=feat_billing)
        _seed_vocab(db, project.id, "Settlement", parent_id=feat_billing)
        _seed_vocab(db, project.id, "Session", parent_id=feat_auth)
        _seed_vocab(db, project.id, "Boulder")  # project-level, excluded
        db.commit()

        billing_vocab = vocabulary.list_feature_vocab(db, project.id, feat_billing)
        assert [e.name for e in billing_vocab] == ["Settlement", "Tranche"]

        auth_vocab = vocabulary.list_feature_vocab(db, project.id, feat_auth)
        assert [e.name for e in auth_vocab] == ["Session"]

    def test_list_all_vocab(self, db, project):
        feat_id = _seed_feat(db, project.id)
        _seed_vocab(db, project.id, "Boulder")  # project
        _seed_vocab(db, project.id, "Foundation")  # project
        _seed_vocab(db, project.id, "Tranche", parent_id=feat_id)  # feature
        db.commit()

        all_entries = vocabulary.list_all_vocab(db, project.id)
        assert len(all_entries) == 3
        # Project-level come first
        assert all_entries[0].parent_id is None
        assert all_entries[1].parent_id is None
        assert all_entries[2].parent_id == feat_id

    def test_vocab_by_id_happy_path(self, db, project):
        vocab_id = _seed_vocab(db, project.id, "Boulder")
        db.commit()
        row = vocabulary.vocab_by_id(db, vocab_id)
        assert row is not None
        assert row.name == "Boulder"

    def test_vocab_by_id_rejects_wrong_tier(self, db, project):
        feat_id = _seed_feat(db, project.id)
        db.commit()
        # A feat_* id is a valid node id but not a vocab id.
        row = vocabulary.vocab_by_id(db, feat_id)
        assert row is None

    def test_vocab_by_name_scoped_to_project(self, db, project):
        feat_id = _seed_feat(db, project.id)
        project_tranche = _seed_vocab(db, project.id, "Tranche")
        feature_tranche = _seed_vocab(db, project.id, "Tranche", parent_id=feat_id)
        db.commit()

        # Project scope returns the project-level one.
        p = vocabulary.vocab_by_name(db, project.id, "Tranche")
        assert p is not None
        assert p.id == project_tranche

        # Feature scope returns the feature-local one.
        f = vocabulary.vocab_by_name(db, project.id, "Tranche", parent_id=feat_id)
        assert f is not None
        assert f.id == feature_tranche

    def test_vocab_by_name_missing(self, db, project):
        assert vocabulary.vocab_by_name(db, project.id, "NoSuchTerm") is None

    def test_reachable_vocab_for_feat_target(self, db, project):
        feat_billing = _seed_feat(db, project.id, "Billing")
        feat_auth = _seed_feat(db, project.id, "Auth")
        project_boulder = _seed_vocab(db, project.id, "Boulder")
        billing_tranche = _seed_vocab(db, project.id, "Tranche", parent_id=feat_billing)
        _seed_vocab(db, project.id, "Session", parent_id=feat_auth)
        db.commit()

        reachable = vocabulary.reachable_vocab_for_node(db, project.id, feat_billing)
        reachable_ids = {n.id for n in reachable}
        # Project-level always included
        assert project_boulder in reachable_ids
        # Feature-local for this feature included
        assert billing_tranche in reachable_ids
        # Feature-local for OTHER feature excluded
        session_ids = [n.id for n in reachable if n.name == "Session"]
        assert session_ids == []

    def test_reachable_vocab_missing_target_returns_project_level(self, db, project):
        _seed_vocab(db, project.id, "Boulder")
        db.commit()
        reachable = vocabulary.reachable_vocab_for_node(db, project.id, "feat_NONEXIST")
        assert len(reachable) == 1
        assert reachable[0].name == "Boulder"
