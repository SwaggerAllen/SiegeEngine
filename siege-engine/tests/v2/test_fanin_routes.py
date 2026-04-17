"""Tests for Phase 7 fan-in inspection routes.

Coverage:
- Decomposition graph includes fan-in nodes.
- GET /fanin returns content + status.
- 404 when the comp has no fan-in node.
- POST /fanin/regenerate enqueues v2.generate_fanin.
- POST /fanin/cancel cancels the active job.
"""

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
from sqlalchemy import (
    create_engine,  # noqa: E402
    select,  # noqa: E402
)
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
    import backend.pipeline.queue as _queue_mod

    monkeypatch.setattr(_database_mod, "SessionLocal", factory)
    monkeypatch.setattr(_queue_mod, "SessionLocal", factory)
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


def _seed_fanned_out_domain_with_fanin(db: Session, project_id: str) -> tuple[str, str]:
    """Mint a top-level domain comp + one sub + fan-in shell.

    Returns (comp_id, fanin_id).
    """
    comp_id = mint(db, Kind.COMP)
    append_event(
        db,
        project_id,
        ev.NodeCreated(
            node_id=comp_id,
            tier="comp",
            kind="domain",
            parent_id=None,
            name="BillingDomain",
            content="<comparch>ok</comparch>",
        ),
    )
    sub_id = mint(db, Kind.COMP)
    append_event(
        db,
        project_id,
        ev.NodeCreated(
            node_id=sub_id,
            tier="comp",
            kind="domain",
            parent_id=comp_id,
            name="BillingStore",
            content="<subcomparch>ok</subcomparch>",
        ),
    )
    fanin_id = mint(db, Kind.FANIN)
    append_event(
        db,
        project_id,
        ev.NodeCreated(
            node_id=fanin_id,
            tier="fanin",
            kind="domain",
            parent_id=comp_id,
            name="BillingDomain fan-in",
            content="",
        ),
    )
    db.commit()
    return comp_id, fanin_id


class TestDecompositionGraphIncludesFanIn:
    def test_graph_response_ships_fanin_nodes(self, client, project, db):
        comp_id, fanin_id = _seed_fanned_out_domain_with_fanin(db, project.id)

        resp = client.get(f"/api/projects/{project.id}/decomposition-graph")
        assert resp.status_code == 200
        body = resp.json()
        node_ids = [n["id"] for n in body["nodes"]]
        assert fanin_id in node_ids
        fanin_node = next(n for n in body["nodes"] if n["id"] == fanin_id)
        assert fanin_node["tier"] == "fanin"
        assert fanin_node["kind"] == "domain"
        assert fanin_node["parent_id"] == comp_id

    def test_graph_response_omits_empty_state(self, client, project):
        # Sanity: a fan-in-less project still returns the normal
        # empty shape rather than erroring.
        resp = client.get(f"/api/projects/{project.id}/decomposition-graph")
        assert resp.status_code == 200
        assert resp.json() == {"nodes": [], "edges": []}


class TestGetFanIn:
    def test_returns_content_and_metadata(self, client, project, db):
        comp_id, fanin_id = _seed_fanned_out_domain_with_fanin(db, project.id)
        # Seed content directly via the dedicated event.
        append_event(
            db,
            project.id,
            ev.FanInContentUpdated(
                node_id=fanin_id,
                new_content="<fanin><summary>S</summary><exposed-surface>E</exposed-surface><realized-behavior>R</realized-behavior></fanin>",
            ),
        )
        db.commit()

        resp = client.get(f"/api/projects/{project.id}/components/{comp_id}/fanin")
        assert resp.status_code == 200
        body = resp.json()
        assert body["node"]["id"] == fanin_id
        assert body["node"]["owner_comp_id"] == comp_id
        assert body["node"]["content"].startswith("<fanin>")
        assert body["generation_status"] == "idle"
        assert body["last_error"] is None

    def test_404_when_comp_has_no_fanin(self, client, project, db):
        # Un-fanned-out domain comp has no fanin child.
        comp_id = mint(db, Kind.COMP)
        append_event(
            db,
            project.id,
            ev.NodeCreated(
                node_id=comp_id,
                tier="comp",
                kind="domain",
                parent_id=None,
                name="SoloDomain",
                content="<comparch>ok</comparch>",
            ),
        )
        db.commit()

        resp = client.get(f"/api/projects/{project.id}/components/{comp_id}/fanin")
        assert resp.status_code == 404
        assert "no fan-in" in resp.json()["detail"]

    def test_404_when_comp_does_not_exist(self, client, project):
        resp = client.get(f"/api/projects/{project.id}/components/comp_NOPEXXXX/fanin")
        assert resp.status_code == 404


class TestRegenerateFanIn:
    def test_enqueues_generate_fanin_job(self, client, project, db):
        comp_id, _ = _seed_fanned_out_domain_with_fanin(db, project.id)

        resp = client.post(f"/api/projects/{project.id}/components/{comp_id}/fanin/regenerate")
        assert resp.status_code == 200
        assert "job_id" in resp.json()

        jobs = list(db.execute(select(Job).where(Job.job_type == "v2.generate_fanin")).scalars())
        assert len(jobs) == 1
        assert jobs[0].payload == {"project_id": project.id, "owner_comp_id": comp_id}

    def test_rapid_fire_deduplicates(self, client, project, db):
        comp_id, _ = _seed_fanned_out_domain_with_fanin(db, project.id)

        r1 = client.post(f"/api/projects/{project.id}/components/{comp_id}/fanin/regenerate")
        r2 = client.post(f"/api/projects/{project.id}/components/{comp_id}/fanin/regenerate")
        assert r1.status_code == r2.status_code == 200
        # pipeline_queue.enqueue dedups identical payloads.
        jobs = list(db.execute(select(Job).where(Job.job_type == "v2.generate_fanin")).scalars())
        assert len(jobs) == 1

    def test_404_when_comp_has_no_fanin(self, client, project, db):
        comp_id = mint(db, Kind.COMP)
        append_event(
            db,
            project.id,
            ev.NodeCreated(
                node_id=comp_id,
                tier="comp",
                kind="domain",
                parent_id=None,
                name="SoloDomain",
                content="<comparch>ok</comparch>",
            ),
        )
        db.commit()
        resp = client.post(f"/api/projects/{project.id}/components/{comp_id}/fanin/regenerate")
        assert resp.status_code == 404


class TestCancelFanIn:
    def test_cancels_queued_job(self, client, project, db):
        comp_id, _ = _seed_fanned_out_domain_with_fanin(db, project.id)
        # Enqueue first, then cancel.
        client.post(f"/api/projects/{project.id}/components/{comp_id}/fanin/regenerate")
        resp = client.post(f"/api/projects/{project.id}/components/{comp_id}/fanin/cancel")
        assert resp.status_code == 200
        assert resp.json() == {"cancelled": True}

        jobs = list(db.execute(select(Job).where(Job.job_type == "v2.generate_fanin")).scalars())
        assert len(jobs) == 1
        assert jobs[0].status == "cancelled"

    def test_cancel_with_no_active_job(self, client, project, db):
        comp_id, _ = _seed_fanned_out_domain_with_fanin(db, project.id)
        resp = client.post(f"/api/projects/{project.id}/components/{comp_id}/fanin/cancel")
        assert resp.status_code == 200
        assert resp.json() == {"cancelled": False}
