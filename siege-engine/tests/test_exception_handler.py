"""Regression test for the global unhandled-exception handler.

The frontend reads ``err.response.data.detail`` for every API error
(see ``frontend/src/lib/describeApiError.ts``). Default FastAPI 500s
don't include ``detail``, so unhandled server errors show up as a
blank "Failed to X" fallback.

The handler in ``backend.main`` wraps any ``Exception`` subclass that
isn't already an ``HTTPException`` in a JSON response of the form
``{"detail": "<ClassName: message>"}`` with status 500.
"""

from __future__ import annotations

import os

# Disable the background worker for every test in this module; the
# handler test stands up a TestClient which would otherwise start it.
os.environ.setdefault("SIEGE_DISABLE_WORKER_LOOP", "1")
os.environ.setdefault("SIEGE_ANTHROPIC_API_KEY", "stub")

import pytest  # noqa: E402

# cryptography/cffi panics on this sandbox, same pattern as
# test_expansion_routes.py. Skip the whole module if it fails.
try:
    import cryptography.hazmat.bindings._rust  # noqa: F401
except BaseException as _exc:  # pragma: no cover
    pytest.skip(
        f"cryptography/cffi environmental issue: {_exc!r}",
        allow_module_level=True,
    )

from types import SimpleNamespace  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from backend.auth.routes import _require_writer, get_current_user  # noqa: E402
from backend.database import Base, get_db  # noqa: E402
from backend.main import app  # noqa: E402
from backend.projects import service as projects_service  # noqa: E402


@pytest.fixture()
def client(monkeypatch):
    # In-memory DB so the HTTPException test (hit /api/projects/<id>)
    # can exercise the real SQLAlchemy query path without a real file.
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    def _get_db():
        session = Session()
        try:
            yield session
        finally:
            session.close()

    user_stub = SimpleNamespace(role="admin", id="u_1", username="tester")
    app.dependency_overrides[get_current_user] = lambda: user_stub
    app.dependency_overrides[_require_writer] = lambda: user_stub
    app.dependency_overrides[get_db] = _get_db
    try:
        # raise_server_exceptions=False so the handler's response is
        # returned to the client instead of re-raising through the
        # TestClient.
        yield TestClient(app, raise_server_exceptions=False)
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_unhandled_exception_returns_json_detail(client, monkeypatch):
    """A raw RuntimeError in a route handler becomes a JSON 500."""

    def broken(db, name, description, project_doc_content):
        raise RuntimeError("simulated git init failure")

    monkeypatch.setattr(projects_service, "create_project", broken)

    resp = client.post(
        "/api/projects/",
        json={"name": "boom", "description": None, "project_doc_content": "x"},
    )
    assert resp.status_code == 500
    assert resp.headers["content-type"].startswith("application/json")
    body = resp.json()
    assert "detail" in body
    assert "RuntimeError" in body["detail"]
    assert "simulated git init failure" in body["detail"]


def test_unhandled_exception_with_empty_message_still_has_class_name(client, monkeypatch):
    """Exceptions whose str() is empty still carry the class name."""

    class CustomError(RuntimeError):
        pass

    def broken(db, name, description, project_doc_content):
        raise CustomError()  # no message

    monkeypatch.setattr(projects_service, "create_project", broken)

    resp = client.post(
        "/api/projects/",
        json={"name": "boom", "description": None, "project_doc_content": "x"},
    )
    assert resp.status_code == 500
    body = resp.json()
    assert body["detail"] == "CustomError"


def test_http_exception_still_goes_through_fastapi_handler(client):
    """Regular HTTPException-based 404s still return their detail.

    This confirms the global handler doesn't swallow FastAPI's own
    HTTPException shape.
    """
    resp = client.get("/api/projects/nonexistent-id-goes-here")
    assert resp.status_code == 404
    assert resp.json() == {"detail": "Project not found"}
