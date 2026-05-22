"""Server-level smoke tests using FastAPI's TestClient.

Exercises the dashboard read API end-to-end against a token, without
needing a real git project: the auth gate, the validate-artifact path
(which doesn't need a GitView), and the middleware that propagates the
user id into the request context.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from fastapi.testclient import TestClient
from jose import jwt

from siege.config import settings
from siege.server import app


def _token() -> str:
    """Sign with whatever secret the loaded settings already hold.

    The settings singleton is materialized at import time, so a tests-only
    os.environ tweak can't change it once other tests have caused
    ``siege.config`` to load. Reading ``settings.jwt_secret_key`` here
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
    every read endpoint's auth lookup is broken in production."""
    from siege import auth_lookup

    captured: dict[str, str | None] = {}

    def fake_lookup(project_id: str, user_id: str | None):
        # Capture what auth_lookup actually sees from the context.
        captured["user_id"] = user_id
        return auth_lookup.ProjectAuth(remote_url=None, access_token=None)

    monkeypatch.setattr("siege.server.lookup_project_auth", fake_lookup, raising=False)
    # Also patch the import path the endpoint uses when it calls in.
    monkeypatch.setattr(auth_lookup, "lookup_project_auth", fake_lookup)

    r = _client().get(
        "/api/debug/auth?project_id=test_proj",
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
