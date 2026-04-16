"""Tests for the reference node tier infrastructure (Phase 6.6).

Covers:

- ``Kind.REF`` mints ``ref_*`` ids that round-trip through ``validate``.
- The reducer accepts ``NodeCreated`` with ``tier="ref"`` and
  ``parent_id=None``.
- The reducer rejects ``NodeCreated`` / ``NodeReparented`` with
  ``tier="ref"`` and any non-None ``parent_id``.
- The edge-type vocabulary carries ``reference`` and
  ``EdgeCreated(edge_type="reference", ...)`` round-trips through
  the reducer.
- The ``backend.graph.references`` helpers return correct shapes
  for listing, lookup by id/name, incoming/outgoing edges.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database import Base
from backend.graph import events as ev
from backend.graph import references
from backend.graph.ids import Kind, mint, validate
from backend.graph.reducer import ReducerError, append_event, rebuild_projections
from backend.models import Project
from backend.models.node import Edge, Node


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
        ),
    )
    return feat_id


def _seed_ref(
    db: Session, project_id: str, name: str = "Deployment Runbook", content: str = ""
) -> str:
    ref_id = mint(db, Kind.REF)
    append_event(
        db,
        project_id,
        ev.NodeCreated(
            node_id=ref_id,
            tier="ref",
            kind="domain",
            parent_id=None,
            name=name,
            content=content,
        ),
    )
    return ref_id


class TestRefKindIdMinting:
    def test_kind_ref_mints_ref_prefix(self, db):
        ref_id = mint(db, Kind.REF)
        assert ref_id.startswith("ref_")
        kind, _ = validate(ref_id)
        assert kind == Kind.REF

    def test_ref_id_round_trips_through_validate(self, db):
        ref_id = mint(db, Kind.REF)
        kind, suffix = validate(ref_id)
        assert kind == Kind.REF
        assert len(suffix) == 8


class TestRefReducerInvariants:
    def test_node_created_ref_tier_project_level_is_accepted(self, db, project):
        ref_id = _seed_ref(db, project.id)
        node = db.get(Node, ref_id)
        assert node is not None
        assert node.tier == "ref"
        assert node.parent_id is None

    def test_node_created_ref_tier_with_feat_parent_is_rejected(self, db, project):
        feat_id = _seed_feat(db, project.id)
        with pytest.raises(ReducerError, match="references are always top-level"):
            append_event(
                db,
                project.id,
                ev.NodeCreated(
                    node_id=mint(db, Kind.REF),
                    tier="ref",
                    kind="domain",
                    parent_id=feat_id,
                    name="Scoped Ref",
                ),
            )

    def test_node_created_ref_tier_with_comp_parent_is_rejected(self, db, project):
        comp_id = mint(db, Kind.COMP)
        append_event(
            db,
            project.id,
            ev.NodeCreated(
                node_id=comp_id,
                tier="comp",
                kind="domain",
                parent_id=None,
                name="BillingService",
            ),
        )
        with pytest.raises(ReducerError, match="references are always top-level"):
            append_event(
                db,
                project.id,
                ev.NodeCreated(
                    node_id=mint(db, Kind.REF),
                    tier="ref",
                    kind="domain",
                    parent_id=comp_id,
                    name="Bad Ref",
                ),
            )

    def test_node_reparented_ref_tier_to_non_null_is_rejected(self, db, project):
        ref_id = _seed_ref(db, project.id)
        feat_id = _seed_feat(db, project.id)
        with pytest.raises(ReducerError, match="references are always top-level"):
            append_event(
                db,
                project.id,
                ev.NodeReparented(node_id=ref_id, new_parent_id=feat_id),
            )

    def test_node_reparented_ref_tier_to_null_is_accepted(self, db, project):
        ref_id = _seed_ref(db, project.id)
        # Reparent to None (a no-op, but exercises the permit path).
        append_event(
            db,
            project.id,
            ev.NodeReparented(node_id=ref_id, new_parent_id=None),
        )
        node = db.get(Node, ref_id)
        assert node is not None
        assert node.parent_id is None


class TestReferenceEdgeTypeRoundTrip:
    def test_edge_created_reference_round_trips(self, db, project):
        ref_id = _seed_ref(db, project.id)
        feat_id = _seed_feat(db, project.id)
        edge_id = mint(db, Kind.EDGE)
        append_event(
            db,
            project.id,
            ev.EdgeCreated(
                edge_id=edge_id,
                edge_type="reference",
                source_id=ref_id,
                target_id=feat_id,
            ),
        )
        edge = db.get(Edge, edge_id)
        assert edge is not None
        assert edge.edge_type == "reference"
        assert edge.source_id == ref_id
        assert edge.target_id == feat_id

    def test_rebuild_replays_ref_nodes_and_reference_edges(self, db, project):
        ref_id = _seed_ref(db, project.id, name="Runbook", content="<reference/>")
        feat_id = _seed_feat(db, project.id)
        edge_id = mint(db, Kind.EDGE)
        append_event(
            db,
            project.id,
            ev.EdgeCreated(
                edge_id=edge_id,
                edge_type="reference",
                source_id=ref_id,
                target_id=feat_id,
            ),
        )
        # Replay from zero. Projection state should match.
        rebuild_projections(db, project.id)
        node = db.get(Node, ref_id)
        assert node is not None
        assert node.tier == "ref"
        assert node.name == "Runbook"
        edge = db.get(Edge, edge_id)
        assert edge is not None
        assert edge.edge_type == "reference"


class TestReferenceHelpers:
    def test_list_project_references_orders_by_name(self, db, project):
        rb_id = _seed_ref(db, project.id, name="Runbook")
        dsl_id = _seed_ref(db, project.id, name="DSL Spec")
        entries = references.list_project_references(db, project.id)
        ids = [e.id for e in entries]
        assert ids == [dsl_id, rb_id]  # alphabetical by name

    def test_reference_by_id_finds_node(self, db, project):
        ref_id = _seed_ref(db, project.id)
        node = references.reference_by_id(db, ref_id)
        assert node is not None
        assert node.id == ref_id

    def test_reference_by_id_returns_none_for_non_ref(self, db, project):
        feat_id = _seed_feat(db, project.id)
        assert references.reference_by_id(db, feat_id) is None

    def test_reference_by_name_finds_by_name(self, db, project):
        _seed_ref(db, project.id, name="Runbook")
        node = references.reference_by_name(db, project.id, "Runbook")
        assert node is not None
        assert node.name == "Runbook"

    def test_reference_by_name_returns_none_for_missing(self, db, project):
        assert references.reference_by_name(db, project.id, "Missing") is None

    def test_outgoing_and_incoming_reference_edges(self, db, project):
        ref_id = _seed_ref(db, project.id)
        feat_id = _seed_feat(db, project.id)
        edge_id = mint(db, Kind.EDGE)
        append_event(
            db,
            project.id,
            ev.EdgeCreated(
                edge_id=edge_id,
                edge_type="reference",
                source_id=ref_id,
                target_id=feat_id,
            ),
        )
        out_edges = references.outgoing_reference_edges(db, project.id, ref_id)
        in_edges = references.incoming_reference_edges(db, project.id, feat_id)
        assert len(out_edges) == 1
        assert out_edges[0].target_id == feat_id
        assert len(in_edges) == 1
        assert in_edges[0].source_id == ref_id
