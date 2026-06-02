"""Tests for backend.graph.handlers.expand_single_feature.

The handler is async and opens its own ``SessionLocal()``. Same engine
+ monkeypatch shape as ``test_feature_expansion_handler.py``, plus
``backend.pipeline.queue.SessionLocal`` (the deferred batch-flush
imports it transitively when enqueueing regens).

The CLI is stubbed via the bound-method patch on
``_handler_mod.cli_manager.generate_with_usage`` to keep tests
deterministic.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database import Base
from backend.graph import events as ev
from backend.graph.handlers.expand_single_feature import (
    ExpandSingleFeatureError,
    _handle,
)
from backend.graph.ids import Kind, mint
from backend.graph.reducer import append_event
from backend.models import InputDocument, Project
from backend.models.graph_event import GraphEvent
from backend.models.job import Job
from backend.models.node import Edge, Node, StalenessLedger
from backend.models.pending_instruction import PendingInstruction


def bootstrap_reqs_node(session, project_id: str) -> str:
    """Inlined from the deleted backend.graph.requirements module.

    The test only needs to create a reqs Node row for the project so
    the handler's downstream "ensure a reqs edge exists" logic has
    something to point at.
    """
    node_id = mint(session, Kind.REQS)
    append_event(
        session,
        project_id,
        ev.NodeCreated(node_id=node_id, tier="reqs", kind="domain", name="Reqs"),
    )
    return node_id


_VALID_OUTPUT = (
    "<features>"
    "<feature>"
    "<name>Profile Editing</name>"
    "<intent>Lets a signed-in user edit their display name, avatar, "
    "and bio. The change persists immediately and replicates across "
    "open sessions through the existing pubsub channel.</intent>"
    "</feature>"
    "</features>"
)


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
    import backend.graph.handlers.expand_single_feature as _handler_mod
    import backend.pipeline.queue as _pipeline_queue_mod

    monkeypatch.setattr(_database_mod, "SessionLocal", factory)
    monkeypatch.setattr(_handler_mod, "SessionLocal", factory)
    monkeypatch.setattr(_pipeline_queue_mod, "SessionLocal", factory, raising=False)
    yield factory
    engine.dispose()


def _patch_cli(monkeypatch, return_value: str = _VALID_OUTPUT):
    """Monkeypatch the bound CLI generate_with_usage method."""
    import backend.graph.handlers.expand_single_feature as _handler_mod
    from backend.cli.manager import GenerationResult

    calls: list[dict] = []

    async def fake(**kwargs):
        calls.append(kwargs)
        return GenerationResult(
            text=return_value,
            prompt_tokens=10,
            completion_tokens=5,
            model="claude-sonnet-4-6",
        )

    monkeypatch.setattr(_handler_mod.cli_manager, "generate_with_usage", fake)
    return calls


def _patch_cli_raising(monkeypatch, exc: Exception):
    import backend.graph.handlers.expand_single_feature as _handler_mod

    async def boom(**kwargs):
        raise exc

    monkeypatch.setattr(_handler_mod.cli_manager, "generate_with_usage", boom)


def _patch_cli_with_callback(monkeypatch, callback, return_value: str = _VALID_OUTPUT):
    """CLI stub that runs a callback (e.g. status flip) before returning."""
    import backend.graph.handlers.expand_single_feature as _handler_mod
    from backend.cli.manager import GenerationResult

    async def fake(**kwargs):
        callback()
        return GenerationResult(
            text=return_value,
            prompt_tokens=10,
            completion_tokens=5,
            model="claude-sonnet-4-6",
        )

    monkeypatch.setattr(_handler_mod.cli_manager, "generate_with_usage", fake)


def _seed_propose_setup(
    factory,
    *,
    with_reqs_node: bool = False,
    feat_name: str = "(proposing) Profile editing",
    feat_content: str = "",
    row_status: str = "running",
    extra_running_siblings: int = 0,
):
    """Create project + feat node + PendingInstruction row.

    Returns ``(project_id, feat_node_id, source_row_id, job_id)``.
    The ``job_id`` is None unless extra_running_siblings > 0, in which
    case it's a synthetic Job row that all siblings share for the
    batch-completion test.
    """
    s: Session = factory()
    try:
        project_id = str(uuid.uuid4())
        s.add(Project(id=project_id, name="T", git_repo_path="/tmp/t"))
        s.flush()

        # Project doc — handler reads it for prompt context.
        s.add(
            InputDocument(
                project_id=project_id,
                name="Doc",
                content="A widget tracker.",
                doc_type="project_doc",
            )
        )

        if with_reqs_node:
            bootstrap_reqs_node(s, project_id)

        feat_id = mint(s, Kind.FEAT)
        append_event(
            s,
            project_id,
            ev.NodeCreated(
                node_id=feat_id,
                tier="feat",
                kind="domain",
                parent_id=None,
                name=feat_name,
                content=feat_content,
            ),
        )

        job_id = None
        if extra_running_siblings > 0 or row_status != "running":
            # Synthetic Job row to anchor batch siblings on a shared
            # job_id. apply_pending_queue would normally create this.
            job = Job(
                id=str(uuid.uuid4()),
                job_type="v2.apply_instructions",
                payload={"project_id": project_id},
                status="running",
            )
            s.add(job)
            s.flush()
            job_id = job.id

        row = PendingInstruction(
            project_id=project_id,
            sequence=1,
            instruction_type="ProposeFeature",
            payload={
                "instruction_type": "ProposeFeature",
                "node_id": feat_id,
                "name_hint": feat_name,
                "description": "Profile editing description",
            },
            status=row_status,
            job_id=job_id,
        )
        s.add(row)
        s.flush()
        source_row_id = row.id

        for i in range(extra_running_siblings):
            sib = PendingInstruction(
                project_id=project_id,
                sequence=2 + i,
                instruction_type="ProposeFeature",
                payload={
                    "instruction_type": "ProposeFeature",
                    "node_id": f"feat_SIB0000{i}",
                    "name_hint": "(proposing) sibling",
                    "description": "sibling desc",
                },
                status="running",
                job_id=job_id,
            )
            s.add(sib)
        s.commit()
        return project_id, feat_id, source_row_id, job_id
    finally:
        s.close()


def _payload(project_id: str, feat_id: str, row_id: str, description: str | None = None) -> dict:
    return {
        "project_id": project_id,
        "feat_node_id": feat_id,
        "description": description or "Profile editing description",
        "source_pending_instruction_id": row_id,
    }


def _event_types(factory, project_id: str) -> list[str]:
    s = factory()
    try:
        return [r.event_type for r in s.query(GraphEvent).filter_by(project_id=project_id).all()]
    finally:
        s.close()


def _row_status(factory, row_id: str) -> tuple[str, str | None]:
    s = factory()
    try:
        row = s.get(PendingInstruction, row_id)
        assert row is not None
        return row.status, row.error
    finally:
        s.close()


class TestHappyPath:
    def test_renames_and_updates_content_and_flips_row(self, shared_session_factory, monkeypatch):
        factory = shared_session_factory
        _patch_cli(monkeypatch)
        project_id, feat_id, row_id, _ = _seed_propose_setup(factory)

        asyncio.run(_handle(_payload(project_id, feat_id, row_id)))

        types = _event_types(factory, project_id)
        assert "NodeRenamed" in types
        assert "NodeContentUpdated" in types

        s = factory()
        try:
            node = s.get(Node, feat_id)
            assert node is not None
            assert node.name == "Profile Editing"
            assert "Lets a signed-in user" in (node.content or "")
        finally:
            s.close()

        status, error = _row_status(factory, row_id)
        assert status == "applied"
        assert error is None

    def test_mints_feat_to_reqs_edge_when_reqs_node_exists(
        self, shared_session_factory, monkeypatch
    ):
        factory = shared_session_factory
        _patch_cli(monkeypatch)
        project_id, feat_id, row_id, _ = _seed_propose_setup(factory, with_reqs_node=True)

        asyncio.run(_handle(_payload(project_id, feat_id, row_id)))

        s = factory()
        try:
            reqs_node = s.execute(
                select(Node).where(Node.project_id == project_id, Node.tier == "reqs")
            ).scalar_one()
            edges = (
                s.execute(
                    select(Edge).where(
                        Edge.project_id == project_id,
                        Edge.edge_type == "decomposition",
                        Edge.source_id == feat_id,
                        Edge.target_id == reqs_node.id,
                    )
                )
                .scalars()
                .all()
            )
            assert len(edges) == 1
        finally:
            s.close()

    def test_no_reqs_edge_when_no_reqs_node(self, shared_session_factory, monkeypatch):
        factory = shared_session_factory
        _patch_cli(monkeypatch)
        project_id, feat_id, row_id, _ = _seed_propose_setup(factory)

        asyncio.run(_handle(_payload(project_id, feat_id, row_id)))

        s = factory()
        try:
            edges = (
                s.execute(
                    select(Edge).where(
                        Edge.project_id == project_id,
                        Edge.edge_type == "decomposition",
                    )
                )
                .scalars()
                .all()
            )
            assert edges == []
        finally:
            s.close()

    def test_skips_rename_when_canonical_matches_placeholder(
        self, shared_session_factory, monkeypatch
    ):
        # Seed feat with a name that already matches the canonical
        # name returned by the CLI stub. NodeRenamed should be omitted.
        factory = shared_session_factory
        _patch_cli(monkeypatch)
        project_id, feat_id, row_id, _ = _seed_propose_setup(factory, feat_name="Profile Editing")

        asyncio.run(_handle(_payload(project_id, feat_id, row_id)))

        types = _event_types(factory, project_id)
        assert "NodeRenamed" not in types
        assert "NodeContentUpdated" in types


class TestFailurePath:
    def test_cli_error_rolls_back_feat_and_flips_row_failed(
        self, shared_session_factory, monkeypatch
    ):
        factory = shared_session_factory
        _patch_cli_raising(monkeypatch, RuntimeError("boom"))
        project_id, feat_id, row_id, _ = _seed_propose_setup(factory)

        asyncio.run(_handle(_payload(project_id, feat_id, row_id)))

        s = factory()
        try:
            assert s.get(Node, feat_id) is None
        finally:
            s.close()

        status, error = _row_status(factory, row_id)
        assert status == "failed"
        assert "boom" in (error or "")

    def test_invalid_xml_rolls_back_and_flips_row_failed(self, shared_session_factory, monkeypatch):
        factory = shared_session_factory
        _patch_cli(monkeypatch, return_value="not even xml")
        project_id, feat_id, row_id, _ = _seed_propose_setup(factory)

        asyncio.run(_handle(_payload(project_id, feat_id, row_id)))

        s = factory()
        try:
            assert s.get(Node, feat_id) is None
        finally:
            s.close()

        status, error = _row_status(factory, row_id)
        assert status == "failed"
        assert error  # some error string

    def test_multi_feature_output_is_failure(self, shared_session_factory, monkeypatch):
        # Two <feature> blocks — handler enforces exactly one.
        two_features = (
            "<features>"
            "<feature><name>One</name>"
            "<intent>First feature intent paragraph here.</intent>"
            "</feature>"
            "<feature><name>Two</name>"
            "<intent>Second feature intent paragraph here.</intent>"
            "</feature>"
            "</features>"
        )
        factory = shared_session_factory
        _patch_cli(monkeypatch, return_value=two_features)
        project_id, feat_id, row_id, _ = _seed_propose_setup(factory)

        asyncio.run(_handle(_payload(project_id, feat_id, row_id)))

        s = factory()
        try:
            assert s.get(Node, feat_id) is None
        finally:
            s.close()

        status, error = _row_status(factory, row_id)
        assert status == "failed"
        assert "exactly 1" in (error or "").lower() or "1 <feature>" in (error or "")


class TestIdempotency:
    def test_re_run_when_row_already_applied_exits_early(self, shared_session_factory, monkeypatch):
        factory = shared_session_factory
        _patch_cli(monkeypatch)
        project_id, feat_id, row_id, _ = _seed_propose_setup(factory, row_status="applied")

        # Track event count before; handler should not emit anything new.
        before = len(_event_types(factory, project_id))
        asyncio.run(_handle(_payload(project_id, feat_id, row_id)))
        after = len(_event_types(factory, project_id))
        assert after == before

    def test_existing_content_short_circuits(self, shared_session_factory, monkeypatch):
        factory = shared_session_factory
        # CLI stub still patched; we don't expect it to be invoked,
        # but if the short-circuit branch breaks the test will still
        # pass / fail on the assertions below.
        _patch_cli(monkeypatch)
        project_id, feat_id, row_id, _ = _seed_propose_setup(
            factory, feat_content="already populated content paragraph"
        )

        asyncio.run(_handle(_payload(project_id, feat_id, row_id)))

        # No NodeContentUpdated; handler short-circuited.
        types = _event_types(factory, project_id)
        assert "NodeContentUpdated" not in types

        status, error = _row_status(factory, row_id)
        assert status == "applied"
        assert error is None


class TestDiscardMidFlight:
    def test_discarded_at_start_emits_node_deleted_no_flip(
        self, shared_session_factory, monkeypatch
    ):
        factory = shared_session_factory
        _patch_cli(monkeypatch)
        project_id, feat_id, row_id, _ = _seed_propose_setup(factory, row_status="discarded")

        asyncio.run(_handle(_payload(project_id, feat_id, row_id)))

        s = factory()
        try:
            assert s.get(Node, feat_id) is None
        finally:
            s.close()

        # Status unchanged (already terminal).
        status, _ = _row_status(factory, row_id)
        assert status == "discarded"

    def test_discarded_during_llm_call_still_rolls_back(self, shared_session_factory, monkeypatch):
        factory = shared_session_factory
        project_id, feat_id, row_id, _ = _seed_propose_setup(factory)

        # Stub flips the row to discarded between handler's first
        # status check and post-LLM re-check.
        def flip_discarded():
            s = factory()
            try:
                row = s.get(PendingInstruction, row_id)
                assert row is not None
                row.status = "discarded"
                row.updated_at = datetime.utcnow()
                s.commit()
            finally:
                s.close()

        _patch_cli_with_callback(monkeypatch, flip_discarded)

        asyncio.run(_handle(_payload(project_id, feat_id, row_id)))

        s = factory()
        try:
            assert s.get(Node, feat_id) is None
        finally:
            s.close()

        status, _ = _row_status(factory, row_id)
        assert status == "discarded"


class TestBadPayload:
    def test_missing_project_id_raises(self, shared_session_factory):
        with pytest.raises(ExpandSingleFeatureError, match="project_id"):
            asyncio.run(_handle({}))

    def test_missing_source_row_id_raises(self, shared_session_factory):
        with pytest.raises(ExpandSingleFeatureError, match="source_pending_instruction_id"):
            asyncio.run(
                _handle(
                    {
                        "project_id": "p",
                        "feat_node_id": "feat_X",
                        "description": "d",
                    }
                )
            )


class TestBatchCompletion:
    def test_last_running_row_flushes_pending_regens(self, shared_session_factory, monkeypatch):
        factory = shared_session_factory
        _patch_cli(monkeypatch)
        project_id, feat_id, row_id, _ = _seed_propose_setup(factory)

        # Seed a stale top-level comp so flush_pending_regens has
        # something to enqueue.
        s = factory()
        try:
            append_event(
                s,
                project_id,
                ev.NodeCreated(
                    node_id="comp_STALE001",
                    tier="comp",
                    kind="domain",
                    name="StaleTop",
                    content="<comparch>approved</comparch>",
                ),
            )
            s.add(
                StalenessLedger(
                    project_id=project_id,
                    stale_node_id="comp_STALE001",
                    source_node_id=feat_id,
                    source_offset=1,
                    reason="content_changed",
                )
            )
            s.commit()
        finally:
            s.close()

        asyncio.run(_handle(_payload(project_id, feat_id, row_id)))

        # The row's job_id is None (single-row test seed), so the
        # batch-completion check fires the flush directly.
        s = factory()
        try:
            jobs = (
                s.execute(select(Job).where(Job.job_type == "v2.generate_comparch")).scalars().all()
            )
            assert any((j.payload or {}).get("component_id") == "comp_STALE001" for j in jobs)
        finally:
            s.close()

    def test_other_siblings_still_running_skips_flush(self, shared_session_factory, monkeypatch):
        factory = shared_session_factory
        _patch_cli(monkeypatch)
        project_id, feat_id, row_id, _ = _seed_propose_setup(factory, extra_running_siblings=1)

        # Same staleness seed as above — but this run's row has a
        # sibling in ``running`` so the flush should NOT fire.
        s = factory()
        try:
            append_event(
                s,
                project_id,
                ev.NodeCreated(
                    node_id="comp_STALE002",
                    tier="comp",
                    kind="domain",
                    name="StaleTop2",
                    content="<comparch>approved</comparch>",
                ),
            )
            s.add(
                StalenessLedger(
                    project_id=project_id,
                    stale_node_id="comp_STALE002",
                    source_node_id=feat_id,
                    source_offset=1,
                    reason="content_changed",
                )
            )
            s.commit()
        finally:
            s.close()

        asyncio.run(_handle(_payload(project_id, feat_id, row_id)))

        s = factory()
        try:
            jobs = (
                s.execute(select(Job).where(Job.job_type == "v2.generate_comparch")).scalars().all()
            )
            assert not any((j.payload or {}).get("component_id") == "comp_STALE002" for j in jobs)
        finally:
            s.close()
