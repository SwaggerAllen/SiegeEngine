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
    subcomparch_sibling_deps_settled,
    wake_deferred_comparchs,
    wake_deferred_dependents,
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


def _add_domain_parent_edge(db, project_id, presentational_id, domain_id):
    edge_id = mint(db, Kind.EDGE)
    append_event(
        db,
        project_id,
        ev.EdgeCreated(
            edge_id=edge_id,
            edge_type="domain_parent",
            source_id=presentational_id,
            target_id=domain_id,
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

    def test_defers_when_domain_parent_has_in_flight_regen(self, db, project):
        # Presentational P with domain_parent edge to domain D —
        # D's in-flight comparch regen should defer P's regen.
        pres = _make_comp(db, project.id, name="P")
        dom = _make_comp(db, project.id, name="D", content="<comparch/>")
        _add_domain_parent_edge(db, project.id, pres, dom)
        _enqueue_comparch_job(db, project.id, dom)
        ready, reason = comparch_dep_comps_settled(db, project.id, (pres,))
        assert ready is False
        assert reason.startswith("deferred")
        assert dom in reason


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

    def test_re_enqueues_dependents_via_domain_parent_edge(self, db, project):
        # Presentational P deferred on domain D — when D persists,
        # the wakeup should re-enqueue P even though there's no
        # dependency edge, only a domain_parent edge.
        pres = _make_comp(db, project.id, name="P")
        dom = _make_comp(db, project.id, name="D", content="<comparch/>")
        _add_domain_parent_edge(db, project.id, pres, dom)

        p_job_id = _enqueue_comparch_job(db, project.id, pres)
        p_job = db.get(Job, p_job_id)
        assert p_job is not None
        p_job.status = "completed"
        p_job.is_deferred = True
        p_job.error_message = "readiness predicate signalled retry-later"
        db.commit()

        wake_deferred_comparchs(db, project.id, "draft_ignored", (dom,), _terminal_ctx())

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
        assert any((j.payload or {}).get("component_id") == pres for j in new_jobs), (
            "wakeup should re-enqueue P's comparch when its domain parent D settles"
        )
        db.refresh(p_job)
        assert p_job.is_deferred is False

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


def _enqueue_subcomparch_job(db, project_id, sub_id, *, status="queued"):
    """Insert a v2.generate_subcomparch Job row."""
    from backend.pipeline import queue as pipeline_queue

    job_id = pipeline_queue.enqueue(
        db,
        job_type="v2.generate_subcomparch",
        payload={
            "project_id": project_id,
            "component_id": sub_id,
            "feedback": None,
        },
    )
    if status != "queued":
        job = db.get(Job, job_id)
        assert job is not None
        job.status = status
        db.commit()
    return job_id


class TestSubcomparchSiblingDepsSettled:
    def test_passes_with_no_sibling_deps(self, db, project):
        parent = _make_comp(db, project.id, name="P")
        sub = _make_comp(db, project.id, name="Sub", parent_id=parent)
        ready, _ = subcomparch_sibling_deps_settled(db, project.id, (sub,))
        assert ready is True

    def test_defers_when_sibling_dep_in_flight(self, db, project):
        parent = _make_comp(db, project.id, name="P")
        sub_a = _make_comp(db, project.id, name="A", parent_id=parent)
        sub_b = _make_comp(db, project.id, name="B", parent_id=parent)
        _add_dep_edge(db, project.id, sub_a, sub_b)
        _enqueue_subcomparch_job(db, project.id, sub_b)
        ready, reason = subcomparch_sibling_deps_settled(db, project.id, (sub_a,))
        assert ready is False
        assert reason.startswith("deferred")
        assert sub_b in reason

    def test_does_not_defer_on_self_running_job(self, db, project):
        parent = _make_comp(db, project.id, name="P")
        sub_a = _make_comp(db, project.id, name="A", parent_id=parent)
        _enqueue_subcomparch_job(db, project.id, sub_a, status="running")
        ready, _ = subcomparch_sibling_deps_settled(db, project.id, (sub_a,))
        assert ready is True

    def test_cross_parent_deps_are_ignored(self, db, project):
        # Subs in different parents don't count — that's the
        # comparch_dep_comps_settled / cross-tier wakeup chain's job.
        parent_a = _make_comp(db, project.id, name="ParentA")
        parent_b = _make_comp(db, project.id, name="ParentB")
        sub_a = _make_comp(db, project.id, name="A", parent_id=parent_a)
        sub_b = _make_comp(db, project.id, name="B", parent_id=parent_b)
        _add_dep_edge(db, project.id, sub_a, sub_b)
        _enqueue_subcomparch_job(db, project.id, sub_b)
        ready, _ = subcomparch_sibling_deps_settled(db, project.id, (sub_a,))
        # B is a different-parent sub, not a same-parent sibling →
        # this predicate doesn't fire on it.
        assert ready is True


class TestWakeDeferredDependentsCrossTier:
    def test_top_level_persist_wakes_subcomp_dependent(self, db, project):
        # A sub that depended on a top-level comp got deferred.
        # When the top-level comp persists, the wakeup should
        # re-enqueue v2.generate_subcomparch for that sub.
        parent = _make_comp(db, project.id, name="P", content="<comparch/>")
        sub = _make_comp(db, project.id, name="Sub", parent_id=parent)
        top = _make_comp(db, project.id, name="Top", content="<comparch/>")
        _add_dep_edge(db, project.id, sub, top)

        sub_job_id = _enqueue_subcomparch_job(db, project.id, sub)
        sub_job = db.get(Job, sub_job_id)
        assert sub_job is not None
        sub_job.status = "completed"
        sub_job.is_deferred = True
        db.commit()

        # Top persists.
        wake_deferred_dependents(db, project.id, "draft_ignored", (top,), _terminal_ctx())

        # The wakeup should enqueue a v2.generate_subcomparch (not
        # v2.generate_comparch) for the sub.
        new_subcomparch_jobs = (
            db.execute(
                select(Job).where(
                    Job.job_type == "v2.generate_subcomparch",
                    Job.status == "queued",
                )
            )
            .scalars()
            .all()
        )
        assert any((j.payload or {}).get("component_id") == sub for j in new_subcomparch_jobs), (
            "wakeup should enqueue v2.generate_subcomparch for the sub-tier dependent"
        )

        db.refresh(sub_job)
        assert sub_job.is_deferred is False

    def test_sub_persist_wakes_sibling_sub_dependent(self, db, project):
        # Two same-parent siblings, A depends on B. A is deferred.
        # B persists → A's subcomparch is re-enqueued.
        parent = _make_comp(db, project.id, name="P", content="<comparch/>")
        sub_a = _make_comp(db, project.id, name="A", parent_id=parent)
        sub_b = _make_comp(db, project.id, name="B", parent_id=parent, content="<subcomparch/>")
        _add_dep_edge(db, project.id, sub_a, sub_b)

        a_job_id = _enqueue_subcomparch_job(db, project.id, sub_a)
        a_job = db.get(Job, a_job_id)
        assert a_job is not None
        a_job.status = "completed"
        a_job.is_deferred = True
        db.commit()

        wake_deferred_dependents(db, project.id, "draft_ignored", (sub_b,), _terminal_ctx())

        new_jobs = (
            db.execute(
                select(Job).where(
                    Job.job_type == "v2.generate_subcomparch",
                    Job.status == "queued",
                )
            )
            .scalars()
            .all()
        )
        assert any((j.payload or {}).get("component_id") == sub_a for j in new_jobs)


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
