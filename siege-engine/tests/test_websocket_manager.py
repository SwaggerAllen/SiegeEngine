"""Tests for backend.websocket.manager – WebSocket connection management."""

from unittest.mock import AsyncMock

import pytest

from backend.websocket.manager import ConnectionManager


@pytest.fixture
def manager():
    return ConnectionManager()


def _make_ws(*, should_fail=False):
    """Create a mock WebSocket."""
    ws = AsyncMock()
    ws.accept = AsyncMock()
    if should_fail:
        ws.send_json = AsyncMock(side_effect=Exception("connection closed"))
    else:
        ws.send_json = AsyncMock()
    return ws


class TestConnect:
    async def test_accepts_and_stores_connection(self, manager):
        ws = _make_ws()
        await manager.connect("proj-1", ws)
        ws.accept.assert_awaited_once()
        assert ws in manager.connections["proj-1"]

    async def test_multiple_connections_same_project(self, manager):
        ws1 = _make_ws()
        ws2 = _make_ws()
        await manager.connect("proj-1", ws1)
        await manager.connect("proj-1", ws2)
        assert len(manager.connections["proj-1"]) == 2


class TestDisconnect:
    async def test_removes_connection(self, manager):
        ws = _make_ws()
        await manager.connect("proj-1", ws)
        manager.disconnect("proj-1", ws)
        assert ws not in manager.connections["proj-1"]

    async def test_disconnect_nonexistent_is_noop(self, manager):
        ws = _make_ws()
        manager.disconnect("proj-1", ws)  # should not raise


class TestBroadcast:
    async def test_sends_to_all_connections(self, manager):
        ws1 = _make_ws()
        ws2 = _make_ws()
        await manager.connect("proj-1", ws1)
        await manager.connect("proj-1", ws2)

        await manager.broadcast("proj-1", {"type": "test"})

        ws1.send_json.assert_awaited_once_with({"type": "test"})
        ws2.send_json.assert_awaited_once_with({"type": "test"})

    async def test_removes_dead_connections(self, manager):
        good_ws = _make_ws()
        dead_ws = _make_ws(should_fail=True)
        await manager.connect("proj-1", good_ws)
        await manager.connect("proj-1", dead_ws)

        await manager.broadcast("proj-1", {"type": "update"})

        assert dead_ws not in manager.connections["proj-1"]
        assert good_ws in manager.connections["proj-1"]

    async def test_broadcast_empty_project_is_noop(self, manager):
        # Should not raise
        await manager.broadcast("no-connections", {"type": "test"})

    async def test_does_not_leak_between_projects(self, manager):
        ws1 = _make_ws()
        ws2 = _make_ws()
        await manager.connect("proj-1", ws1)
        await manager.connect("proj-2", ws2)

        await manager.broadcast("proj-1", {"type": "msg"})

        ws1.send_json.assert_awaited_once()
        ws2.send_json.assert_not_awaited()
