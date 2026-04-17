"""Tests for GET /projects/:id/structure.

Consolidated read that replaces nav-tree + decomposition-graph +
responsibility-coverage + all list endpoints. Covers tier
coverage, edge filtering, status flags (has_content,
has_pending_draft, generation_running), and the ``offset`` field
that clients use to subscribe to the SSE stream without losing
events.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime

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
from backend.models.job import Job  # noqa: E402


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


def _mint(
    db: Session,
    project_id: str,
    kind_enum: Kind,
    *,
    tier: str,
    name: str,
    parent_id: str | None = None,
    content: str = "",
    display_order: int = 0,
) -> str:
    nid = mint(db, kind_enum)
    append_event(
        db,
        project_id,
        ev.NodeCreated(
            node_id=nid,
            tier=tier,  # type: ignore[arg-type]
            kind="domain",
            parent_id=parent_id,
            name=name,
            display_order=display_order,
            content=content,
        ),
    )
    return nid


def _edge(db: Session, project_id: str, edge_type: str, source_id: str, target_id: str) -> str:
    eid = mint(db, Kind.EDGE)
    append_event(
        db,
        project_id,
        ev.EdgeCreated(
            edge_id=eid,
            edge_type=edge_type,  # type: ignore[arg-type]
            source_id=source_id,
            target_id=target_id,
        ),
    )
    return eid


class TestEmptyProject:
    def test_returns_offset_zero_and_empty_lists(self, client, project, db):
        db.commit()
        resp = client.get(f"/api/projects/{project.id}/structure")
        assert resp.status_code == 200
        body = resp.json()
        assert body == {"offset": 0, "nodes": [], "edges": []}


class TestInlineContent:
    def test_content_included_for_light_tiers(self, client, project, db):
        # resp / feat / policy / vocab / ref content ships inline.
        r = _mint(db, project.id, Kind.RESP, tier="resp", name="R", content="Resp description.")
        f = _mint(db, project.id, Kind.FEAT, tier="feat", name="F", content="Feature description.")
        v = _mint(
            db,
            project.id,
            Kind.VOCAB,
            tier="vocab",
            name="V",
            content="<vocab-entry>...</vocab-entry>",
        )
        db.commit()

        nodes = {
            n["id"]: n for n in client.get(f"/api/projects/{project.id}/structure").json()["nodes"]
        }
        assert nodes[r]["content"] == "Resp description."
        assert nodes[f]["content"] == "Feature description."
        assert nodes[v]["content"].startswith("<vocab-entry>")

    def test_content_empty_for_heavy_tiers(self, client, project, db):
        # comp / subreqs / impl / fanin / expansion / reqs / sysarch
        # have their own detail endpoints; /structure leaves
        # ``content`` empty to keep the snapshot payload bounded.
        c = _mint(
            db,
            project.id,
            Kind.COMP,
            tier="comp",
            name="C",
            content="<comparch>big blob</comparch>",
        )
        e = _mint(
            db,
            project.id,
            Kind.EXPANSION,
            tier="expansion",
            name="E",
            content="<expansion>…</expansion>",
        )
        db.commit()

        nodes = {
            n["id"]: n for n in client.get(f"/api/projects/{project.id}/structure").json()["nodes"]
        }
        assert nodes[c]["content"] == ""
        # But has_content still reflects the truth.
        assert nodes[c]["has_content"] is True
        assert nodes[e]["content"] == ""
        assert nodes[e]["has_content"] is True


class TestTierCoverage:
    def test_ships_every_structural_tier(self, client, project, db):
        ids = {
            "expansion": _mint(db, project.id, Kind.EXPANSION, tier="expansion", name="E"),
            "reqs": _mint(db, project.id, Kind.REQS, tier="reqs", name="R"),
            "sysarch": _mint(db, project.id, Kind.SYSARCH, tier="sysarch", name="S"),
            "feat": _mint(db, project.id, Kind.FEAT, tier="feat", name="F"),
            "resp": _mint(db, project.id, Kind.RESP, tier="resp", name="TopResp"),
            "comp": _mint(db, project.id, Kind.COMP, tier="comp", name="C"),
            "policy": _mint(db, project.id, Kind.POLICY, tier="policy", name="P"),
            "vocab": _mint(db, project.id, Kind.VOCAB, tier="vocab", name="V"),
            "ref": _mint(db, project.id, Kind.REF, tier="ref", name="Ref"),
        }
        sub_id = _mint(db, project.id, Kind.COMP, tier="comp", name="Sub", parent_id=ids["comp"])
        ids["subreqs"] = _mint(
            db, project.id, Kind.SUBREQS, tier="subreqs", name="SR", parent_id=ids["comp"]
        )
        ids["fanin"] = _mint(
            db, project.id, Kind.FANIN, tier="fanin", name="FI", parent_id=ids["comp"]
        )
        ids["impl"] = _mint(db, project.id, Kind.IMPL, tier="impl", name="IM", parent_id=sub_id)
        db.commit()

        resp = client.get(f"/api/projects/{project.id}/structure")
        assert resp.status_code == 200
        body = resp.json()
        node_ids = {n["id"] for n in body["nodes"]}
        assert set(ids.values()) | {sub_id} <= node_ids


class TestEdges:
    def test_includes_dependency_decomposition_domain_parent_reference(self, client, project, db):
        c1 = _mint(db, project.id, Kind.COMP, tier="comp", name="C1")
        c2 = _mint(db, project.id, Kind.COMP, tier="comp", name="C2")
        r1 = _mint(db, project.id, Kind.RESP, tier="resp", name="R1")
        ref1 = _mint(db, project.id, Kind.REF, tier="ref", name="Ref")
        _edge(db, project.id, "dependency", c1, c2)
        _edge(db, project.id, "decomposition", r1, c1)
        _edge(db, project.id, "domain_parent", c1, c2)
        _edge(db, project.id, "reference", c1, ref1)
        db.commit()

        body = client.get(f"/api/projects/{project.id}/structure").json()
        edge_types = {e["edge_type"] for e in body["edges"]}
        assert edge_types == {"dependency", "decomposition", "domain_parent", "reference"}

    def test_omits_edges_with_unknown_endpoints(self, client, project, db):
        # Edges whose endpoints aren't in the returned node set
        # should be filtered out so the frontend doesn't receive
        # dangling refs.
        c1 = _mint(db, project.id, Kind.COMP, tier="comp", name="C1")
        # plan_* tier is NOT in _STRUCTURE_TIERS; an edge to it
        # would be dangling from the client's perspective.
        plan_id = mint(db, Kind.PLAN)
        append_event(
            db,
            project.id,
            ev.NodeCreated(
                node_id=plan_id,
                tier="plan",
                kind="domain",
                parent_id=c1,
                name="P",
            ),
        )
        _edge(db, project.id, "dependency", c1, plan_id)
        db.commit()

        body = client.get(f"/api/projects/{project.id}/structure").json()
        assert body["edges"] == []


class TestFlags:
    def test_has_content_reflects_trimmed_content(self, client, project, db):
        empty = _mint(db, project.id, Kind.COMP, tier="comp", name="E", content="")
        ws = _mint(db, project.id, Kind.COMP, tier="comp", name="W", content=" \n\t ")
        real = _mint(db, project.id, Kind.COMP, tier="comp", name="R", content="<x/>")
        db.commit()

        nodes = {
            n["id"]: n for n in client.get(f"/api/projects/{project.id}/structure").json()["nodes"]
        }
        assert nodes[empty]["has_content"] is False
        assert nodes[ws]["has_content"] is False
        assert nodes[real]["has_content"] is True

    def test_has_pending_draft_flag(self, client, project, db):
        c = _mint(db, project.id, Kind.COMP, tier="comp", name="C", content="<x/>")
        append_event(
            db,
            project.id,
            ev.DraftGenerated(
                draft_id="d1",
                target_type="node",
                target_id=c,
                content="<x>new</x>",
                batch_id="b1",
            ),
        )
        db.commit()

        nodes = {
            n["id"]: n for n in client.get(f"/api/projects/{project.id}/structure").json()["nodes"]
        }
        assert nodes[c]["has_pending_draft"] is True

    def test_generation_running_flag_via_active_job(self, client, project, db):
        c = _mint(db, project.id, Kind.COMP, tier="comp", name="C")
        db.add(
            Job(
                job_type="v2.generate_comparch",
                payload={"project_id": project.id, "component_id": c},
                status="running",
                priority=10,
                max_retries=0,
                created_at=datetime.utcnow(),
            )
        )
        db.commit()

        nodes = {
            n["id"]: n for n in client.get(f"/api/projects/{project.id}/structure").json()["nodes"]
        }
        assert nodes[c]["generation_running"] is True


class TestOffset:
    def test_offset_tracks_latest_event(self, client, project, db):
        # Empty project → offset 0.
        body = client.get(f"/api/projects/{project.id}/structure").json()
        assert body["offset"] == 0

        # After three events, offset should be 3.
        _mint(db, project.id, Kind.COMP, tier="comp", name="C1")
        _mint(db, project.id, Kind.COMP, tier="comp", name="C2")
        _mint(db, project.id, Kind.COMP, tier="comp", name="C3")
        db.commit()

        body = client.get(f"/api/projects/{project.id}/structure").json()
        assert body["offset"] == 3


class TestIsolation:
    def test_other_project_nodes_do_not_leak(self, client, project, db):
        # Seed a second project and confirm its nodes don't show
        # up when we read the first project's structure.
        other = Project(id=str(uuid.uuid4()), name="Other", git_repo_path="/tmp/o")
        db.add(other)
        db.commit()
        _mint(db, other.id, Kind.COMP, tier="comp", name="LeakyComp")
        this_c = _mint(db, project.id, Kind.COMP, tier="comp", name="MyComp")
        db.commit()

        body = client.get(f"/api/projects/{project.id}/structure").json()
        node_ids = {n["id"] for n in body["nodes"]}
        assert this_c in node_ids
        assert len(node_ids) == 1
