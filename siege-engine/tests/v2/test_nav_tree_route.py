"""Tests for GET /projects/:id/nav-tree (workspace sidebar data).

Single batched endpoint that returns the flat node list for the
workspace nav tree. Covers:
- Every sidebar-relevant tier: expansion, reqs, sysarch, subreqs,
  comp (top-level + sub), fanin, impl.
- ``has_content`` reflects trimmed Node.content.
- ``has_pending_draft`` reflects target_type='node' pending drafts.
- ``generation_running`` flips when a tier-matching job is
  queued/running, off when no job or job is in a terminal state.
- Ordering preserved by (tier, display_order, id).
- Empty project returns empty nodes list.
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


def _mint_node(
    db: Session,
    project_id: str,
    kind_enum: Kind,
    *,
    tier: str,
    name: str,
    parent_id: str | None = None,
    content: str = "",
    comp_kind: str = "domain",
    display_order: int = 0,
) -> str:
    node_id = mint(db, kind_enum)
    append_event(
        db,
        project_id,
        ev.NodeCreated(
            node_id=node_id,
            tier=tier,  # type: ignore[arg-type]
            kind=comp_kind,  # type: ignore[arg-type]
            parent_id=parent_id,
            name=name,
            display_order=display_order,
            content=content,
        ),
    )
    return node_id


class TestEmptyProject:
    def test_no_nodes_returns_empty_list(self, client, project):
        resp = client.get(f"/api/projects/{project.id}/nav-tree")
        assert resp.status_code == 200
        assert resp.json() == {"nodes": []}


class TestNodeCoverage:
    def test_ships_every_sidebar_tier(self, client, project, db):
        expansion_id = _mint_node(
            db, project.id, Kind.EXPANSION, tier="expansion", name="Expansion"
        )
        reqs_id = _mint_node(db, project.id, Kind.REQS, tier="reqs", name="Requirements")
        sysarch_id = _mint_node(db, project.id, Kind.SYSARCH, tier="sysarch", name="Sysarch")
        comp_id = _mint_node(
            db, project.id, Kind.COMP, tier="comp", name="Billing", content="<comparch/>"
        )
        sub_id = _mint_node(
            db,
            project.id,
            Kind.COMP,
            tier="comp",
            name="BillingStore",
            parent_id=comp_id,
        )
        subreqs_id = _mint_node(
            db, project.id, Kind.SUBREQS, tier="subreqs", name="Billing subreqs", parent_id=comp_id
        )
        fanin_id = _mint_node(
            db, project.id, Kind.FANIN, tier="fanin", name="Billing fan-in", parent_id=comp_id
        )
        impl_id = _mint_node(
            db, project.id, Kind.IMPL, tier="impl", name="BillingStore impl", parent_id=sub_id
        )
        db.commit()

        resp = client.get(f"/api/projects/{project.id}/nav-tree")
        assert resp.status_code == 200
        body = resp.json()
        ids = [n["id"] for n in body["nodes"]]
        assert set(ids) == {
            expansion_id,
            reqs_id,
            sysarch_id,
            comp_id,
            sub_id,
            subreqs_id,
            fanin_id,
            impl_id,
        }

    def test_excludes_irrelevant_tiers(self, client, project, db):
        # feat / vocab / ref are project-scoped but don't belong
        # in the sidebar tree structure (they surface via their
        # own list views). Confirm they don't leak in.
        _mint_node(db, project.id, Kind.FEAT, tier="feat", name="Billing")
        _mint_node(db, project.id, Kind.VOCAB, tier="vocab", name="tranche")
        _mint_node(db, project.id, Kind.REF, tier="ref", name="Runbook")
        db.commit()

        resp = client.get(f"/api/projects/{project.id}/nav-tree")
        assert resp.json() == {"nodes": []}


class TestHasContent:
    def test_reflects_trimmed_content(self, client, project, db):
        empty = _mint_node(db, project.id, Kind.COMP, tier="comp", name="Empty", content="")
        whitespace = _mint_node(
            db, project.id, Kind.COMP, tier="comp", name="Whitespace", content="   \n  "
        )
        real = _mint_node(
            db, project.id, Kind.COMP, tier="comp", name="Real", content="<comparch/>"
        )
        db.commit()

        nodes = {
            n["id"]: n for n in client.get(f"/api/projects/{project.id}/nav-tree").json()["nodes"]
        }
        assert nodes[empty]["has_content"] is False
        assert nodes[whitespace]["has_content"] is False
        assert nodes[real]["has_content"] is True


class TestHasPendingDraft:
    def test_pending_draft_on_node_sets_flag(self, client, project, db):
        comp_id = _mint_node(
            db, project.id, Kind.COMP, tier="comp", name="Billing", content="<comparch/>"
        )
        append_event(
            db,
            project.id,
            ev.DraftGenerated(
                draft_id="d1",
                target_type="node",
                target_id=comp_id,
                content="<comparch>new</comparch>",
                batch_id="b1",
            ),
        )
        db.commit()

        nodes = {
            n["id"]: n for n in client.get(f"/api/projects/{project.id}/nav-tree").json()["nodes"]
        }
        assert nodes[comp_id]["has_pending_draft"] is True

    def test_approved_draft_does_not_set_flag(self, client, project, db):
        comp_id = _mint_node(
            db, project.id, Kind.COMP, tier="comp", name="Billing", content="<comparch/>"
        )
        append_event(
            db,
            project.id,
            ev.DraftGenerated(
                draft_id="d1",
                target_type="node",
                target_id=comp_id,
                content="<comparch>new</comparch>",
                batch_id="b1",
            ),
        )
        append_event(db, project.id, ev.DraftApproved(draft_id="d1"))
        db.commit()

        nodes = {
            n["id"]: n for n in client.get(f"/api/projects/{project.id}/nav-tree").json()["nodes"]
        }
        assert nodes[comp_id]["has_pending_draft"] is False


class TestGenerationRunning:
    def _enqueue_job(self, db: Session, job_type: str, payload: dict, status: str = "queued"):
        job = Job(
            job_type=job_type,
            payload=payload,
            status=status,
            priority=10,
            max_retries=0,
            created_at=datetime.utcnow(),
        )
        db.add(job)
        db.commit()

    def test_comp_with_active_comparch_job_flagged(self, client, project, db):
        comp_id = _mint_node(db, project.id, Kind.COMP, tier="comp", name="Billing")
        self._enqueue_job(
            db,
            "v2.generate_comparch",
            {"project_id": project.id, "component_id": comp_id},
            status="running",
        )

        nodes = {
            n["id"]: n for n in client.get(f"/api/projects/{project.id}/nav-tree").json()["nodes"]
        }
        assert nodes[comp_id]["generation_running"] is True

    def test_sub_with_active_subcomparch_job_flagged(self, client, project, db):
        comp_id = _mint_node(db, project.id, Kind.COMP, tier="comp", name="Billing")
        sub_id = _mint_node(db, project.id, Kind.COMP, tier="comp", name="Store", parent_id=comp_id)
        self._enqueue_job(
            db,
            "v2.generate_subcomparch",
            {"project_id": project.id, "component_id": sub_id},
        )

        nodes = {
            n["id"]: n for n in client.get(f"/api/projects/{project.id}/nav-tree").json()["nodes"]
        }
        assert nodes[sub_id]["generation_running"] is True
        # Parent comp isn't running — its comparch isn't the
        # subject of the active subcomparch job.
        assert nodes[comp_id]["generation_running"] is False

    def test_fanin_flagged_when_generate_fanin_active(self, client, project, db):
        comp_id = _mint_node(db, project.id, Kind.COMP, tier="comp", name="Billing")
        fanin_id = _mint_node(
            db, project.id, Kind.FANIN, tier="fanin", name="Billing fan-in", parent_id=comp_id
        )
        self._enqueue_job(
            db,
            "v2.generate_fanin",
            {"project_id": project.id, "owner_comp_id": comp_id},
        )

        nodes = {
            n["id"]: n for n in client.get(f"/api/projects/{project.id}/nav-tree").json()["nodes"]
        }
        assert nodes[fanin_id]["generation_running"] is True

    def test_impl_flagged_when_generate_impl_active(self, client, project, db):
        comp_id = _mint_node(db, project.id, Kind.COMP, tier="comp", name="Billing")
        sub_id = _mint_node(db, project.id, Kind.COMP, tier="comp", name="Store", parent_id=comp_id)
        impl_id = _mint_node(
            db, project.id, Kind.IMPL, tier="impl", name="Store impl", parent_id=sub_id
        )
        self._enqueue_job(
            db,
            "v2.generate_impl",
            {"project_id": project.id, "owner_id": sub_id},
        )

        nodes = {
            n["id"]: n for n in client.get(f"/api/projects/{project.id}/nav-tree").json()["nodes"]
        }
        assert nodes[impl_id]["generation_running"] is True

    def test_completed_job_does_not_set_flag(self, client, project, db):
        comp_id = _mint_node(db, project.id, Kind.COMP, tier="comp", name="Billing")
        self._enqueue_job(
            db,
            "v2.generate_comparch",
            {"project_id": project.id, "component_id": comp_id},
            status="completed",
        )

        nodes = {
            n["id"]: n for n in client.get(f"/api/projects/{project.id}/nav-tree").json()["nodes"]
        }
        assert nodes[comp_id]["generation_running"] is False

    def test_other_project_job_does_not_leak(self, client, project, db):
        # A running job from a different project must not set the
        # flag on this project's nodes.
        comp_id = _mint_node(db, project.id, Kind.COMP, tier="comp", name="Billing")
        self._enqueue_job(
            db,
            "v2.generate_comparch",
            {"project_id": "other_project", "component_id": comp_id},
            status="running",
        )

        nodes = {
            n["id"]: n for n in client.get(f"/api/projects/{project.id}/nav-tree").json()["nodes"]
        }
        assert nodes[comp_id]["generation_running"] is False


class TestOrdering:
    def test_nodes_ordered_by_tier_then_display_order(self, client, project, db):
        # Insert out of natural order and verify the response is
        # sorted deterministically.
        c1 = _mint_node(db, project.id, Kind.COMP, tier="comp", name="Gamma", display_order=2)
        c2 = _mint_node(db, project.id, Kind.COMP, tier="comp", name="Alpha", display_order=0)
        c3 = _mint_node(db, project.id, Kind.COMP, tier="comp", name="Beta", display_order=1)
        db.commit()

        body = client.get(f"/api/projects/{project.id}/nav-tree").json()
        ids = [n["id"] for n in body["nodes"]]
        # display_order 0 → 1 → 2
        assert ids == [c2, c3, c1]
