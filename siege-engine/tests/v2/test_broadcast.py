"""Tests for the per-project SSE broadcaster.

Covers the in-process pub/sub primitive that powers the
workspace event stream: publish/subscribe lifecycle, ring-buffer
replay, dropped-slow-subscriber behavior, and the
``commit_and_publish`` helper that bridges the reducer's
session-info offset stash to broadcast messages.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database import Base
from backend.graph import events as ev
from backend.graph.broadcast import (
    BroadcastMessage,
    ProjectBroadcaster,
    _node_ids_for_event,
    commit_and_publish,
    reset_broadcaster_for_tests,
)
from backend.graph.reducer import append_event
from backend.models import Project


@pytest.fixture(autouse=True)
def _reset_broadcaster():
    reset_broadcaster_for_tests()
    yield


@pytest.fixture()
def db(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    import backend.database as _database_mod

    monkeypatch.setattr(_database_mod, "SessionLocal", factory)
    session: Session = factory()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def project(db):
    p = Project(id=str(uuid.uuid4()), name="T", git_repo_path="/tmp/t")
    db.add(p)
    db.commit()
    return p


async def _drain(agen, n: int, timeout: float = 1.0) -> list[BroadcastMessage]:
    """Read ``n`` messages off an async generator with a timeout per message."""
    out: list[BroadcastMessage] = []
    for _ in range(n):
        out.append(await asyncio.wait_for(anext(agen), timeout=timeout))
    return out


class TestNodeIdsForEvent:
    def test_node_created_returns_node_id(self):
        assert _node_ids_for_event("NodeCreated", {"node_id": "comp_X"}) == ("comp_X",)

    def test_edge_created_returns_source_and_target(self):
        out = _node_ids_for_event("EdgeCreated", {"source_id": "comp_A", "target_id": "comp_B"})
        assert set(out) == {"comp_A", "comp_B"}

    def test_nodes_merged_returns_dest_and_sources(self):
        out = _node_ids_for_event(
            "NodesMerged",
            {"dest_id": "comp_D", "source_ids": ["comp_A", "comp_B"]},
        )
        assert set(out) == {"comp_D", "comp_A", "comp_B"}

    def test_fragment_updated_returns_owner_id(self):
        assert _node_ids_for_event("FragmentUpdated", {"owner_id": "comp_X"}) == ("comp_X",)

    def test_draft_generated_returns_target_id(self):
        assert _node_ids_for_event(
            "DraftGenerated",
            {"target_id": "comp_X", "target_type": "node"},
        ) == ("comp_X",)

    def test_draft_approved_returns_empty(self):
        # DraftApproved carries only a draft_id; client resolves
        # the target via cached structure.
        assert _node_ids_for_event("DraftApproved", {"draft_id": "d1"}) == ()

    def test_unknown_event_returns_empty(self):
        assert _node_ids_for_event("MadeUp", {"foo": "bar"}) == ()


class TestPublishSubscribe:
    async def test_subscriber_receives_published_message(self):
        b = ProjectBroadcaster()
        gen = b.subscribe("p1")

        # Start the subscriber coroutine so it can register its
        # queue before we publish.
        task = asyncio.create_task(anext(gen))
        await asyncio.sleep(0)  # let subscribe enter its try block

        msg = BroadcastMessage(offset=1, event_type="NodeCreated", node_ids=("n1",))
        b.publish("p1", msg)

        received = await asyncio.wait_for(task, timeout=1.0)
        assert received == msg
        await gen.aclose()

    async def test_multiple_subscribers_each_receive(self):
        b = ProjectBroadcaster()
        gen_a = b.subscribe("p1")
        gen_b = b.subscribe("p1")

        task_a = asyncio.create_task(anext(gen_a))
        task_b = asyncio.create_task(anext(gen_b))
        await asyncio.sleep(0)

        msg = BroadcastMessage(offset=1, event_type="FragmentUpdated", node_ids=("n1",))
        b.publish("p1", msg)

        got_a = await asyncio.wait_for(task_a, timeout=1.0)
        got_b = await asyncio.wait_for(task_b, timeout=1.0)
        assert got_a == msg
        assert got_b == msg

        await gen_a.aclose()
        await gen_b.aclose()

    async def test_publish_to_no_subscribers_is_a_noop(self):
        b = ProjectBroadcaster()
        b.publish("p1", BroadcastMessage(offset=1, event_type="NodeCreated", node_ids=()))
        # Buffer still holds the message for future replay.
        assert b._ring_buffer_size("p1") == 1

    async def test_project_isolation(self):
        b = ProjectBroadcaster()
        gen = b.subscribe("p1")
        task = asyncio.create_task(anext(gen))
        await asyncio.sleep(0)

        # Publish to a different project — our subscriber on p1
        # must NOT receive it.
        b.publish("p2", BroadcastMessage(offset=1, event_type="NodeCreated", node_ids=()))

        # Give the event loop a tick so any spurious cross-project
        # delivery would have happened by now.
        await asyncio.sleep(0.05)
        assert not task.done()

        # Publishing to p1 delivers.
        msg = BroadcastMessage(offset=2, event_type="NodeRenamed", node_ids=("n1",))
        b.publish("p1", msg)
        assert await asyncio.wait_for(task, timeout=1.0) == msg
        await gen.aclose()


class TestReplay:
    async def test_replays_buffered_messages_greater_than_since(self):
        b = ProjectBroadcaster()
        # Pre-publish 5 messages before anyone subscribes.
        for i in range(1, 6):
            b.publish(
                "p1",
                BroadcastMessage(offset=i, event_type="NodeCreated", node_ids=(f"n{i}",)),
            )

        # Subscribe with since=2 — should replay offsets 3, 4, 5.
        gen = b.subscribe("p1", since_offset=2)
        replayed = await _drain(gen, 3)
        assert [m.offset for m in replayed] == [3, 4, 5]
        await gen.aclose()

    async def test_no_replay_when_since_is_none(self):
        b = ProjectBroadcaster()
        for i in range(1, 4):
            b.publish(
                "p1",
                BroadcastMessage(offset=i, event_type="NodeCreated", node_ids=()),
            )
        gen = b.subscribe("p1")  # no since_offset
        # Subscriber should block because nothing is live and
        # no replay was requested.
        task = asyncio.create_task(anext(gen))
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(task, timeout=0.1)
        await gen.aclose()
        task.cancel()

    async def test_ring_buffer_eviction(self):
        # Small buffer so we can test the eviction boundary.
        b = ProjectBroadcaster(ring_buffer_maxlen=3)
        for i in range(1, 6):
            b.publish(
                "p1",
                BroadcastMessage(offset=i, event_type="NodeCreated", node_ids=()),
            )
        # Buffer holds the last 3: offsets 3, 4, 5.
        assert b._ring_buffer_size("p1") == 3
        gen = b.subscribe("p1", since_offset=0)
        replayed = await _drain(gen, 3)
        assert [m.offset for m in replayed] == [3, 4, 5]
        await gen.aclose()


class TestCommitAndPublish:
    def test_publishes_messages_for_stashed_offsets(self, db, project):
        # Append an event (stashes the offset on session.info),
        # then commit_and_publish — broadcaster should see a
        # message for that offset.
        append_event(
            db,
            project.id,
            ev.NodeCreated(
                node_id="comp_AAAAAAAA",
                tier="comp",
                kind="domain",
                parent_id=None,
                name="A",
            ),
        )

        captured: list[BroadcastMessage] = []
        import backend.graph.broadcast as broadcast_mod

        original_publish = broadcast_mod.get_broadcaster().publish

        def _record(pid, msg):
            captured.append(msg)
            original_publish(pid, msg)

        broadcast_mod.get_broadcaster().publish = _record  # type: ignore[method-assign]
        try:
            commit_and_publish(db, project.id)
        finally:
            broadcast_mod.get_broadcaster().publish = original_publish  # type: ignore[method-assign]

        assert len(captured) == 1
        assert captured[0].event_type == "NodeCreated"
        assert captured[0].node_ids == ("comp_AAAAAAAA",)

    def test_no_stashed_offsets_is_a_noop(self, db, project):
        # No append_event call — just commit_and_publish.
        # Nothing should be published.
        captured: list[BroadcastMessage] = []
        import backend.graph.broadcast as broadcast_mod

        broadcast_mod.get_broadcaster().publish = lambda _pid, msg: captured.append(msg)  # type: ignore[method-assign]
        try:
            commit_and_publish(db, project.id)
        finally:
            # Restore default
            reset_broadcaster_for_tests()
        assert captured == []

    def test_drains_stash_so_second_commit_does_not_republish(self, db, project):
        append_event(
            db,
            project.id,
            ev.NodeCreated(
                node_id="comp_BBBBBBBB",
                tier="comp",
                kind="domain",
                parent_id=None,
                name="B",
            ),
        )
        captured: list[BroadcastMessage] = []
        import backend.graph.broadcast as broadcast_mod

        broadcast_mod.get_broadcaster().publish = lambda _pid, msg: captured.append(msg)  # type: ignore[method-assign]
        try:
            commit_and_publish(db, project.id)
            commit_and_publish(db, project.id)  # second call, nothing new
        finally:
            reset_broadcaster_for_tests()
        assert len(captured) == 1
