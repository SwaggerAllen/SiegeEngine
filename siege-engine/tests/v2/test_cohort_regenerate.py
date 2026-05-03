"""Tests for the Phase 3b cohort regenerate + exploration + full-corpus
endpoints, plus bootstrap_feedback ``force=True`` bypass."""

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
from backend.graph.ids import Kind, mint  # noqa: E402
from backend.graph.reducer import append_event  # noqa: E402
from backend.main import app  # noqa: E402
from backend.models import Project, User  # noqa: E402
from backend.models.batch import Batch  # noqa: E402
from backend.models.job import Job  # noqa: E402

# ── Fixtures ───────────────────────────────────────────────────────


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
def client(engine_and_factory):
    _, factory = engine_and_factory

    def _override_db():
        s = factory()
        try:
            yield s
        finally:
            s.close()

    def _override_user():
        return User(id="u1", username="t", password_hash="x", role="admin")

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user] = _override_user
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _seed_project(db: Session) -> str:
    project_id = str(uuid.uuid4())
    db.add(Project(id=project_id, name="T", git_repo_path="/tmp/t"))
    db.flush()
    return project_id


def _seed_top_level_comp(db: Session, project_id: str, *, name: str, content: str = "") -> str:
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
            content=content,
        ),
    )
    return comp_id


def _seed_subcomp(
    db: Session,
    project_id: str,
    *,
    parent_id: str,
    name: str,
    content: str = "",
) -> str:
    sub_id = mint(db, Kind.COMP)
    append_event(
        db,
        project_id,
        ev.NodeCreated(
            node_id=sub_id,
            tier="comp",
            kind="domain",
            parent_id=parent_id,
            name=name,
            display_order=0,
            content=content,
        ),
    )
    return sub_id


# ── Cohort regenerate ─────────────────────────────────────────────


