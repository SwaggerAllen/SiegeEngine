"""Server-level smoke tests using FastAPI's TestClient.

Exercises both transports (HTTP + MCP) end-to-end against a token,
without needing a real git project. Covers the auth gate, the
validate_artifact path (which doesn't need a GitView), and the MCP
JSON-RPC error envelope.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from fastapi.testclient import TestClient
from jose import jwt

from siege_mcp.config import settings
from siege_mcp.server import app


def _token() -> str:
    """Sign with whatever secret the loaded settings already hold.

    The settings singleton is materialized at import time, so a tests-only
    os.environ tweak can't change it once other tests have caused
    ``siege_mcp.config`` to load. Reading ``settings.jwt_secret_key`` here
    keeps the test robust to import order across the full pytest run.
    """
    payload = {
        "sub": "u1",
        "username": "u",
        "exp": datetime.utcnow() + timedelta(hours=1),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def _client() -> TestClient:
    return TestClient(app)


def _auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {_token()}"}


def test_healthz_open():
    r = _client().get("/api/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_bootstrap_script_open():
    r = _client().get("/bootstrap.sh")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/x-shellscript")
    assert r.text.startswith("#!/usr/bin/env bash")
    # Sanity-check: must reference the MCP URL placeholder + the marker.
    assert "MCP_URL" in r.text
    assert "siege-bootstrap: BEGIN" in r.text


def test_missing_auth_401():
    r = _client().post(
        "/api/validate-artifact",
        json={"project_id": "x", "ref": "main", "tier": "comparch", "body": "x"},
    )
    assert r.status_code == 401


def test_malformed_auth_header_401():
    r = _client().post(
        "/api/validate-artifact",
        json={"project_id": "x", "ref": "main", "tier": "comparch", "body": "x"},
        headers={"Authorization": "not-bearer xyz"},
    )
    assert r.status_code == 401


def test_validate_artifact_http():
    r = _client().post(
        "/api/validate-artifact",
        json={
            "project_id": "x",
            "ref": "main",
            "tier": "comparch",
            "body": "## comparch:techspec\nfoo\n\n## comparch:pubapi\nbar\n",
        },
        headers=_auth_headers(),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["extracted_metadata"]["section_count"] == 2


def test_validate_artifact_fails_on_empty():
    r = _client().post(
        "/api/validate-artifact",
        json={"project_id": "x", "ref": "main", "tier": "comparch", "body": ""},
        headers=_auth_headers(),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert "empty" in body["errors"][0]


def test_mcp_initialize():
    """`initialize` must return server info + capabilities for the
    client's handshake to succeed."""
    r = _client().post(
        "/mcp",
        json={"jsonrpc": "2.0", "method": "initialize", "params": {}, "id": 1},
        headers=_auth_headers(),
    )
    assert r.status_code == 200
    payload = r.json()
    assert payload["jsonrpc"] == "2.0"
    assert "result" in payload
    assert payload["result"]["serverInfo"]["name"] == "siegeengine"
    assert "protocolVersion" in payload["result"]
    assert "capabilities" in payload["result"]


def test_mcp_tools_list():
    """`tools/list` must return the canonical tool catalog with
    JSON Schemas. Real MCP clients call this first to learn what
    they can do."""
    r = _client().post(
        "/mcp",
        json={"jsonrpc": "2.0", "method": "tools/list", "params": {}, "id": 2},
        headers=_auth_headers(),
    )
    assert r.status_code == 200
    payload = r.json()
    assert "result" in payload
    tools_list = payload["result"]["tools"]
    names = {t["name"] for t in tools_list}
    # Every tool that dispatches must appear in the catalog or the
    # client can't discover it.
    assert names == {
        "list_refs",
        "get_state",
        "list_tier",
        "get_generation_context",
        "get_review_context",
        "get_review_summary",
        "get_structure_summary",
        "list_batches",
        "validate_artifact",
    }
    # Every entry must have a schema.
    for t in tools_list:
        assert "inputSchema" in t
        assert t["inputSchema"]["type"] == "object"


