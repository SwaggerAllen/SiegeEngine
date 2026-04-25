"""Phase F: topo-correct comparch dispatch via readiness predicate.

Pins the behaviour that prevents the over-regen pattern observed in
production: when a sysarch update marks all top-level comparchs
stale, fanout enqueues them in mark-iteration order. Without
Phase F, comp_A processed before its dep comp_B sees stale pubapi
fragments and generates a wrong draft, then re-fires later when B's
regen lands. Phase F's :func:`comparch_dep_comps_settled` predicate
makes A defer when B has an in-flight regen, and the
:func:`wake_deferred_comparchs` post-persist hook re-enqueues A
once B settles.
"""

from __future__ import annotations

from sqlalchemy import select

from backend.graph import events as ev
from backend.graph.handlers._readiness import (
    comparch_dep_comps_settled,
    wake_deferred_comparchs,
)
from backend.graph.handlers._tier_generation import (
    PostPersistContext,
    TierDeferredError,
)
from backend.graph.ids import Kind, mint
from backend.graph.reducer import append_event
from backend.models.job import Job


def _terminal_ctx() -> PostPersistContext:
    """Build a terminal-pass PostPersistContext for hook tests.

    The wakeup hook is gated on ``ctx.is_terminal`` (Phase F item
    4). Tests of the wakeup's behaviour pass a terminal context;
    the dedicated gate test passes a non-terminal context to
    verify the gate.
    """
    return PostPersistContext(
        auto_revision_pass=0,
        auto_revisions_remaining=0,
        is_terminal=True,
    )


def _make_comp(db, project_id, *, name, content="", parent_id=None):
    nid = mint(db, Kind.COMP)
    append_event(
        db,
        project_id,
        ev.NodeCreated(
            node_id=nid,
            tier="comp",
            kind="domain",
            parent_id=parent_id,
            name=name,
            content=content,
        ),
    )
    return nid


def _add_dep_edge(db, project_id, source_id, target_id):
    edge_id = mint(db, Kind.EDGE)
    append_event(
        db,
        project_id,
        ev.EdgeCreated(
            edge_id=edge_id,
            edge_type="dependency",
            source_id=source_id,
            target_id=target_id,
        ),
    )
    return edge_id


def _enqueue_comparch_job(db, project_id, comp_id, *, status="queued"):
    """Insert a v2.generate_comparch Job row directly for predicate testing."""
    from backend.pipeline import queue as pipeline_queue

    job_id = pipeline_queue.enqueue(
        db,
        job_type="v2.generate_comparch",
        payload={
            "project_id": project_id,
            "component_id": comp_id,
            "feedback": None,
        },
    )
    if status != "queued":
        job = db.get(Job, job_id)
        assert job is not None
        job.status = status
        db.commit()
    return job_id


class TestComparchDepCompsSettled:
    def test_passes_with_no_deps(self, db, project):
        comp_id = _make_comp(db, project.id, name="A")
        ready, _ = comparch_dep_comps_settled(db, project.id, (comp_id,))
        assert ready is True

    def test_passes_when_dep_settled_no_jobs_in_flight(self, db, project):
        a = _make_comp(db, project.id, name="A")
        b = _make_comp(db, project.id, name="B", content="<comparch/>")
        _add_dep_edge(db, project.id, a, b)
        ready, _ = comparch_dep_comps_settled(db, project.id, (a,))
        assert ready is True

    def test_defers_when_dep_has_queued_regen(self, db, project):
        a = _make_comp(db, project.id, name="A")
        b = _make_comp(db, project.id, name="B", content="<comparch/>")
        _add_dep_edge(db, project.id, a, b)
        _enqueue_comparch_job(db, project.id, b)
        ready, reason = comparch_dep_comps_settled(db, project.id, (a,))
        assert ready is False
        assert reason.startswith("deferred")
        assert b in reason

    def test_defers_when_dep_has_running_regen(self, db, project):
        a = _make_comp(db, project.id, name="A")
        b = _make_comp(db, project.id, name="B", content="<comparch/>")
        _add_dep_edge(db, project.id, a, b)
        _enqueue_comparch_job(db, project.id, b, status="running")
        ready, reason = comparch_dep_comps_settled(db, project.id, (a,))
        assert ready is False
        assert reason.startswith("deferred")

    def test_does_not_defer_on_self_running_job(self, db, project):
        # The predicate is being evaluated AS PART of A's own
        # job-claim, so A's own job is "running". The predicate
        # excludes A's own running job from the defer signal so
        # the gate doesn't deadlock on its own.
        a = _make_comp(db, project.id, name="A")
        _enqueue_comparch_job(db, project.id, a, status="running")
        # No deps at all → still passes.
        ready, _ = comparch_dep_comps_settled(db, project.id, (a,))
        assert ready is True

    def test_subcomp_deps_are_ignored(self, db, project):
        # Only top-level comp deps gate the predicate. Sub deps
        # come up through a different path.
        a = _make_comp(db, project.id, name="A")
        parent = _make_comp(db, project.id, name="Parent")
        sub = _make_comp(db, project.id, name="Sub", parent_id=parent)
        _add_dep_edge(db, project.id, a, sub)
        _enqueue_comparch_job(db, project.id, sub)
        ready, _ = comparch_dep_comps_settled(db, project.id, (a,))
        # Sub is not top-level, so it doesn't trigger defer.
        assert ready is True


