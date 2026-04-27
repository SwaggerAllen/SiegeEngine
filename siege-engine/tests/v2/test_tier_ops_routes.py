"""Tests for the tier-ops routes (reset-all + review-sweep).

Covers:
- ``GET /tiers/{tier}/info`` returns counts + capability flags.
- ``POST /tiers/{tier}/reset-all`` iterates the tier's scopes and
  invokes the per-node reset for each, summing results.
- ``POST /tiers/{tier}/review-sweep`` enqueues a fresh review job
  per node with content, skipping empties.

Two tier shapes are exercised: a singleton (sysarch — single node
per project) and a per-comp tier (comparch — one node per top-level
comp). The seeded fixture has two top-level comps so the per-comp
sweep produces two enqueues / resets.
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
from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from backend.auth.routes import get_current_user  # noqa: E402
from backend.database import Base, get_db  # noqa: E402
from backend.graph import events as ev  # noqa: E402
from backend.graph.fragments import FragmentKind, fragment_id  # noqa: E402
from backend.graph.ids import Kind, mint  # noqa: E402
from backend.graph.reducer import append_event  # noqa: E402
from backend.graph.sysarch import bootstrap_sysarch_node  # noqa: E402
from backend.main import app  # noqa: E402
from backend.models import Project  # noqa: E402
from backend.models.job import Job  # noqa: E402
from backend.models.node import Node  # noqa: E402


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


def _seed_project_with_two_comps(db: Session) -> dict:
    """Seed a project with sysarch approved + two top-level comps,
    each with approved comparch content and a parent resp.

    Returns ``project_id``, ``comp_ids``, ``sysarch_id``.
    """
    project_id = str(uuid.uuid4())
    db.add(Project(id=project_id, name="T", git_repo_path="/tmp/t"))
    db.flush()

    sysarch_id = bootstrap_sysarch_node(db, project_id)
    # Mark the sysarch node as approved by writing content to it.
    append_event(
        db,
        project_id,
        ev.NodeContentUpdated(node_id=sysarch_id, new_content="<sysarch>seeded</sysarch>"),
    )

    comp_ids: list[str] = []
    for idx, name in enumerate(["Billing", "Invoicing"]):
        parent_id = mint(db, Kind.RESP)
        append_event(
            db,
            project_id,
            ev.NodeCreated(
                node_id=parent_id,
                tier="resp",
                kind="domain",
                parent_id=None,
                name=f"{name} Resp",
                display_order=idx,
                content=name,
            ),
        )
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
                display_order=idx,
                content="",
            ),
        )
        for kind, content in (
            (FragmentKind.TECHSPEC, f"{name} role"),
            (FragmentKind.PUBAPI, f"{name} api"),
        ):
            append_event(
                db,
                project_id,
                ev.FragmentUpdated(
                    fragment_id=fragment_id(comp_id, kind),
                    owner_id=comp_id,
                    fragment_kind=kind,
                    new_content=content,
                ),
            )
        edge_id = mint(db, Kind.EDGE)
        append_event(
            db,
            project_id,
            ev.EdgeCreated(
                edge_id=edge_id,
                edge_type="decomposition",
                source_id=parent_id,
                target_id=comp_id,
            ),
        )
        # Approve comparch content directly on the comp_* node so
        # reset-all has something to act on.
        append_event(
            db,
            project_id,
            ev.NodeContentUpdated(
                node_id=comp_id,
                new_content=f"<comparch>{name}</comparch>",
            ),
        )
        comp_ids.append(comp_id)

    db.commit()
    return {"project_id": project_id, "comp_ids": comp_ids, "sysarch_id": sysarch_id}


@pytest.fixture()
def seeded(db):
    return _seed_project_with_two_comps(db)


@pytest.fixture()
def client(db, seeded):
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


# ── /tiers/{tier}/info ─────────────────────────────────────────────


class TestTierInfo:
    def test_singleton_sysarch_reports_one_node(self, client, seeded):
        r = client.get(f"/api/projects/{seeded['project_id']}/tiers/sysarch/info")
        assert r.status_code == 200
        body = r.json()
        assert body["tier"] == "sysarch"
        assert body["tier_name"] == "System architecture"
        assert body["node_count"] == 1
        assert body["nodes_with_content"] == 1
        assert body["supports_reset"] is True
        assert body["supports_review"] is True

    def test_per_comp_comparch_reports_two_nodes(self, client, seeded):
        r = client.get(f"/api/projects/{seeded['project_id']}/tiers/comparch/info")
        assert r.status_code == 200
        body = r.json()
        assert body["node_count"] == 2
        assert body["nodes_with_content"] == 2

    def test_unknown_tier_404s(self, client, seeded):
        r = client.get(f"/api/projects/{seeded['project_id']}/tiers/bogus/info")
        # FastAPI rejects literal-mismatch with 422 before our handler.
        assert r.status_code in (404, 422)

    def test_unknown_project_404s(self, client):
        r = client.get(f"/api/projects/{uuid.uuid4()}/tiers/sysarch/info")
        assert r.status_code == 404


# ── /tiers/{tier}/reset-all ────────────────────────────────────────


class TestResetAll:
    def test_singleton_resets_one_scope(self, client, db, seeded):
        r = client.post(f"/api/projects/{seeded['project_id']}/tiers/sysarch/reset-all")
        assert r.status_code == 200
        body = r.json()
        assert body["tier"] == "sysarch"
        assert body["scopes_total"] == 1
        assert body["scopes_succeeded"] == 1
        assert body["scopes_skipped"] == []

        # The sysarch node's content was cleared and a generate job
        # was enqueued.
        sysarch_node = db.get(Node, seeded["sysarch_id"])
        assert sysarch_node is not None
        assert (sysarch_node.content or "") == ""
        # The bulk handler does a final cancel+re-enqueue pass (so
        # earlier scopes don't get nuked by later scopes' cascading
        # cancels), leaving the original bootstrap_reset enqueue
        # cancelled and a fresh one queued. Filter to queued status.
        queued_jobs = [
            j
            for j in db.execute(
                select(Job).where(
                    Job.job_type == "v2.generate_sysarch",
                    Job.status == "queued",
                )
            ).scalars()
            if j.payload.get("project_id") == seeded["project_id"]
        ]
        assert len(queued_jobs) == 1
        assert body["jobs_enqueued"] == 1

    def test_per_comp_resets_each_top_level_comp(self, client, db, seeded):
        r = client.post(f"/api/projects/{seeded['project_id']}/tiers/comparch/reset-all")
        assert r.status_code == 200
        body = r.json()
        assert body["tier"] == "comparch"
        assert body["scopes_total"] == 2
        assert body["scopes_succeeded"] == 2
        # Bulk reset must queue a generate per scope. Each per-scope
        # bootstrap_reset cancels the tier's generate_job_type
        # project-wide before re-enqueueing, so the bulk handler
        # does a final cancel + per-scope re-enqueue pass to ensure
        # every succeeded scope ends up with a fresh queued job.
        assert body["jobs_enqueued"] == 2

        # Two generate_comparch jobs in the queue, one per comp.
        jobs = [
            j
            for j in db.execute(
                select(Job).where(
                    Job.job_type == "v2.generate_comparch",
                    Job.status == "queued",
                )
            ).scalars()
            if j.payload.get("project_id") == seeded["project_id"]
        ]
        assert len(jobs) == 2
        targeted_comp_ids = {j.payload.get("component_id") for j in jobs}
        assert targeted_comp_ids == set(seeded["comp_ids"])

    def test_unknown_project_404s(self, client):
        r = client.post(f"/api/projects/{uuid.uuid4()}/tiers/sysarch/reset-all")
        assert r.status_code == 404

    def test_force_resets_unapproved_scope(self, client, db, seeded):
        """A comp with no approved comparch content must still reset
        under the bulk sweep — force=True bypasses the approval
        gate. Mirrors the dev-project case the user hit."""
        # Wipe one comp's content back to empty (pre-approval state).
        unapproved = db.get(Node, seeded["comp_ids"][0])
        assert unapproved is not None
        unapproved.content = ""
        db.commit()

        r = client.post(f"/api/projects/{seeded['project_id']}/tiers/comparch/reset-all")
        assert r.status_code == 200
        body = r.json()
        # Both scopes succeeded — the unapproved one was force-reset
        # rather than skipped with 409.
        assert body["scopes_total"] == 2
        assert body["scopes_succeeded"] == 2
        assert body["scopes_skipped"] == []
        # And both got a queued generate.
        assert body["jobs_enqueued"] == 2
        queued = [
            j
            for j in db.execute(
                select(Job).where(
                    Job.job_type == "v2.generate_comparch",
                    Job.status == "queued",
                )
            ).scalars()
            if j.payload.get("project_id") == seeded["project_id"]
        ]
        assert len(queued) == 2


# ── /tiers/{tier}/review-sweep ─────────────────────────────────────


class TestReviewSweep:
    def test_singleton_enqueues_one_review(self, client, db, seeded):
        r = client.post(f"/api/projects/{seeded['project_id']}/tiers/sysarch/review-sweep")
        assert r.status_code == 200
        body = r.json()
        assert body["tier"] == "sysarch"
        assert body["scopes_total"] == 1
        assert body["jobs_enqueued"] == 1
        assert body["scopes_skipped"] == []

        review_jobs = [
            j
            for j in db.execute(select(Job).where(Job.job_type == "v2.review_sysarch")).scalars()
            if j.payload.get("project_id") == seeded["project_id"]
        ]
        assert len(review_jobs) == 1

    def test_per_comp_enqueues_review_per_comp(self, client, db, seeded):
        r = client.post(f"/api/projects/{seeded['project_id']}/tiers/comparch/review-sweep")
        assert r.status_code == 200
        body = r.json()
        assert body["scopes_total"] == 2
        assert body["jobs_enqueued"] == 2

        review_jobs = [
            j
            for j in db.execute(select(Job).where(Job.job_type == "v2.review_comparch")).scalars()
            if j.payload.get("project_id") == seeded["project_id"]
        ]
        assert len(review_jobs) == 2
        targeted_node_ids = {j.payload.get("node_id") for j in review_jobs}
        # Each of the two top-level comps in the fixture should
        # have a review job targeting its own comp_* id.
        assert targeted_node_ids == set(seeded["comp_ids"])

    def test_skips_nodes_with_no_content(self, client, db, seeded):
        # Clear one comp's content so the review-sweep skips it.
        target = db.get(Node, seeded["comp_ids"][0])
        assert target is not None
        target.content = ""
        db.commit()

        r = client.post(f"/api/projects/{seeded['project_id']}/tiers/comparch/review-sweep")
        assert r.status_code == 200
        body = r.json()
        assert body["jobs_enqueued"] == 1
        assert len(body["scopes_skipped"]) == 1
        assert body["scopes_skipped"][0]["status"] == 409