def test_mcp_tools_call_validate_artifact():
    """`tools/call` is the dispatcher real MCP clients use."""
    r = _client().post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "validate_artifact",
                "arguments": {
                    "project_id": "x",
                    "ref": "main",
                    "tier": "comparch",
                    "body": "## comparch:techspec\nfoo\n\n## comparch:pubapi\nbar\n",
                },
            },
        },
        headers=_auth_headers(),
    )
    assert r.status_code == 200
    payload = r.json()
    result = payload["result"]
    # The tool returns a content block + structuredContent.
    assert result["isError"] is False
    assert result["structuredContent"]["ok"] is True
    # The text content carries the JSON serialization for clients
    # that ignore structuredContent.
    text = result["content"][0]["text"]
    assert '"ok": true' in text


def test_mcp_tools_call_unknown_tool_returns_error_block():
    """An unknown tool name must come back as an isError result, not
    as a JSON-RPC error envelope. (`tools/call` itself succeeds —
    the call dispatched, the tool was just wrong.)"""
    r = _client().post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {"name": "no_such_tool", "arguments": {}},
        },
        headers=_auth_headers(),
    )
    assert r.status_code == 200
    payload = r.json()
    assert "result" in payload
    assert payload["result"]["isError"] is True
    assert "no_such_tool" in payload["result"]["content"][0]["text"]


def test_mcp_unknown_jsonrpc_method():
    r = _client().post(
        "/mcp",
        json={"jsonrpc": "2.0", "method": "definitely/not/a/method", "params": {}, "id": 5},
        headers=_auth_headers(),
    )
    assert r.status_code == 200
    payload = r.json()
    assert "error" in payload
    assert payload["error"]["code"] == -32601


def test_mcp_notifications_ack_empty():
    """`notifications/*` are fire-and-forget per spec; we still send
    a 200 with empty result to keep HTTP semantics clean."""
    r = _client().post(
        "/mcp",
        json={"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
        headers=_auth_headers(),
    )
    assert r.status_code == 200


def test_mcp_trailing_slash_works_directly():
    """Some MCP clients canonicalize URLs with a trailing slash. If
    `/mcp/` redirected to `/mcp`, a TLS-terminated reverse-proxy
    deployment without X-Forwarded-Proto would scheme-downgrade the
    Location header to http://, which strips Authorization on retry.
    Both `/mcp` and `/mcp/` are routed to the same handler so neither
    needs a redirect."""
    r = _client().post(
        "/mcp/",
        json={"jsonrpc": "2.0", "method": "initialize", "params": {}, "id": 1},
        headers=_auth_headers(),
        follow_redirects=False,
    )
    assert r.status_code == 200
    payload = r.json()
    assert payload["result"]["serverInfo"]["name"] == "siegeengine"


def test_user_id_context_propagates_through_middleware_to_route(monkeypatch):
    """Regression test for the threadpool-context-fork bug: a
    ContextVar set inside a FastAPI sync dependency runs in a
    threadpool worker that diverges from the route handler's
    threadpool worker, so the route doesn't see the value. The fix
    is to bind in middleware (which runs on the request task itself).

    Stub `lookup_project_auth` to short-circuit the DB lookup, then
    hit the debug endpoint and check the response reflects the JWT's
    sub claim. If this test fails with `user_id_from_context: null`
    while `user_id_in_claims` is set, the middleware regressed and
    every tool call's auth lookup is broken in production."""
    from siege_mcp import auth_lookup

    captured: dict[str, str | None] = {}

    def fake_lookup(project_id: str, user_id: str | None):
        # Capture what auth_lookup actually sees from the context.
        captured["user_id"] = user_id
        return auth_lookup.ProjectAuth(remote_url=None, access_token=None)

    monkeypatch.setattr("siege_mcp.server.lookup_project_auth", fake_lookup, raising=False)
    # Also patch the import path tools.py uses if it ever calls in.
    monkeypatch.setattr(auth_lookup, "lookup_project_auth", fake_lookup)

    r = _client().get(
        "/api/debug/mcp-auth?project_id=test_proj",
        headers=_auth_headers(),
    )
    assert r.status_code == 200
    body = r.json()
    # The middleware must propagate the JWT sub into the request task
    # context such that the route handler sees it.
    assert body["user_id_from_context"] == "u1", (
        f"ContextVar inside the route did NOT pick up the JWT sub. "
        f"Got user_id_from_context={body['user_id_from_context']!r} "
        f"while claims['sub']={body['user_id_in_claims']!r}. "
        f"Auth middleware regressed."
    )
    assert body["user_id_in_claims"] == "u1"
    assert body["context_matches_claims"] is True
