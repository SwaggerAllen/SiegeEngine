"""End-to-end tests for /projects/{id}/settings.

Same TestClient + in-memory-DB pattern as test_expansion_routes.py.
Covers the GET default, PUT round-trip, PUT validation, and the
edge case of the JSON column being ``None`` vs ``{}``.
"""

from __future__ import annotations

import os
import uuid

import pytest

os.environ.setdefault("SIEGE_DISABLE_WORKER_LOOP", "1")

# Skip the whole module if the cryptography stack can't load — same
# environmental guard as the other route tests.
try:
    import cryptography.hazmat.bindings._rust  # noqa: F401
except BaseException as _exc:  # pragma: no cover - env-dependent skip
    pytest.skip(
        f"cryptography/cffi environmental issue: {_exc!r}",
        allow_module_level=True,
    )

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from backend.auth.routes import _require_writer, get_current_user  # noqa: E402
from backend.database import Base, get_db  # noqa: E402
from backend.main import app  # noqa: E402
from backend.models import Project  # noqa: E402


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
    p = Project(
        id=str(uuid.uuid4()),
        name="Test",
        git_repo_path="/tmp/t",
    )
    db.add(p)
    db.commit()
    return p


@pytest.fixture()
def client(db, project):
    def _get_db():
        yield db

    def _get_user():
        return object()

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[get_current_user] = _get_user
    app.dependency_overrides[_require_writer] = _get_user
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


class TestGetSettings:
    def test_returns_defaults_when_column_is_null(self, client, project):
        resp = client.get(f"/api/projects/{project.id}/settings")
        assert resp.status_code == 200
        body = resp.json()
        assert body["generation_timeout_seconds"] == 7200
        assert body["cli_max_budget_usd"] == 2.00

    def test_returns_overridden_value_when_column_is_set(self, client, project, db):
        project.settings = {"generation_timeout_seconds": 1500, "cli_max_budget_usd": 5.00}
        db.commit()
        resp = client.get(f"/api/projects/{project.id}/settings")
        assert resp.status_code == 200
        body = resp.json()
        assert body["generation_timeout_seconds"] == 1500
        assert body["cli_max_budget_usd"] == 5.00

    def test_returns_defaults_when_column_is_empty_dict(self, client, project, db):
        project.settings = {}
        db.commit()
        resp = client.get(f"/api/projects/{project.id}/settings")
        assert resp.status_code == 200
        body = resp.json()
        assert body["generation_timeout_seconds"] == 7200
        assert body["cli_max_budget_usd"] == 2.00

    def test_unknown_project_is_404(self, client):
        resp = client.get("/api/projects/does-not-exist/settings")
        assert resp.status_code == 404


class TestPutSettings:
    def test_updates_timeout(self, client, project, db):
        resp = client.put(
            f"/api/projects/{project.id}/settings",
            json={"generation_timeout_seconds": 1200},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["generation_timeout_seconds"] == 1200
        db.refresh(project)
        # The full validated dump lands in the column, not just the
        # override diff — see the PUT route docstring.
        assert project.settings["generation_timeout_seconds"] == 1200

    def test_empty_body_resets_to_defaults(self, client, project, db):
        project.settings = {"generation_timeout_seconds": 2000, "cli_max_budget_usd": 5.0}
        db.commit()
        resp = client.put(f"/api/projects/{project.id}/settings", json={})
        assert resp.status_code == 200
        body = resp.json()
        assert body["generation_timeout_seconds"] == 7200
        assert body["cli_max_budget_usd"] == 2.00
        db.refresh(project)
        assert project.settings["generation_timeout_seconds"] == 7200
        assert project.settings["cli_max_budget_usd"] == 2.00

    def test_updates_budget(self, client, project, db):
        resp = client.put(
            f"/api/projects/{project.id}/settings",
            json={"generation_timeout_seconds": 1800, "cli_max_budget_usd": 4.50},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["cli_max_budget_usd"] == 4.50
        db.refresh(project)
        assert project.settings["cli_max_budget_usd"] == 4.50

    def test_below_minimum_is_rejected(self, client, project):
        resp = client.put(
            f"/api/projects/{project.id}/settings",
            json={"generation_timeout_seconds": 30},
        )
        assert resp.status_code == 422

    def test_above_maximum_is_rejected(self, client, project):
        resp = client.put(
            f"/api/projects/{project.id}/settings",
            json={"generation_timeout_seconds": 99999},
        )
        assert resp.status_code == 422

    def test_budget_below_minimum_is_rejected(self, client, project):
        resp = client.put(
            f"/api/projects/{project.id}/settings",
            json={"cli_max_budget_usd": 0.00},
        )
        assert resp.status_code == 422

    def test_budget_above_maximum_is_rejected(self, client, project):
        resp = client.put(
            f"/api/projects/{project.id}/settings",
            json={"cli_max_budget_usd": 1000.00},
        )
        assert resp.status_code == 422

    def test_unknown_project_is_404(self, client):
        resp = client.put(
            "/api/projects/does-not-exist/settings",
            json={"generation_timeout_seconds": 600},
        )
        assert resp.status_code == 404

    def test_extra_keys_are_dropped(self, client, project, db):
        resp = client.put(
            f"/api/projects/{project.id}/settings",
            json={
                "generation_timeout_seconds": 600,
                "unknown_setting": "should be ignored",
            },
        )
        assert resp.status_code == 200
        assert "unknown_setting" not in resp.json()
        db.refresh(project)
        assert "unknown_setting" not in (project.settings or {})
