"""End-to-end debug route test.

This test imports backend.graph.routes, which transitively imports
``backend.auth.routes`` (via the ``get_current_user`` dependency). In
environments where ``cryptography`` / ``cffi`` isn't loadable — see
the note in ``tests/test_auth_service.py`` — the import fails with a
PyO3 panic. We gate the whole module on that being importable so the
test is skipped rather than crashing collection.
"""

from __future__ import annotations

import pytest

# Skip the whole module if the cryptography stack can't load — the
# jose → cryptography → cffi chain panics (not raises) on this box,
# so we have to catch BaseException here.
try:
    import cryptography.hazmat.bindings._rust  # noqa: F401
except BaseException as _exc:  # pragma: no cover - env-dependent skip
    pytest.skip(
        f"cryptography/cffi environmental issue: {_exc!r}",
        allow_module_level=True,
    )

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from backend.auth.routes import get_current_user  # noqa: E402
from backend.database import Base, get_db  # noqa: E402
from backend.graph import events as ev  # noqa: E402
from backend.graph.reducer import append_event  # noqa: E402
from backend.main import app  # noqa: E402
from backend.models import Project  # noqa: E402


@pytest.fixture()
def db():
    """Thread-safe in-memory SQLite session for TestClient.

    The default ``db`` fixture in ``tests/conftest.py`` uses a bare
    in-memory engine, which pins the connection to the thread that
    created it. FastAPI's TestClient runs sync endpoints in a
    threadpool, so the endpoint sees a different thread than the
    fixture and sqlite3 raises ``ProgrammingError``. StaticPool +
    ``check_same_thread=False`` keeps a single shared connection
    usable from any thread.
    """
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = Session(engine)
    yield session
    session.close()


@pytest.fixture()
def project(db):
    import uuid

    p = Project(
        id=str(uuid.uuid4()),
        name="Test Project",
        git_repo_path="/tmp/test-repo",
    )
    db.add(p)
    db.flush()
    return p


@pytest.fixture()
def client(db, project):
    # Override get_db to yield our in-memory test session; override
    # get_current_user to short-circuit the HTTPBearer dep. We just
    # need a truthy object — the debug route never inspects the user.
    def _get_db():
        yield db

    def _get_user():
        return object()

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[get_current_user] = _get_user
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


class TestDebugRoute:
    def test_empty_project_returns_empty_snapshot(self, client, project):
        resp = client.get(f"/api/projects/{project.id}/model")
        assert resp.status_code == 200
        body = resp.json()
        assert body == {
            "nodes": [],
            "edges": [],
            "fragments": [],
            "drafts": [],
            "event_count": 0,
            "latest_offset": None,
        }

    def test_missing_project_returns_404(self, client):
        resp = client.get("/api/projects/nonexistent/model")
        assert resp.status_code == 404

    def test_populated_project_snapshot(self, client, db, project, canonical_events):
        for e in canonical_events:
            append_event(db, project.id, e)
        db.commit()

        resp = client.get(f"/api/projects/{project.id}/model")
        assert resp.status_code == 200
        body = resp.json()
        assert body["event_count"] == len(canonical_events)
        assert body["latest_offset"] == len(canonical_events)
        # Should contain the nodes that survived the canonical sequence.
        node_ids = {n["id"] for n in body["nodes"]}
        assert "comp_CMPA1111" in node_ids  # AuthService survived the merge
        assert "comp_CMPC1111" not in node_ids  # merged away
        # Fragment eventually committed by DraftApproved.
        frag_ids = {f["id"] for f in body["fragments"]}
        assert "comp_CMPA1111_pubapi" in frag_ids

    def test_simple_event_reflected_in_snapshot(self, client, db, project):
        append_event(
            db,
            project.id,
            ev.NodeCreated(
                node_id="comp_SIMPLE11", tier="comp", kind="domain", name="Simple"
            ),
        )
        db.commit()

        resp = client.get(f"/api/projects/{project.id}/model")
        assert resp.status_code == 200
        body = resp.json()
        assert body["event_count"] == 1
        assert len(body["nodes"]) == 1
        assert body["nodes"][0]["id"] == "comp_SIMPLE11"
        assert body["nodes"][0]["name"] == "Simple"
