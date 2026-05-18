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


def test_mcp_rpc_dispatch():
    r = _client().post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "method": "validate_artifact",
            "params": {
                "project_id": "x",
                "ref": "main",
                "tier": "comparch",
                "body": "## comparch:techspec\nfoo\n\n## comparch:pubapi\nbar\n",
            },
            "id": 42,
        },
        headers=_auth_headers(),
    )
    assert r.status_code == 200
    payload = r.json()
    assert payload["id"] == 42
    assert payload["jsonrpc"] == "2.0"
    assert payload["result"]["ok"] is True


def test_mcp_unknown_method():
    r = _client().post(
        "/mcp",
        json={"jsonrpc": "2.0", "method": "no_such_tool", "params": {}, "id": 1},
        headers=_auth_headers(),
    )
    assert r.status_code == 200
    payload = r.json()
    assert "error" in payload
    assert payload["error"]["code"] == -32601


def test_mcp_invalid_params():
    r = _client().post(
        "/mcp",
        json={"jsonrpc": "2.0", "method": "validate_artifact", "params": {}, "id": 1},
        headers=_auth_headers(),
    )
    assert r.status_code == 200
    payload = r.json()
    # Missing required project_id triggers TypeError → -32602
    assert "error" in payload
    assert payload["error"]["code"] == -32602
