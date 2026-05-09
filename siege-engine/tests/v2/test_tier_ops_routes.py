"""Tests for the tier-ops routes (reset-all + review-sweep).

Covers:
- ``GET /tiers/{tier}/info`` returns counts + capability flags.
- ``POST /tiers/{tier}/reset-all`` iterates the tier's scopes and
  invokes the per-node reset for each, summing results.
- ``POST /tiers/{tier}/review-sweep`` fans the per-node "Reject &
  Regenerate" action across every scope: each pending draft's AI
  review rides forward as ``prior_review_text``, the stale review
  is cleared, in-flight review jobs are cancelled, and a fresh
  generation job is enqueued. Approved-only scopes 409-skip.

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
        # Approved content counts as reviewable.
        assert body["reviewable_count"] == 2

    def test_reviewable_count_includes_pending_drafts(self, client, db, seeded):
        """A scope with only a pending draft (no approved content)
        is still reviewable — bootstrap_retry_review accepts the
        pending draft as the review target."""
        from backend.models.node import Draft, Node

        # Find the two seeded comps and clear their content so they're
        # back in the "pending draft" state — only the draft on one of
        # them carries a pending row.
        comps = (
            db.execute(
                select(Node).where(
                    Node.project_id == seeded["project_id"],
                    Node.tier == "comp",
                    Node.parent_id.is_(None),
                )
            )
            .scalars()
            .all()
        )
        for comp in comps:
            comp.content = ""
        # Add a pending draft on the first comp; leave the second
        # with neither content nor draft.
        db.add(
            Draft(
                id=f"draft_{uuid.uuid4().hex[:8]}",
                project_id=seeded["project_id"],
                target_type="node",
                target_id=comps[0].id,
                content="<comparch>regen wip</comparch>",
                status="pending",
                batch_id=f"batch_{uuid.uuid4().hex[:8]}",
            )
        )
        db.commit()

        r = client.get(f"/api/projects/{seeded['project_id']}/tiers/comparch/info")
        assert r.status_code == 200
        body = r.json()
        assert body["nodes_with_content"] == 0
        # Only the comp with a pending draft is reviewable.
        assert body["reviewable_count"] == 1

    def test_avg_generation_seconds_is_null_with_no_completed_jobs(self, client, seeded):
        r = client.get(f"/api/projects/{seeded['project_id']}/tiers/comparch/info")
        body = r.json()
        assert body["avg_generation_seconds"] is None
        assert body["generation_sample_size"] == 0

    def test_avg_generation_seconds_means_completed_run_durations(self, client, db, seeded):
        from datetime import datetime, timedelta

        # Two completed comparch generations, ran 10s and 20s.
        # Average should be 15.
        base = datetime(2026, 4, 29, 12, 0, 0)
        for delay_seconds, comp_id in zip([10, 20], seeded["comp_ids"]):
            db.add(
                Job(
                    job_type="v2.generate_comparch",
                    status="completed",
                    payload={"project_id": seeded["project_id"], "component_id": comp_id},
                    locked_at=base,
                    completed_at=base + timedelta(seconds=delay_seconds),
                )
            )
        # A completed generation for a DIFFERENT project — must not
        # leak into this project's average.
        db.add(
            Job(
                job_type="v2.generate_comparch",
                status="completed",
                payload={"project_id": str(uuid.uuid4()), "component_id": "comp_other"},
                locked_at=base,
                completed_at=base + timedelta(seconds=99999),
            )
        )
        # A still-running generation for THIS project — must be
        # excluded (status != completed).
        db.add(
            Job(
                job_type="v2.generate_comparch",
                status="running",
                payload={"project_id": seeded["project_id"], "component_id": "comp_x"},
                locked_at=base,
                completed_at=None,
            )
        )
        db.commit()

        r = client.get(f"/api/projects/{seeded['project_id']}/tiers/comparch/info")
        body = r.json()
        assert body["generation_sample_size"] == 2
        assert body["avg_generation_seconds"] == 15.0

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
    """Tier-ops "Regen From Reviews" — per-scope wrapper around
    ``bootstrap_feedback("")``. Pending-draft scopes regen with
    ``prior_review_text`` riding forward; approved-only scopes
    409-skip and report in the result line.
    """

    def test_skips_approved_singleton(self, client, db, seeded):
        # Sysarch is seeded as approved with no pending draft.
        # bootstrap_feedback raises 409 on approved scopes, so the
        # sweep reports the skip rather than enqueueing a regen.
        r = client.post(f"/api/projects/{seeded['project_id']}/tiers/sysarch/review-sweep")
        assert r.status_code == 200
        body = r.json()
        assert body["tier"] == "sysarch"
        assert body["scopes_total"] == 1
        assert body["jobs_enqueued"] == 0
        assert len(body["scopes_skipped"]) == 1
        assert body["scopes_skipped"][0]["status"] == 409

        # No review job enqueued — that pathway is gone.
        review_jobs = [
            j
            for j in db.execute(select(Job).where(Job.job_type == "v2.review_sysarch")).scalars()
            if j.payload.get("project_id") == seeded["project_id"]
        ]
        assert len(review_jobs) == 0

    def test_skips_approved_comps(self, client, db, seeded):
        # Both seeded comparch comps are approved with no pending
        # drafts; both should 409-skip.
        r = client.post(f"/api/projects/{seeded['project_id']}/tiers/comparch/review-sweep")
        assert r.status_code == 200
        body = r.json()
        assert body["scopes_total"] == 2
        assert body["jobs_enqueued"] == 0
        assert len(body["scopes_skipped"]) == 2
        assert all(s["status"] == 409 for s in body["scopes_skipped"])

    def test_pending_draft_regens_with_prior_review_text(self, client, db, seeded):
        # Convert one comp from approved to pending: clear its
        # node content so the approval gate opens, then add a
        # pending draft with a non-empty review_text. The sweep
        # should enqueue a regen for that scope with the review
        # riding on the payload, preserve the prior review on the
        # discarded draft (so the user can do a clean rerun on
        # failure), and report the still-approved comp as skipped.
        from backend.models.node import Draft

        target_id = seeded["comp_ids"][0]
        target = db.get(Node, target_id)
        assert target is not None
        target.content = ""
        draft = Draft(
            id=f"draft_{uuid.uuid4().hex[:8]}",
            project_id=seeded["project_id"],
            target_type="node",
            target_id=target_id,
            content="<comparch>pending body</comparch>",
            status="pending",
            batch_id=f"batch_{uuid.uuid4().hex[:8]}",
            review_text="<review><intro>Critique to apply.</intro></review>",
        )
        db.add(draft)
        db.commit()
        original_review_text = draft.review_text

        r = client.post(f"/api/projects/{seeded['project_id']}/tiers/comparch/review-sweep")
        assert r.status_code == 200
        body = r.json()
        assert body["scopes_total"] == 2
        assert body["jobs_enqueued"] == 1
        assert len(body["scopes_skipped"]) == 1

        # One generation job for the pending-draft scope, with the
        # prior review riding forward in the payload.
        gen_jobs = [
            j
            for j in db.execute(
                select(Job).where(
                    Job.job_type == "v2.generate_comparch",
                    Job.status == "queued",
                )
            ).scalars()
            if j.payload.get("project_id") == seeded["project_id"]
        ]
        assert len(gen_jobs) == 1
        assert gen_jobs[0].payload.get("component_id") == target_id
        assert gen_jobs[0].payload.get("prior_review_text") == original_review_text

        # Prior review_text stays on the discarded draft so the user
        # has the previous critique available for a clean rerun if
        # the regen fails.
        db.refresh(draft)
        assert (draft.review_text or "") == original_review_text

        # No review job enqueued by the sweep — the next review
        # fires from the post-commit hook on the new draft.
        review_jobs = [
            j
            for j in db.execute(
                select(Job).where(
                    Job.job_type == "v2.review_comparch",
                    Job.status == "queued",
                )
            ).scalars()
            if j.payload.get("project_id") == seeded["project_id"]
        ]
        assert len(review_jobs) == 0


# ── /tiers/{tier}/resume ───────────────────────────────────────────


class TestResumeTier:
    def test_seeded_approved_fires_missing_reviews(self, client, db, seeded):
        """The seed leaves both comps approved with no review_text and
        no review jobs in the queue, so resume should fire the two
        missing reviews."""
        r = client.post(f"/api/projects/{seeded['project_id']}/tiers/comparch/resume")
        assert r.status_code == 200
        body = r.json()
        assert body["scopes_total"] == 2
        assert body["generations_enqueued"] == 0
        assert body["reviews_enqueued"] == 2
        assert body["jobs_enqueued"] == 2
        assert body["scopes_skipped"] == []

        review_jobs = [
            j
            for j in db.execute(
                select(Job).where(
                    Job.job_type == "v2.review_comparch",
                    Job.status == "queued",
                )
            ).scalars()
            if j.payload.get("project_id") == seeded["project_id"]
        ]
        assert len(review_jobs) == 2
        assert {j.payload.get("node_id") for j in review_jobs} == set(seeded["comp_ids"])
        # Reviews enqueue at the priority lane.
        from backend.pipeline import queue as pipeline_queue

        assert all(j.priority == pipeline_queue.REVIEW_JOB_PRIORITY for j in review_jobs)

    def test_skips_review_when_completed_already(self, client, db, seeded):
        """Approved + a completed review with non-empty review_text on
        file → leave it alone. Resume only re-fires if the actual
        review_text is empty (the wipe-and-deferred case)."""
        # Stamp a completed review for both comps + populate the
        # node's review_text so resume sees the result actually
        # landed.
        for comp_id in seeded["comp_ids"]:
            comp = db.get(Node, comp_id)
            assert comp is not None
            comp.review_text = "<review>landed</review>"
            db.add(
                Job(
                    job_type="v2.review_comparch",
                    status="completed",
                    payload={
                        "project_id": seeded["project_id"],
                        "node_id": comp_id,
                        "draft_id": None,
                    },
                )
            )
        db.commit()

        r = client.post(f"/api/projects/{seeded['project_id']}/tiers/comparch/resume")
        assert r.status_code == 200
        body = r.json()
        assert body["jobs_enqueued"] == 0
        assert len(body["scopes_skipped"]) == 2
        assert all("latest review completed" in s["detail"] for s in body["scopes_skipped"])

    def test_resumes_cancelled_review(self, client, db, seeded):
        """The killed-mid-deploy case: latest review was cancelled,
        so resume re-fires it. Other comp has no review job → also
        resumed."""
        cancelled = Job(
            job_type="v2.review_comparch",
            status="cancelled",
            payload={
                "project_id": seeded["project_id"],
                "node_id": seeded["comp_ids"][0],
                "draft_id": None,
            },
        )
        db.add(cancelled)
        db.commit()

        r = client.post(f"/api/projects/{seeded['project_id']}/tiers/comparch/resume")
        assert r.status_code == 200
        body = r.json()
        assert body["reviews_enqueued"] == 2
        assert body["scopes_skipped"] == []

    def test_resumes_after_startup_reaper_cancels_a_review(self, client, db, seeded):
        """End-to-end of the kill-server-then-resume flow: a row
        left in ``running`` from a previous process is reaped to
        ``cancelled`` at startup, then resume picks it up."""
        from backend.pipeline import queue as pipeline_queue

        # Stamp a "running" row for the first comp's review — the
        # state we'd see if the previous server died with this job
        # in flight.
        db.add(
            Job(
                job_type="v2.review_comparch",
                status="running",
                payload={
                    "project_id": seeded["project_id"],
                    "node_id": seeded["comp_ids"][0],
                    "draft_id": None,
                },
            )
        )
        db.commit()

        # Reaper flips it to cancelled (this is what the lifespan
        # hook does before the new worker boots).
        n = pipeline_queue.reap_orphaned_running_jobs(db)
        assert n == 1

        r = client.post(f"/api/projects/{seeded['project_id']}/tiers/comparch/resume")
        assert r.status_code == 200
        body = r.json()
        # Both comps now have either no review (second comp) or a
        # cancelled review (first comp, post-reap), so resume fires
        # both.
        assert body["reviews_enqueued"] == 2
        assert body["scopes_skipped"] == []

    def test_skips_scope_with_active_review(self, client, db, seeded):
        """A queued review job for the scope means the queue already
        has it covered."""
        db.add(
            Job(
                job_type="v2.review_comparch",
                status="queued",
                payload={
                    "project_id": seeded["project_id"],
                    "node_id": seeded["comp_ids"][0],
                    "draft_id": None,
                },
            )
        )
        db.commit()

        r = client.post(f"/api/projects/{seeded['project_id']}/tiers/comparch/resume")
        assert r.status_code == 200
        body = r.json()
        # First comp skipped (active review), second comp gets a new review.
        assert body["reviews_enqueued"] == 1
        assert len(body["scopes_skipped"]) == 1
        assert "active review job" in body["scopes_skipped"][0]["detail"]

    def test_resumes_completed_review_with_wiped_review_text(self, client, db, seeded):
        """Wipe-and-deferred case: a regen sweep cleared the prior
        draft's review_text, the follow-up gen job got deferred so
        no new draft committed and no fresh review fired, and the
        latest review job in the table is still the pre-wipe
        ``completed`` row. Resume Tier should re-enqueue a review
        anyway, because the actual ``Draft.review_text`` is empty."""
        from backend.models.node import Draft

        target_id = seeded["comp_ids"][0]
        # Simulate a pending draft with empty review_text — the
        # state left after the regen sweep wiped the review row but
        # the follow-up gen got deferred and never replaced the
        # draft.
        draft_id = f"draft_{uuid.uuid4().hex[:8]}"
        db.add(
            Draft(
                id=draft_id,
                project_id=seeded["project_id"],
                target_type="node",
                target_id=target_id,
                content="<comparch>old draft</comparch>",
                status="pending",
                batch_id=f"batch_{uuid.uuid4().hex[:8]}",
                review_text="",
            )
        )
        # Pre-wipe completed review job — the row Resume Tier used
        # to skip on.
        db.add(
            Job(
                job_type="v2.review_comparch",
                status="completed",
                payload={
                    "project_id": seeded["project_id"],
                    "node_id": target_id,
                    "draft_id": draft_id,
                },
            )
        )
        # Stamp a completed review on the second comp too, but with
        # non-empty review_text — that scope should be skipped (the
        # control case).
        other_id = seeded["comp_ids"][1]
        other_comp = db.get(Node, other_id)
        assert other_comp is not None
        other_comp.review_text = "<review>landed</review>"
        db.add(
            Job(
                job_type="v2.review_comparch",
                status="completed",
                payload={
                    "project_id": seeded["project_id"],
                    "node_id": other_id,
                    "draft_id": None,
                },
            )
        )
        db.commit()

        r = client.post(f"/api/projects/{seeded['project_id']}/tiers/comparch/resume")
        assert r.status_code == 200
        body = r.json()
        # First comp re-enqueued (completed review but empty text);
        # second comp skipped (completed review with text on file).
        assert body["reviews_enqueued"] == 1
        assert len(body["scopes_skipped"]) == 1
        assert "latest review completed" in body["scopes_skipped"][0]["detail"]
        # Confirm the new review job carries the existing draft_id
        # (it's reviewing the empty-text draft, not generating a new one).
        new_review_jobs = [
            j
            for j in db.execute(
                select(Job).where(Job.job_type == "v2.review_comparch", Job.status == "queued")
            ).scalars()
            if j.payload.get("project_id") == seeded["project_id"]
        ]
        assert len(new_review_jobs) == 1
        assert new_review_jobs[0].payload.get("draft_id") == draft_id
        assert new_review_jobs[0].payload.get("node_id") == target_id

    def test_enqueues_for_unapproved_scopes(self, client, db, seeded):
        """Wiping content + having no active job should resume both
        as generations (not reviews — there's nothing to review)."""
        for comp_id in seeded["comp_ids"]:
            comp = db.get(Node, comp_id)
            assert comp is not None
            comp.content = ""
        db.commit()

        r = client.post(f"/api/projects/{seeded['project_id']}/tiers/comparch/resume")
        assert r.status_code == 200
        body = r.json()
        assert body["generations_enqueued"] == 2
        assert body["reviews_enqueued"] == 0
        assert body["jobs_enqueued"] == 2
        assert body["scopes_skipped"] == []

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
        assert {j.payload.get("component_id") for j in queued} == set(seeded["comp_ids"])

    def test_skips_scope_with_active_gen_job(self, client, db, seeded):
        """An already-queued generate for one comp must short-circuit."""
        for comp_id in seeded["comp_ids"]:
            comp = db.get(Node, comp_id)
            assert comp is not None
            comp.content = ""
        # Pre-seed a queued generate for the first comp.
        existing = Job(
            job_type="v2.generate_comparch",
            status="queued",
            payload={
                "project_id": seeded["project_id"],
                "component_id": seeded["comp_ids"][0],
                "feedback": None,
            },
        )
        db.add(existing)
        db.commit()

        r = client.post(f"/api/projects/{seeded['project_id']}/tiers/comparch/resume")
        assert r.status_code == 200
        body = r.json()
        assert body["generations_enqueued"] == 1
        assert body["reviews_enqueued"] == 0
        assert len(body["scopes_skipped"]) == 1
        assert body["scopes_skipped"][0]["status"] == 409
        assert "active gen job" in body["scopes_skipped"][0]["detail"]
        queued_for = [
            j.payload.get("component_id")
            for j in db.execute(
                select(Job).where(
                    Job.job_type == "v2.generate_comparch",
                    Job.status == "queued",
                )
            ).scalars()
            if j.payload.get("project_id") == seeded["project_id"]
        ]
        assert seeded["comp_ids"][0] in queued_for  # the pre-seeded one
        assert seeded["comp_ids"][1] in queued_for  # the new one
        assert len(queued_for) == 2

    def test_pending_draft_triggers_review_pass(self, client, db, seeded):
        """A scope with a pending draft is reviewable — resume should
        fire a review against the pending draft (not start a fresh
        generation, which would discard the draft)."""
        from backend.models.node import Draft

        target_id = seeded["comp_ids"][0]
        target = db.get(Node, target_id)
        assert target is not None
        target.content = ""
        draft_id = f"draft_{uuid.uuid4().hex[:8]}"
        db.add(
            Draft(
                id=draft_id,
                project_id=seeded["project_id"],
                target_type="node",
                target_id=target_id,
                content="<comparch>wip</comparch>",
                status="pending",
                batch_id=f"batch_{uuid.uuid4().hex[:8]}",
            )
        )
        # Wipe the second comp's content too so it gets a generation.
        other = db.get(Node, seeded["comp_ids"][1])
        assert other is not None
        other.content = ""
        db.commit()

        r = client.post(f"/api/projects/{seeded['project_id']}/tiers/comparch/resume")
        assert r.status_code == 200
        body = r.json()
        # The first comp (pending draft) → review against the draft.
        # The second comp (no content, no draft) → generation.
        assert body["reviews_enqueued"] == 1
        assert body["generations_enqueued"] == 1
        assert body["scopes_skipped"] == []
        review_jobs = [
            j
            for j in db.execute(
                select(Job).where(Job.job_type == "v2.review_comparch", Job.status == "queued")
            ).scalars()
            if j.payload.get("project_id") == seeded["project_id"]
        ]
        assert len(review_jobs) == 1
        assert review_jobs[0].payload.get("draft_id") == draft_id


class TestScopeIteratorTopoOrder:
    """The tier-ops scope iterators emit (parent, sub) / (owner) tuples
    in topological order so enqueue order matches dispatch order. These
    tests exercise the helpers directly with a fixture that has a real
    dep + subcomp + impl shape — the broader route tests use a flatter
    fixture without sibling deps.
    """

    def _seed_topo_fixture(self, db: Session) -> dict:
        """Project: foundation comp + app comp (app→foundation dep).
        Each top-level has two subs with a sibling dep among them.
        Foundation comp + one sub of each top-level have an impl child.
        """
        project_id = str(uuid.uuid4())
        db.add(Project(id=project_id, name="T", git_repo_path="/tmp/t"))
        db.flush()

        def _new_comp(name: str, parent_id: str | None, order: int) -> str:
            cid = mint(db, Kind.COMP)
            append_event(
                db,
                project_id,
                ev.NodeCreated(
                    node_id=cid,
                    tier="comp",
                    kind="domain",
                    parent_id=parent_id,
                    name=name,
                    display_order=order,
                    content="",
                ),
            )
            return cid

        def _new_dep(src: str, tgt: str) -> None:
            eid = mint(db, Kind.EDGE)
            append_event(
                db,
                project_id,
                ev.EdgeCreated(edge_id=eid, edge_type="dependency", source_id=src, target_id=tgt),
            )

        # Top-level: app depends on foundation. Foundation should
        # sort first even though display_order puts app first.
        comp_app = _new_comp("App", None, 0)
        comp_foundation = _new_comp("Foundation", None, 1)
        _new_dep(comp_app, comp_foundation)

        # App's subs: a_left depends on a_right. a_right should
        # sort first within app.
        sub_a_left = _new_comp("a_left", comp_app, 0)
        sub_a_right = _new_comp("a_right", comp_app, 1)
        _new_dep(sub_a_left, sub_a_right)

        # Foundation's subs: f_first sorts by display_order alone
        # (no sibling deps).
        sub_f_first = _new_comp("f_first", comp_foundation, 0)
        sub_f_second = _new_comp("f_second", comp_foundation, 1)

        # Impls: foundation directly, plus one sub under each top-level.
        for owner in (comp_foundation, sub_a_right, sub_f_first):
            iid = mint(db, Kind.IMPL)
            append_event(
                db,
                project_id,
                ev.NodeCreated(
                    node_id=iid,
                    tier="impl",
                    kind="domain",
                    parent_id=owner,
                    name=f"impl_{owner}",
                    display_order=0,
                    content="",
                ),
            )

        db.commit()
        return {
            "project_id": project_id,
            "comp_app": comp_app,
            "comp_foundation": comp_foundation,
            "sub_a_left": sub_a_left,
            "sub_a_right": sub_a_right,
            "sub_f_first": sub_f_first,
            "sub_f_second": sub_f_second,
        }

    def test_top_level_comp_scope_emits_topo_order(self, db):
        from backend.graph.tier_ops_routes import _top_level_comp_scope

        s = self._seed_topo_fixture(db)
        scopes = _top_level_comp_scope(db, s["project_id"])
        # Foundation first (app depends on it), app second.
        assert scopes == [(s["comp_foundation"],), (s["comp_app"],)]

    def test_subcomp_scope_emits_parent_topo_then_sub_topo(self, db):
        from backend.graph.tier_ops_routes import _subcomp_scope

        s = self._seed_topo_fixture(db)
        scopes = _subcomp_scope(db, s["project_id"])
        # Foundation's subs (display_order ascending — no deps) before
        # app's subs (a_right before a_left because a_left depends on
        # a_right). Scope tuples are 1-element ``(sub_id,)`` so the
        # per-node helpers' ``get_node`` signature matches the
        # ``_get_sub_node(db, project_id, sub_id)`` shape.
        assert scopes == [
            (s["sub_f_first"],),
            (s["sub_f_second"],),
            (s["sub_a_right"],),
            (s["sub_a_left"],),
        ]

    def test_impl_scope_walks_owners_in_combined_topo_order(self, db):
        from backend.graph.tier_ops_routes import _impl_scope

        s = self._seed_topo_fixture(db)
        scopes = _impl_scope(db, s["project_id"])
        # Foundation impl runs before its subcomps; foundation subtree
        # runs before app subtree because app depends on foundation.
        # sub_f_first has impl, sub_f_second does not, sub_a_right has
        # impl, sub_a_left does not.
        assert scopes == [
            (s["comp_foundation"],),
            (s["sub_f_first"],),
            (s["sub_a_right"],),
        ]