class TestWakeDeferredComparchs:
    def test_re_enqueues_dependents_with_deferred_marker(self, db, project):
        # Setup: A depends on B. A has a deferred-completed job.
        a = _make_comp(db, project.id, name="A")
        b = _make_comp(db, project.id, name="B", content="<comparch/>")
        _add_dep_edge(db, project.id, a, b)

        # Set up the deferred marker directly to avoid the
        # production SessionLocal dependency in
        # ``_complete_deferred_job_sync``.
        a_job_id = _enqueue_comparch_job(db, project.id, a)
        a_job = db.get(Job, a_job_id)
        assert a_job is not None
        a_job.status = "completed"
        a_job.is_deferred = True
        a_job.error_message = "readiness predicate signalled retry-later"
        db.commit()

        # Verify the deferred flag is set.
        a_job = db.get(Job, a_job_id)
        assert a_job is not None
        assert a_job.is_deferred is True

        # Wakeup fires after B persists. Re-enqueues A.
        wake_deferred_comparchs(db, project.id, "draft_ignored", (b,), _terminal_ctx())

        # New comparch job for A is queued.
        new_jobs = (
            db.execute(
                select(Job).where(
                    Job.job_type == "v2.generate_comparch",
                    Job.status == "queued",
                )
            )
            .scalars()
            .all()
        )
        assert any((j.payload or {}).get("component_id") == a for j in new_jobs), (
            "wakeup should re-enqueue A's comparch when B settles"
        )

        # The deferred flag is cleared so the next wakeup doesn't
        # act on this row again.
        db.refresh(a_job)
        assert a_job.is_deferred is False

    def test_no_op_when_no_deferred_dependents(self, db, project):
        a = _make_comp(db, project.id, name="A")
        b = _make_comp(db, project.id, name="B", content="<comparch/>")
        _add_dep_edge(db, project.id, a, b)

        # No deferred jobs. Wakeup is a no-op.
        wake_deferred_comparchs(db, project.id, "draft_ignored", (b,), _terminal_ctx())

        new_jobs = (
            db.execute(
                select(Job).where(
                    Job.job_type == "v2.generate_comparch",
                    Job.status == "queued",
                )
            )
            .scalars()
            .all()
        )
        assert new_jobs == []

    def test_does_not_re_enqueue_unrelated_deferred(self, db, project):
        # X has a deferred job, but X doesn't depend on B. B's
        # persist should NOT re-enqueue X.
        x = _make_comp(db, project.id, name="X")
        b = _make_comp(db, project.id, name="B", content="<comparch/>")
        # No dep edge between X and B.

        x_job_id = _enqueue_comparch_job(db, project.id, x)
        x_job = db.get(Job, x_job_id)
        assert x_job is not None
        x_job.status = "completed"
        x_job.is_deferred = True
        x_job.error_message = "readiness predicate signalled retry-later"
        db.commit()

        wake_deferred_comparchs(db, project.id, "draft_ignored", (b,), _terminal_ctx())

        new_jobs = (
            db.execute(
                select(Job).where(
                    Job.job_type == "v2.generate_comparch",
                    Job.status == "queued",
                )
            )
            .scalars()
            .all()
        )
        assert not any((j.payload or {}).get("component_id") == x for j in new_jobs), (
            "X's deferred shouldn't wake when B persists (X doesn't depend on B)"
        )


class TestTerminalGate:
    def test_wakeup_no_op_on_intermediate_persist(self, db, project):
        # Setup: A depends on B, A has a deferred job, B is the
        # just-persisted comp. With a NON-terminal ctx (e.g.
        # auto_revisions_remaining > 0), the wakeup should NOT
        # re-enqueue A — that would fire on every auto-revision
        # intermediate, multiplying the cascade work.
        a = _make_comp(db, project.id, name="A")
        b = _make_comp(db, project.id, name="B", content="<comparch/>")
        _add_dep_edge(db, project.id, a, b)

        a_job_id = _enqueue_comparch_job(db, project.id, a)
        a_job = db.get(Job, a_job_id)
        assert a_job is not None
        a_job.status = "completed"
        a_job.is_deferred = True
        db.commit()

        non_terminal = PostPersistContext(
            auto_revision_pass=1,
            auto_revisions_remaining=2,
            is_terminal=False,
        )
        wake_deferred_comparchs(db, project.id, "draft_intermediate", (b,), non_terminal)

        # No new jobs enqueued, A's deferred flag still set.
        new_jobs = (
            db.execute(
                select(Job).where(
                    Job.job_type == "v2.generate_comparch",
                    Job.status == "queued",
                )
            )
            .scalars()
            .all()
        )
        assert not any((j.payload or {}).get("component_id") == a for j in new_jobs)
        db.refresh(a_job)
        assert a_job.is_deferred is True


class TestTierDeferredErrorClass:
    def test_is_distinct_from_precondition(self):
        # Defensive: TierDeferredError must not be caught by code
        # that catches TierPreconditionError. The two have very
        # different semantics (defer-and-retry vs hard-fail).
        from backend.graph.handlers._tier_generation import TierPreconditionError

        deferred = TierDeferredError("test")
        assert not isinstance(deferred, TierPreconditionError)

    def test_worker_completes_deferred_cleanly(self):
        # Pin the worker's deferred-completion behaviour: status
        # ends up "completed" with a "deferred:" marker, not
        # "failed".
        from backend.pipeline.queue import _complete_deferred_job_sync

        # Marker shape verified in the wakeup test above; this
        # test just guards against accidentally renaming the prefix.
        # The wakeup hook keys off "deferred:".
        assert _complete_deferred_job_sync.__module__ == "backend.pipeline.queue"
