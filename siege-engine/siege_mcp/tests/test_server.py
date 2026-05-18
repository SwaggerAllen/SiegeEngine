"""Server-level smoke tests using FastAPI's TestClient.

Exercises both transports (HTTP + MCP) end-to-end against a token,
without needing a real git project. Covers the auth gate, the
validate_artifact path (which doesn't need a GitView), and the MCP
JSON-RPC error envelope.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta

# Configure auth BEFORE importing the server so settings pick up the secret.
os.environ.setdefault("SIEGE_JWT_SECRET_KEY", "test-secret")

from fastapi.testclient import TestClient  # noqa: E402
from jose import jwt  # noqa: E402

from siege_mcp.server import app  # noqa: E402


def _token(secret: str = "test-secret") -> str:
    payload = {
        "sub": "u1",
        "username": "u",
        "exp": datetime.utcnow() + timedelta(hours=1),
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def _client() -> TestClient:
    return TestClient(app)


def _auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {_token()}"}


def test_healthz_open():
    r = _client().get("/api/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


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