class TestCohortRegenerate:
    def test_review_mode_enqueues_subs_under_one_batch(self, db, client):
        project_id = _seed_project(db)
        # Two cohort comps, each with two subs (with content so the
        # bootstrap_feedback path doesn't 409 on missing-pending-
        # draft — we set up an approved scope).
        comp_a = _seed_top_level_comp(db, project_id, name="A")
        comp_b = _seed_top_level_comp(db, project_id, name="B")
        for parent in (comp_a, comp_b):
            for n in ("x", "y"):
                _seed_subcomp(
                    db, project_id, parent_id=parent, name=f"{n}", content="<subcomparch/>"
                )
        # Cohort over both top-level comps.
        cohort_resp = client.post(
            f"/api/projects/{project_id}/cohorts",
            json={"tier": "comparch", "name": "c", "comp_ids": [comp_a, comp_b]},
        )
        cohort_id = cohort_resp.json()["id"]
        db.commit()

        resp = client.post(
            f"/api/projects/{project_id}/cohorts/{cohort_id}/regenerate",
            json={"mode": "review"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["mode"] == "review"
        assert body["target_tier"] == "subcomparch"
        assert body["scopes_total"] == 4
        # All 4 succeeded — bootstrap_feedback with force bypasses
        # the approved-content gate (the subs have content).
        assert body["scopes_succeeded"] == 4
        assert body["scopes_skipped"] == []
        batch_id = body["batch_id"]
        # All 4 enqueued generate jobs share the batch_id.
        gen_jobs = list(
            db.execute(
                select(Job).where(
                    Job.job_type == "v2.generate_subcomparch",
                    Job.batch_id == batch_id,
                )
            ).scalars()
        )
        assert len(gen_jobs) == 4
        # Batch row records the mode.
        batch = db.get(Batch, batch_id)
        assert batch is not None
        assert batch.params == {"mode": "review"}
        assert batch.op_type == "cohort_regenerate"

    def test_fresh_mode_uses_reset_path(self, db, client):
        project_id = _seed_project(db)
        comp_a = _seed_top_level_comp(db, project_id, name="A")
        sub_id = _seed_subcomp(
            db, project_id, parent_id=comp_a, name="x", content="<subcomparch>old</subcomparch>"
        )
        cohort_resp = client.post(
            f"/api/projects/{project_id}/cohorts",
            json={"tier": "comparch", "name": "c", "comp_ids": [comp_a]},
        )
        cohort_id = cohort_resp.json()["id"]
        db.commit()
        resp = client.post(
            f"/api/projects/{project_id}/cohorts/{cohort_id}/regenerate",
            json={"mode": "fresh"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["mode"] == "fresh"
        # The reset path wipes the sub's content via
        # BootstrapNodeContentCleared.
        db.refresh_all = lambda: None  # noqa: B023 — keep linter quiet
        from backend.models.node import Node as NodeModel

        sub = db.get(NodeModel, sub_id)
        db.refresh(sub)
        assert (sub.content or "") == ""
        # Batch records mode=fresh.
        batch = db.get(Batch, body["batch_id"])
        assert batch is not None
        assert batch.params == {"mode": "fresh"}

    def test_unknown_cohort_404(self, db, client):
        project_id = _seed_project(db)
        db.commit()
        resp = client.post(
            f"/api/projects/{project_id}/cohorts/cohort_nope/regenerate",
            json={"mode": "review"},
        )
        assert resp.status_code == 404


# ── Exploration sample ────────────────────────────────────────────


class TestExplorationSample:
    def test_picks_random_comps_outside_cohort_and_excludes_prior(self, db, client):
        project_id = _seed_project(db)
        # 5 top-level comps, each with a sub.
        comp_ids = []
        for i in range(5):
            cid = _seed_top_level_comp(db, project_id, name=f"C{i}")
            comp_ids.append(cid)
            _seed_subcomp(db, project_id, parent_id=cid, name=f"{i}sub")
        # Save a cohort over the first 2.
        cohort_id = client.post(
            f"/api/projects/{project_id}/cohorts",
            json={
                "tier": "comparch",
                "name": "c",
                "comp_ids": comp_ids[:2],
            },
        ).json()["id"]
        db.commit()
        # First exploration sample: pick 2 from outside cohort (3 left).
        resp = client.post(
            f"/api/projects/{project_id}/tiers/subcomparch/exploration-sample",
            json={"count": 2, "exclude_cohort_id": cohort_id},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        first_picked = set(body["picked_comp_ids"])
        assert len(first_picked) == 2
        assert first_picked.isdisjoint(comp_ids[:2])
        # Second exploration: should pick from the remaining 1 unsampled.
        resp = client.post(
            f"/api/projects/{project_id}/tiers/subcomparch/exploration-sample",
            json={"count": 5, "exclude_cohort_id": cohort_id},
        )
        body2 = resp.json()
        second_picked = set(body2["picked_comp_ids"])
        # Only 1 candidate left (5 total - 2 cohort - 2 prior sample).
        assert len(second_picked) == 1
        # Pre/post intersection is empty (no overlap with prior sample).
        assert second_picked.isdisjoint(first_picked)

    def test_409_when_pool_exhausted(self, db, client):
        project_id = _seed_project(db)
        c1 = _seed_top_level_comp(db, project_id, name="C1")
        cohort_id = client.post(
            f"/api/projects/{project_id}/cohorts",
            json={"tier": "comparch", "name": "c", "comp_ids": [c1]},
        ).json()["id"]
        db.commit()
        resp = client.post(
            f"/api/projects/{project_id}/tiers/subcomparch/exploration-sample",
            json={"count": 1, "exclude_cohort_id": cohort_id},
        )
        assert resp.status_code == 409


# ── Full corpus ───────────────────────────────────────────────────


class TestFullCorpus:
    def test_enqueues_every_subcomp(self, db, client):
        project_id = _seed_project(db)
        c1 = _seed_top_level_comp(db, project_id, name="C1")
        c2 = _seed_top_level_comp(db, project_id, name="C2")
        for c in (c1, c2):
            _seed_subcomp(db, project_id, parent_id=c, name="x")
            _seed_subcomp(db, project_id, parent_id=c, name="y")
        db.commit()
        resp = client.post(f"/api/projects/{project_id}/tiers/subcomparch/full-corpus")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["scopes_total"] == 4
        assert body["scopes_succeeded"] == 4
        # All 4 jobs share the batch_id.
        jobs = list(
            db.execute(
                select(Job).where(
                    Job.job_type == "v2.generate_subcomparch",
                    Job.batch_id == body["batch_id"],
                )
            ).scalars()
        )
        assert len(jobs) == 4


# ── force=True on bootstrap_feedback ──────────────────────────────


class TestBootstrapFeedbackForce:
    def test_force_bypasses_approved_gate(self, db, client):
        """The cohort regenerate path passes force=True so a sub
        with approved content can still receive a regen. Without
        force, bootstrap_feedback 409s on approved scopes."""
        project_id = _seed_project(db)
        c1 = _seed_top_level_comp(db, project_id, name="A", content="<comparch/>")
        sub_id = _seed_subcomp(db, project_id, parent_id=c1, name="x", content="<subcomparch/>")
        cohort_id = client.post(
            f"/api/projects/{project_id}/cohorts",
            json={"tier": "comparch", "name": "c", "comp_ids": [c1]},
        ).json()["id"]
        db.commit()
        # mode=review uses bootstrap_feedback(force=True). The sub
        # has approved content; without force it would 409. With
        # force the regen succeeds + a job lands.
        resp = client.post(
            f"/api/projects/{project_id}/cohorts/{cohort_id}/regenerate",
            json={"mode": "review"},
        )
        assert resp.status_code == 200
        assert resp.json()["scopes_succeeded"] == 1
        # Verify the new gen job's payload references this sub. The
        # subcomparch handler reads ``payload["component_id"]`` and
        # treats it as the sub id (it does ``db.get(Node,
        # component_id)`` and expects the row back) — confusing but
        # consistent with the per-node-route convention.
        jobs = list(
            db.execute(
                select(Job)
                .where(Job.job_type == "v2.generate_subcomparch")
                .order_by(Job.created_at.desc())
            ).scalars()
        )
        assert any((j.payload or {}).get("component_id") == sub_id for j in jobs)
