"""Tests for the decomposition-graph endpoint (Phase 4 stage 10)."""

from __future__ import annotations

import os
import uuid

import pytest

os.environ.setdefault("SIEGE_DISABLE_WORKER_LOOP", "1")

try:
    import cryptography.hazmat.bindings._rust  # noqa: F401
except BaseException as _exc:  # pragma: no cover - env-dependent skip
    pytest.skip(
        f"cryptography/cffi environmental issue: {_exc!r}",
        allow_module_level=True,
    )

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from backend.auth.routes import get_current_user  # noqa: E402
from backend.database import Base, get_db  # noqa: E402
from backend.graph import events as ev  # noqa: E402
from backend.graph.ids import Kind, mint  # noqa: E402
from backend.graph.reducer import append_event  # noqa: E402
from backend.main import app  # noqa: E402
from backend.models import Project  # noqa: E402


@pytest.fixture()
def engine_and_factory(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    import backend.database as _database_mod

    monkeypatch.setattr(_database_mod, "SessionLocal", factory)
    yield engine, factory
    engine.dispose()


@pytest.fixture()
def db(engine_and_factory):
    _, factory = engine_and_factory
    s: Session = factory()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture()
def project(db):
    p = Project(id=str(uuid.uuid4()), name="Test", git_repo_path="/tmp/test")
    db.add(p)
    db.commit()
    return p


@pytest.fixture()
def client(db, project):
    def _get_db():
        yield db

    def _get_user():
        return object()

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[get_current_user] = _get_user
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


class TestDecompositionGraph:
    def test_empty_project(self, client, project):
        resp = client.get(f"/api/projects/{project.id}/decomposition-graph")
        assert resp.status_code == 200
        assert resp.json() == {"nodes": [], "edges": []}

    def test_populated_project(self, client, project, db):
        # Seed a top-level comp + a subresp + a subcomponent +
        # dependency and decomposition edges.
        resp_id = mint(db, Kind.RESP)
        append_event(
            db,
            project.id,
            ev.NodeCreated(
                node_id=resp_id,
                tier="resp",
                kind="domain",
                parent_id=None,
                name="Billing",
                display_order=0,
                content="",
            ),
        )
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
                display_order=0,
                content="",
            ),
        )
        sub_id = mint(db, Kind.COMP)
        append_event(
            db,
            project.id,
            ev.NodeCreated(
                node_id=sub_id,
                tier="comp",
                kind="domain",
                parent_id=comp_id,
                name="TokenStore",
                display_order=0,
                content="",
            ),
        )
        decomp_edge_id = mint(db, Kind.EDGE)
        append_event(
            db,
            project.id,
            ev.EdgeCreated(
                edge_id=decomp_edge_id,
                edge_type="decomposition",
                source_id=resp_id,
                target_id=comp_id,
            ),
        )
        db.commit()

        resp = client.get(f"/api/projects/{project.id}/decomposition-graph")
        body = resp.json()
        node_ids = {n["id"] for n in body["nodes"]}
        assert resp_id in node_ids
        assert comp_id in node_ids
        assert sub_id in node_ids
        edge_ids = {e["id"] for e in body["edges"]}
        assert decomp_edge_id in edge_ids

    def test_excludes_non_decomposition_nodes(self, client, project, db):
        # Feature + policy nodes should NOT appear in the graph payload
        feat_id = mint(db, Kind.FEAT)
        append_event(
            db,
            project.id,
            ev.NodeCreated(
                node_id=feat_id,
                tier="feat",
                kind="domain",
                parent_id=None,
                name="Payments",
                display_order=0,
                content="",
            ),
        )
        policy_id = mint(db, Kind.POLICY)
        append_event(
            db,
            project.id,
            ev.NodeCreated(
                node_id=policy_id,
                tier="policy",
                kind="domain",
                parent_id=None,
                name="Telemetry",
                display_order=0,
                content="",
            ),
        )
        db.commit()

        resp = client.get(f"/api/projects/{project.id}/decomposition-graph")
        body = resp.json()
        node_ids = {n["id"] for n in body["nodes"]}
        assert feat_id not in node_ids
        assert policy_id not in node_ids

    def test_drops_edges_whose_endpoints_arent_in_node_set(self, client, project, db):
        """Regression: feat → resp decomposition edges reference
        feat_* nodes that are deliberately excluded from the graph
        node scope. Previous implementation returned them anyway,
        which crashed the Cytoscape renderer with "nonexistent source".

        Any edge whose source or target is outside the returned
        node set must be dropped.
        """
        # Top-level resp (in scope)
        resp_id = mint(db, Kind.RESP)
        append_event(
            db,
            project.id,
            ev.NodeCreated(
                node_id=resp_id,
                tier="resp",
                kind="domain",
                parent_id=None,
                name="Billing",
                display_order=0,
                content="",
            ),
        )
        # Feature (out of scope)
        feat_id = mint(db, Kind.FEAT)
        append_event(
            db,
            project.id,
            ev.NodeCreated(
                node_id=feat_id,
                tier="feat",
                kind="domain",
                parent_id=None,
                name="Payments",
                display_order=0,
                content="",
            ),
        )
        # feat → resp decomposition edge — source is out of scope
        leak_edge_id = mint(db, Kind.EDGE)
        append_event(
            db,
            project.id,
            ev.EdgeCreated(
                edge_id=leak_edge_id,
                edge_type="decomposition",
                source_id=feat_id,
                target_id=resp_id,
            ),
        )
        db.commit()

        resp = client.get(f"/api/projects/{project.id}/decomposition-graph")
        body = resp.json()
        edge_ids = {e["id"] for e in body["edges"]}
        assert leak_edge_id not in edge_ids, (
            "feat → resp edge must be filtered out when feat_* nodes "
            "aren't in the returned node set"
        )
        # And every remaining edge's source+target are in the node set
        node_ids = {n["id"] for n in body["nodes"]}
        for edge in body["edges"]:
            assert edge["source_id"] in node_ids
            assert edge["target_id"] in node_ids
