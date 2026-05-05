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
    def test_comparch_cohort_review_mode_enqueues_comparch_jobs(self, db, client):
        """Comparch cohort drives comparch generation directly — no
        walk to subs. Each cohort comp becomes a (comp_id,) scope."""
        project_id = _seed_project(db)
        comp_a = _seed_top_level_comp(db, project_id, name="A", content="<comparch/>")
        comp_b = _seed_top_level_comp(db, project_id, name="B", content="<comparch/>")
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
        assert body["target_tier"] == "comparch"
        assert body["scopes_total"] == 2
        assert body["scopes_succeeded"] == 2
        assert body["scopes_skipped"] == []
        batch_id = body["batch_id"]
        # Both enqueued comparch jobs share the batch_id.
        gen_jobs = list(
            db.execute(
                select(Job).where(
                    Job.job_type == "v2.generate_comparch",
                    Job.batch_id == batch_id,
                )
            ).scalars()
        )
        assert len(gen_jobs) == 2
        batch = db.get(Batch, batch_id)
        assert batch is not None
        assert batch.params == {"mode": "review", "exploration_count": 0}
        assert batch.op_type == "cohort_regenerate"
        assert batch.tier == "comparch"

    def test_comparch_cohort_fresh_mode_uses_reset_path(self, db, client):
        project_id = _seed_project(db)
        comp_a = _seed_top_level_comp(db, project_id, name="A", content="<comparch>old</comparch>")
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
        # The reset path wipes the comp's content via
        # BootstrapNodeContentCleared.
        from backend.models.node import Node as NodeModel

        comp = db.get(NodeModel, comp_a)
        db.refresh(comp)
        assert (comp.content or "") == ""
        batch = db.get(Batch, body["batch_id"])
        assert batch is not None
        assert batch.params == {"mode": "fresh", "exploration_count": 0}

    def test_fresh_mode_preserves_sibling_jobs_in_same_batch(self, db, client):
        """Regression: bootstrap_reset's job-cancellation sweep
        cancels every queued job of the tier's downstream types,
        which (for comparch) includes ``v2.generate_comparch``
        itself. Without batch-aware exclusion, each cohort comp's
        reset call cancels the previously-queued sibling jobs,
        leaving only the last one. The fix passes the cohort
        regen's batch_id as exclude_batch_id to the cancel sweep."""
        project_id = _seed_project(db)
        comps = [
            _seed_top_level_comp(db, project_id, name=f"C{i}", content="<comparch/>")
            for i in range(5)
        ]
        cohort_id = client.post(
            f"/api/projects/{project_id}/cohorts",
            json={"tier": "comparch", "name": "c", "comp_ids": comps},
        ).json()["id"]
        db.commit()

        resp = client.post(
            f"/api/projects/{project_id}/cohorts/{cohort_id}/regenerate",
            json={"mode": "fresh"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["scopes_succeeded"] == 5

        # All five comparch jobs must be queued under the same batch
        # — a regression against this would leave only one (the last).
        queued = list(
            db.execute(
                select(Job).where(
                    Job.job_type == "v2.generate_comparch",
                    Job.batch_id == body["batch_id"],
                    Job.status == "queued",
                )
            ).scalars()
        )
        assert len(queued) == 5
        # And each queued job should reference a distinct cohort comp.
        comp_ids_on_jobs = {(j.payload or {}).get("component_id") for j in queued}
        assert comp_ids_on_jobs == set(comps)

    def test_subcomparch_cohort_walks_to_subs(self, db, client):
        """Subcomparch cohort walks from each cohort comp to its subs,
        enqueueing one subcomparch job per sub."""
        project_id = _seed_project(db)
        comp_a = _seed_top_level_comp(db, project_id, name="A")
        comp_b = _seed_top_level_comp(db, project_id, name="B")
        for parent in (comp_a, comp_b):
            for n in ("x", "y"):
                _seed_subcomp(
                    db, project_id, parent_id=parent, name=f"{n}", content="<subcomparch/>"
                )
        cohort_id = client.post(
            f"/api/projects/{project_id}/cohorts",
            json={"tier": "subcomparch", "name": "sc", "comp_ids": [comp_a, comp_b]},
        ).json()["id"]
        db.commit()

        resp = client.post(
            f"/api/projects/{project_id}/cohorts/{cohort_id}/regenerate",
            json={"mode": "review"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["target_tier"] == "subcomparch"
        # 2 cohort comps × 2 subs each = 4 subcomparch jobs.
        assert body["scopes_total"] == 4
        assert body["scopes_succeeded"] == 4
        gen_jobs = list(
            db.execute(
                select(Job).where(
                    Job.job_type == "v2.generate_subcomparch",
                    Job.batch_id == body["batch_id"],
                )
            ).scalars()
        )
        assert len(gen_jobs) == 4

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
    def test_subcomparch_picks_random_comps_outside_cohort_and_excludes_prior(self, db, client):
        project_id = _seed_project(db)
        # 5 top-level comps, each with a sub (target=subcomparch
        # walks to subs).
        comp_ids = []
        for i in range(5):
            cid = _seed_top_level_comp(db, project_id, name=f"C{i}")
            comp_ids.append(cid)
            _seed_subcomp(db, project_id, parent_id=cid, name=f"{i}sub")
        # Save a subcomparch cohort over the first 2.
        cohort_id = client.post(
            f"/api/projects/{project_id}/cohorts",
            json={
                "tier": "subcomparch",
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

    def test_comparch_picks_top_comps_and_runs_comparch(self, db, client):
        """Comparch tier exploration-sample picks top-level comps and
        runs comparch generation directly — no walk to subs."""
        project_id = _seed_project(db)
        comp_ids = [
            _seed_top_level_comp(db, project_id, name=f"C{i}", content="<comparch/>")
            for i in range(3)
        ]
        cohort_id = client.post(
            f"/api/projects/{project_id}/cohorts",
            json={"tier": "comparch", "name": "c", "comp_ids": [comp_ids[0]]},
        ).json()["id"]
        db.commit()
        resp = client.post(
            f"/api/projects/{project_id}/tiers/comparch/exploration-sample",
            json={"count": 2, "exclude_cohort_id": cohort_id},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["tier"] == "comparch"
        # 2 comps picked, each becomes one comparch job.
        assert len(body["picked_comp_ids"]) == 2
        assert body["scopes_succeeded"] == 2
        comparch_jobs = list(
            db.execute(
                select(Job).where(
                    Job.job_type == "v2.generate_comparch",
                    Job.batch_id == body["batch_id"],
                )
            ).scalars()
        )
        assert len(comparch_jobs) == 2

    def test_409_when_pool_exhausted(self, db, client):
        project_id = _seed_project(db)
        c1 = _seed_top_level_comp(db, project_id, name="C1")
        cohort_id = client.post(
            f"/api/projects/{project_id}/cohorts",
            json={"tier": "subcomparch", "name": "c", "comp_ids": [c1]},
        ).json()["id"]
        db.commit()
        resp = client.post(
            f"/api/projects/{project_id}/tiers/subcomparch/exploration-sample",
            json={"count": 1, "exclude_cohort_id": cohort_id},
        )
        assert resp.status_code == 409


# ── Active-explored working set ───────────────────────────────────


class TestActiveExploredWorkingSet:
    """Exploration sample's picks tag the cohort and ride along on
    subsequent regenerate calls. Fresh-mode regen resets the working
    set via temporal cutoff so the next regen sees only canonical."""

    def test_review_after_exploration_covers_explored_comps(self, db, client):
        project_id = _seed_project(db)
        canonical = [
            _seed_top_level_comp(db, project_id, name=f"K{i}", content="<comparch/>")
            for i in range(2)
        ]
        explorable = [
            _seed_top_level_comp(db, project_id, name=f"X{i}", content="<comparch/>")
            for i in range(3)
        ]
        cohort_id = client.post(
            f"/api/projects/{project_id}/cohorts",
            json={"tier": "comparch", "name": "c", "comp_ids": canonical},
        ).json()["id"]
        db.commit()
        # Exploration sample with parent_cohort link
        exp_resp = client.post(
            f"/api/projects/{project_id}/tiers/comparch/exploration-sample",
            json={"count": len(explorable), "exclude_cohort_id": cohort_id},
        )
        assert exp_resp.status_code == 200, exp_resp.text
        sampled = set(exp_resp.json()["picked_comp_ids"])
        assert sampled == set(explorable)
        # Subsequent review-mode regen covers canonical + sampled
        resp = client.post(
            f"/api/projects/{project_id}/cohorts/{cohort_id}/regenerate",
            json={"mode": "review"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["scopes_total"] == 5
        assert body["scopes_succeeded"] == 5
        regen_jobs = list(
            db.execute(
                select(Job).where(
                    Job.job_type == "v2.generate_comparch",
                    Job.batch_id == body["batch_id"],
                )
            ).scalars()
        )
        comp_ids_on_jobs = {(j.payload or {}).get("component_id") for j in regen_jobs}
        assert comp_ids_on_jobs == set(canonical) | set(explorable)

    def test_fresh_does_not_enqueue_regen_for_prior_exploration(self, db, client):
        """Fresh-mode regen runs on canonical only — prior-cycle
        exploration comps don't get a regen job under the fresh
        batch. The temporal cutoff then buries the prior exploration
        batch from future review-mode regens too."""
        project_id = _seed_project(db)
        canonical = _seed_top_level_comp(db, project_id, name="K", content="<comparch/>")
        _seed_top_level_comp(db, project_id, name="X", content="<comparch/>")
        cohort_id = client.post(
            f"/api/projects/{project_id}/cohorts",
            json={"tier": "comparch", "name": "c", "comp_ids": [canonical]},
        ).json()["id"]
        db.commit()
        # Sample → adds X to working set under its own exploration batch.
        client.post(
            f"/api/projects/{project_id}/tiers/comparch/exploration-sample",
            json={"count": 1, "exclude_cohort_id": cohort_id},
        )
        # Fresh-mode regen — runs on canonical only. The prior
        # exploration comp does NOT get a fresh-batch regen job.
        fresh_resp = client.post(
            f"/api/projects/{project_id}/cohorts/{cohort_id}/regenerate",
            json={"mode": "fresh"},
        )
        assert fresh_resp.json()["scopes_total"] == 1
        fresh_jobs = list(
            db.execute(
                select(Job).where(
                    Job.job_type == "v2.generate_comparch",
                    Job.batch_id == fresh_resp.json()["batch_id"],
                )
            ).scalars()
        )
        fresh_comp_ids = {(j.payload or {}).get("component_id") for j in fresh_jobs}
        assert fresh_comp_ids == {canonical}
        # Subsequent review-mode regen should NOT include the
        # explored comp — temporal cutoff buried the exploration batch.
        review_resp = client.post(
            f"/api/projects/{project_id}/cohorts/{cohort_id}/regenerate",
            json={"mode": "review"},
        )
        assert review_resp.status_code == 200, review_resp.text
        body = review_resp.json()
        assert body["scopes_total"] == 1
        review_jobs = list(
            db.execute(
                select(Job).where(
                    Job.job_type == "v2.generate_comparch",
                    Job.batch_id == body["batch_id"],
                )
            ).scalars()
        )
        comp_ids_on_jobs = {(j.payload or {}).get("component_id") for j in review_jobs}
        assert comp_ids_on_jobs == {canonical}

    def test_fresh_with_exploration_count_baselines_new_picks(self, db, client):
        """Fresh-mode regen with exploration_count > 0 picks N new
        comps and tags them parent_cohort_id so they join the working
        set for the next review cycle."""
        project_id = _seed_project(db)
        canonical = _seed_top_level_comp(db, project_id, name="K", content="<comparch/>")
        for i in range(4):
            _seed_top_level_comp(db, project_id, name=f"X{i}", content="<comparch/>")
        cohort_id = client.post(
            f"/api/projects/{project_id}/cohorts",
            json={"tier": "comparch", "name": "c", "comp_ids": [canonical]},
        ).json()["id"]
        db.commit()

        fresh_resp = client.post(
            f"/api/projects/{project_id}/cohorts/{cohort_id}/regenerate",
            json={"mode": "fresh", "exploration_count": 2},
        )
        assert fresh_resp.status_code == 200, fresh_resp.text
        body = fresh_resp.json()
        # Canonical-only scope walk: 1 canonical comp.
        assert body["scopes_total"] == 1
        # Exploration ran inline.
        assert body["exploration"] is not None
        assert body["exploration"]["ok"] is True
        assert len(body["exploration"]["picked_comp_ids"]) == 2
        # Subsequent review should cover canonical + 2 explored.
        review_resp = client.post(
            f"/api/projects/{project_id}/cohorts/{cohort_id}/regenerate",
            json={"mode": "review"},
        )
        review_body = review_resp.json()
        assert review_body["scopes_total"] == 3

    def test_post_fresh_exploration_rejoins_working_set(self, db, client):
        """After a fresh reset, a NEW exploration sample's picks
        should join the working set again — the cutoff only buries
        pre-fresh exploration batches."""
        project_id = _seed_project(db)
        canonical = _seed_top_level_comp(db, project_id, name="K", content="<comparch/>")
        # Two explorable comps so the random pick has alternatives
        # across pre/post fresh.
        for n in ("X1", "X2"):
            _seed_top_level_comp(db, project_id, name=n, content="<comparch/>")
        cohort_id = client.post(
            f"/api/projects/{project_id}/cohorts",
            json={"tier": "comparch", "name": "c", "comp_ids": [canonical]},
        ).json()["id"]
        db.commit()
        # Pre-fresh exploration → first explorable joins (which one
        # depends on rng; record it).
        pre_resp = client.post(
            f"/api/projects/{project_id}/tiers/comparch/exploration-sample",
            json={"count": 1, "exclude_cohort_id": cohort_id},
        )
        pre_picked = set(pre_resp.json()["picked_comp_ids"])
        # Fresh resets working set
        client.post(
            f"/api/projects/{project_id}/cohorts/{cohort_id}/regenerate",
            json={"mode": "fresh"},
        )
        # Post-fresh exploration → the OTHER explorable joins (the
        # exclusion pool excludes the pre-fresh pick).
        post_resp = client.post(
            f"/api/projects/{project_id}/tiers/comparch/exploration-sample",
            json={"count": 1, "exclude_cohort_id": cohort_id},
        )
        post_picked = set(post_resp.json()["picked_comp_ids"])
        assert post_picked.isdisjoint(pre_picked)
        # Review covers canonical + post-fresh pick (pre-fresh pick
        # was buried by the fresh cutoff).
        review_resp = client.post(
            f"/api/projects/{project_id}/cohorts/{cohort_id}/regenerate",
            json={"mode": "review"},
        )
        body = review_resp.json()
        regen_jobs = list(
            db.execute(
                select(Job).where(
                    Job.job_type == "v2.generate_comparch",
                    Job.batch_id == body["batch_id"],
                )
            ).scalars()
        )
        comp_ids_on_jobs = {(j.payload or {}).get("component_id") for j in regen_jobs}
        assert comp_ids_on_jobs == {canonical} | post_picked


# ── Full corpus ───────────────────────────────────────────────────


class TestFullCorpus:
    def test_subcomparch_enqueues_every_subcomp(self, db, client):
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
        assert body["tier"] == "subcomparch"
        assert body["scopes_total"] == 4
        assert body["scopes_succeeded"] == 4
        jobs = list(
            db.execute(
                select(Job).where(
                    Job.job_type == "v2.generate_subcomparch",
                    Job.batch_id == body["batch_id"],
                )
            ).scalars()
        )
        assert len(jobs) == 4

    def test_comparch_enqueues_every_top_level_comp(self, db, client):
        project_id = _seed_project(db)
        for name in ("A", "B", "C"):
            _seed_top_level_comp(db, project_id, name=name)
        db.commit()
        resp = client.post(f"/api/projects/{project_id}/tiers/comparch/full-corpus")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["tier"] == "comparch"
        assert body["scopes_total"] == 3
        assert body["scopes_succeeded"] == 3
        jobs = list(
            db.execute(
                select(Job).where(
                    Job.job_type == "v2.generate_comparch",
                    Job.batch_id == body["batch_id"],
                )
            ).scalars()
        )
        assert len(jobs) == 3


# ── force=True on bootstrap_feedback ──────────────────────────────


class TestBootstrapFeedbackForce:
    def test_force_bypasses_approved_gate(self, db, client):
        """The cohort regenerate path passes force=True so a comp
        with approved content can still receive a regen. Without
        force, bootstrap_feedback 409s on approved scopes."""
        project_id = _seed_project(db)
        c1 = _seed_top_level_comp(db, project_id, name="A", content="<comparch/>")
        cohort_id = client.post(
            f"/api/projects/{project_id}/cohorts",
            json={"tier": "comparch", "name": "c", "comp_ids": [c1]},
        ).json()["id"]
        db.commit()
        # mode=review uses bootstrap_feedback(force=True). The comp
        # has approved content; without force it would 409. With
        # force the regen succeeds + a job lands.
        resp = client.post(
            f"/api/projects/{project_id}/cohorts/{cohort_id}/regenerate",
            json={"mode": "review"},
        )
        assert resp.status_code == 200
        assert resp.json()["scopes_succeeded"] == 1
        jobs = list(
            db.execute(
                select(Job)
                .where(Job.job_type == "v2.generate_comparch")
                .order_by(Job.created_at.desc())
            ).scalars()
        )
        assert any((j.payload or {}).get("component_id") == c1 for j in jobs)
