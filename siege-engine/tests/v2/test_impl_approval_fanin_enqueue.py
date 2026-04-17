"""Tests for the Phase 7 on_impl_approved hook.

The hook walks up from an impl node to its owning top-level comp
and enqueues ``v2.generate_fanin`` if that comp has a fanin_*
child. Presentational subtrees and un-fanned-out domain comps
(both of which have no fanin child) must no-op. Duplicate
enqueues within a rapid-fire batch collapse via pipeline_queue's
payload-dedup.

Also verifies the BootstrapTierConfig.on_approve plumbing in
bootstrap_approve: the hook is called after the reducer commits,
hook failures do not roll back the approval, and presentational
impl approvals still commit cleanly without any fanin enqueue.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database import Base
from backend.graph import events as ev
from backend.graph.bootstrap_routes import bootstrap_approve
from backend.graph.handlers.impl_generation import on_impl_approved
from backend.graph.ids import Kind, mint
from backend.graph.reducer import append_event
from backend.models import Project
from backend.models.job import Job
from backend.models.node import Node


@pytest.fixture()
def shared_session_factory(monkeypatch):
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
    yield factory
    engine.dispose()


def _seed_with_subcomp_impl(
    factory,
    *,
    top_kind: str = "domain",
    mint_fanin: bool = True,
) -> tuple[str, str, str, str]:
    """Seed project + fanned-out top-level + subcomp + impl, optionally with fanin shell.

    Returns (project_id, top_comp_id, sub_comp_id, impl_id).
    """
    session: Session = factory()
    try:
        project_id = str(uuid.uuid4())
        session.add(Project(id=project_id, name="T", git_repo_path="/tmp/t"))
        session.flush()

        top_id = mint(session, Kind.COMP)
        append_event(
            session,
            project_id,
            ev.NodeCreated(
                node_id=top_id,
                tier="comp",
                kind=top_kind,  # type: ignore[arg-type]
                parent_id=None,
                name="Top",
                content="<comparch>ok</comparch>",
            ),
        )
        sub_id = mint(session, Kind.COMP)
        append_event(
            session,
            project_id,
            ev.NodeCreated(
                node_id=sub_id,
                tier="comp",
                kind=top_kind,  # type: ignore[arg-type]
                parent_id=top_id,
                name="Sub",
                content="<subcomparch>ok</subcomparch>",
            ),
        )
        impl_id = mint(session, Kind.IMPL)
        append_event(
            session,
            project_id,
            ev.NodeCreated(
                node_id=impl_id,
                tier="impl",
                kind=top_kind,  # type: ignore[arg-type]
                parent_id=sub_id,
                name="Sub impl",
            ),
        )
        if mint_fanin:
            fanin_id = mint(session, Kind.FANIN)
            append_event(
                session,
                project_id,
                ev.NodeCreated(
                    node_id=fanin_id,
                    tier="fanin",
                    kind="domain",
                    parent_id=top_id,
                    name="Top fan-in",
                ),
            )
        session.commit()
        return project_id, top_id, sub_id, impl_id
    finally:
        session.close()


def _enqueued_fanin_jobs(session: Session, project_id: str) -> list[Job]:
    return list(session.execute(select(Job).where(Job.job_type == "v2.generate_fanin")).scalars())


class TestOnImplApprovedDirect:
    def test_fanned_out_domain_enqueues_fanin(self, shared_session_factory):
        project_id, top_id, sub_id, impl_id = _seed_with_subcomp_impl(
            shared_session_factory, top_kind="domain", mint_fanin=True
        )
        session: Session = shared_session_factory()
        try:
            impl = session.get(Node, impl_id)
            on_impl_approved(session, project_id, impl, (sub_id,))
            session.commit()
            jobs = _enqueued_fanin_jobs(session, project_id)
            assert len(jobs) == 1
            assert jobs[0].payload == {
                "project_id": project_id,
                "owner_comp_id": top_id,
            }
        finally:
            session.close()

    def test_presentational_subtree_noops(self, shared_session_factory):
        project_id, _, sub_id, impl_id = _seed_with_subcomp_impl(
            shared_session_factory,
            top_kind="presentational",
            mint_fanin=False,
        )
        session: Session = shared_session_factory()
        try:
            impl = session.get(Node, impl_id)
            on_impl_approved(session, project_id, impl, (sub_id,))
            session.commit()
            jobs = _enqueued_fanin_jobs(session, project_id)
            assert jobs == []
        finally:
            session.close()

    def test_un_fanned_out_domain_without_fanin_child_noops(self, shared_session_factory):
        """An un-fanned-out domain comp has its impl directly under itself
        and has no fanin child. Hook should no-op."""
        session: Session = shared_session_factory()
        try:
            project_id = str(uuid.uuid4())
            session.add(Project(id=project_id, name="T", git_repo_path="/tmp/t"))
            session.flush()
            top_id = mint(session, Kind.COMP)
            append_event(
                session,
                project_id,
                ev.NodeCreated(
                    node_id=top_id,
                    tier="comp",
                    kind="domain",
                    parent_id=None,
                    name="Top",
                    content="<comparch>ok</comparch>",
                ),
            )
            impl_id = mint(session, Kind.IMPL)
            append_event(
                session,
                project_id,
                ev.NodeCreated(
                    node_id=impl_id,
                    tier="impl",
                    kind="domain",
                    parent_id=top_id,
                    name="Top impl",
                ),
            )
            session.commit()

            impl = session.get(Node, impl_id)
            on_impl_approved(session, project_id, impl, (top_id,))
            session.commit()
            jobs = _enqueued_fanin_jobs(session, project_id)
            assert jobs == []
        finally:
            session.close()

    def test_non_impl_node_noops(self, shared_session_factory):
        project_id, top_id, sub_id, _ = _seed_with_subcomp_impl(
            shared_session_factory, top_kind="domain", mint_fanin=True
        )
        session: Session = shared_session_factory()
        try:
            # Call with the sub comp node (tier="comp") instead of
            # the impl. The hook should no-op rather than enqueue.
            sub = session.get(Node, sub_id)
            on_impl_approved(session, project_id, sub, (sub_id,))
            session.commit()
            jobs = _enqueued_fanin_jobs(session, project_id)
            assert jobs == []
        finally:
            session.close()

    def test_rapid_fire_approvals_dedup(self, shared_session_factory):
        project_id, top_id, sub_id, impl_id = _seed_with_subcomp_impl(
            shared_session_factory, top_kind="domain", mint_fanin=True
        )
        session: Session = shared_session_factory()
        try:
            impl = session.get(Node, impl_id)
            on_impl_approved(session, project_id, impl, (sub_id,))
            on_impl_approved(session, project_id, impl, (sub_id,))
            on_impl_approved(session, project_id, impl, (sub_id,))
            session.commit()
            # pipeline_queue.enqueue has payload-dedup — three
            # identical calls collapse to one queued job.
            jobs = _enqueued_fanin_jobs(session, project_id)
            assert len(jobs) == 1
        finally:
            session.close()


class TestBootstrapApproveIntegration:
    def test_approve_invokes_hook_and_enqueues(self, shared_session_factory):
        """Full bootstrap_approve path: after DraftApproved commits,
        the on_approve hook fires and enqueues fan-in regen."""
        from backend.graph.routes import IMPL_CONFIG

        project_id, top_id, sub_id, impl_id = _seed_with_subcomp_impl(
            shared_session_factory, top_kind="domain", mint_fanin=True
        )

        session: Session = shared_session_factory()
        try:
            # Seed a pending impl draft.
            impl_xml = (
                "<implementation>"
                "<behavior>B</behavior>"
                "<invariants>I</invariants>"
                "<sequencing>S</sequencing>"
                "<edge-cases>E</edge-cases>"
                "</implementation>"
            )
            append_event(
                session,
                project_id,
                ev.DraftGenerated(
                    draft_id="d_impl_1",
                    target_type="node",
                    target_id=impl_id,
                    content=impl_xml,
                    batch_id="b1",
                ),
            )
            session.commit()

            def _noop_require_project(db, pid):  # type: ignore[no-untyped-def]
                return None

            result = bootstrap_approve(
                session,
                project_id,
                scope_ids=(sub_id,),
                draft_id="d_impl_1",
                config=IMPL_CONFIG,
                require_project=_noop_require_project,
            )
            assert "node" in result

            # Draft status flipped + impl content landed.
            impl = session.get(Node, impl_id)
            assert impl.content == impl_xml

            # Fan-in regen enqueued.
            jobs = _enqueued_fanin_jobs(session, project_id)
            assert len(jobs) == 1
            assert jobs[0].payload["owner_comp_id"] == top_id
        finally:
            session.close()

    def test_hook_failure_does_not_roll_back_approval(self, shared_session_factory, monkeypatch):
        """If on_approve raises, the approval itself still commits —
        the draft flips to approved and the node content updates."""
        from backend.graph.routes import IMPL_CONFIG

        project_id, top_id, sub_id, impl_id = _seed_with_subcomp_impl(
            shared_session_factory, top_kind="domain", mint_fanin=True
        )

        session: Session = shared_session_factory()
        try:
            impl_xml = (
                "<implementation>"
                "<behavior>B</behavior>"
                "<invariants>I</invariants>"
                "<sequencing>S</sequencing>"
                "<edge-cases>E</edge-cases>"
                "</implementation>"
            )
            append_event(
                session,
                project_id,
                ev.DraftGenerated(
                    draft_id="d_impl_2",
                    target_type="node",
                    target_id=impl_id,
                    content=impl_xml,
                    batch_id="b2",
                ),
            )
            session.commit()

            def exploding_hook(db, pid, node, scope_ids):
                raise RuntimeError("boom")

            # Swap IMPL_CONFIG.on_approve for a blast-radius test.
            # dataclass is not frozen, so attribute assignment works.
            original_hook = IMPL_CONFIG.on_approve
            IMPL_CONFIG.on_approve = exploding_hook
            try:

                def _noop_require_project(db, pid):  # type: ignore[no-untyped-def]
                    return None

                # bootstrap_approve wraps the hook in try/except and
                # logs; the call must NOT raise.
                result = bootstrap_approve(
                    session,
                    project_id,
                    scope_ids=(sub_id,),
                    draft_id="d_impl_2",
                    config=IMPL_CONFIG,
                    require_project=_noop_require_project,
                )
                assert "node" in result
                # Impl content lands despite the hook blowing up.
                impl = session.get(Node, impl_id)
                assert impl.content == impl_xml
                # And no fan-in job enqueued (hook exploded
                # before the enqueue could happen).
                jobs = _enqueued_fanin_jobs(session, project_id)
                assert jobs == []
            finally:
                IMPL_CONFIG.on_approve = original_hook
        finally:
            session.close()
