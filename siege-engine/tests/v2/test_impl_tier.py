"""Tests for the impl node tier (Phase 8).

``Kind.IMPL`` and ``"impl"`` in NODE_TIERS / NodeTier were
already scaffolded at Phase 0; this file confirms the
round-trip works end-to-end now that Phase 8 actually uses them.
No reducer invariants are needed — impl is a leaf under comp
with no depth cap of its own.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database import Base
from backend.graph import events as ev
from backend.graph.ids import Kind, mint, validate
from backend.graph.reducer import append_event, rebuild_projections
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


def _seed_comp(db: Session, project_id: str) -> str:
    comp_id = mint(db, Kind.COMP)
    append_event(
        db,
        project_id,
        ev.NodeCreated(
            node_id=comp_id,
            tier="comp",
            kind="domain",
            parent_id=None,
            name="C",
        ),
    )
    return comp_id


def _seed_impl(db: Session, project_id: str, parent_id: str) -> str:
    impl_id = mint(db, Kind.IMPL)
    append_event(
        db,
        project_id,
        ev.NodeCreated(
            node_id=impl_id,
            tier="impl",
            kind="domain",
            parent_id=parent_id,
            name="C impl",
        ),
    )
    return impl_id


class TestImplKind:
    def test_kind_impl_mints_impl_prefix(self, db):
        impl_id = mint(db, Kind.IMPL)
        assert impl_id.startswith("impl_")
        kind, _ = validate(impl_id)
        assert kind == Kind.IMPL

    def test_impl_id_round_trips(self, db):
        impl_id = mint(db, Kind.IMPL)
        kind, suffix = validate(impl_id)
        assert kind == Kind.IMPL
        assert len(suffix) == 8


class TestImplNodeCreation:
    def test_impl_under_comp_accepted(self, db, project):
        comp_id = _seed_comp(db, project.id)
        impl_id = _seed_impl(db, project.id, comp_id)
        node = db.get(Node, impl_id)
        assert node is not None
        assert node.tier == "impl"
        assert node.parent_id == comp_id

    def test_impl_at_top_level_accepted(self, db, project):
        """Impl nodes don't have a reducer invariant (unlike vocab/ref).

        The one-impl-per-leaf invariant is enforced at mint-time
        by comparch_mint, not by the reducer. An impl with
        parent_id=None would be semantically wrong, but the
        reducer doesn't reject it.
        """
        impl_id = mint(db, Kind.IMPL)
        append_event(
            db,
            project.id,
            ev.NodeCreated(
                node_id=impl_id,
                tier="impl",
                kind="domain",
                parent_id=None,
                name="Orphan impl",
            ),
        )
        node = db.get(Node, impl_id)
        assert node is not None

    def test_rebuild_replays_impl_nodes(self, db, project):
        comp_id = _seed_comp(db, project.id)
        impl_id = _seed_impl(db, project.id, comp_id)
        # Mutate content via DraftGenerated+DraftApproved path.
        append_event(
            db,
            project.id,
            ev.DraftGenerated(
                draft_id="draft_impl_1",
                target_type="node",
                target_id=impl_id,
                content="<implementation><behavior>B</behavior>"
                "<invariants>I</invariants><sequencing>S</sequencing>"
                "<edge-cases>E</edge-cases></implementation>",
                batch_id="batch_1",
            ),
        )
        append_event(db, project.id, ev.DraftApproved(draft_id="draft_impl_1"))

        rebuild_projections(db, project.id)
        node = db.get(Node, impl_id)
        assert node is not None
        assert node.tier == "impl"
        assert "<implementation>" in node.content
