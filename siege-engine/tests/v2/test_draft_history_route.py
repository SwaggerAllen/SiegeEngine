"""End-to-end tests for the Phase 13 draft audit-history endpoint.

``GET /projects/{project_id}/drafts/by-target/{target_id}/history``
returns every Draft row that ever targeted ``target_id``, newest
first, carrying the change_summary + discard_reason alongside the
lifecycle metadata.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta

import pytest

os.environ.setdefault("SIEGE_DISABLE_WORKER_LOOP", "1")

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

from backend.auth.routes import get_current_user  # noqa: E402
from backend.database import Base, get_db  # noqa: E402
from backend.main import app  # noqa: E402
from backend.models import Project  # noqa: E402
from backend.models.node import Draft  # noqa: E402


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session: Session = factory()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def project(db):
    p = Project(id=str(uuid.uuid4()), name="Test", git_repo_path="/tmp/test")
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
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _seed_draft(
    db: Session,
    *,
    project_id: str,
    target_id: str,
    status: str,
    change_summary: str | None,
    discard_reason: str | None,
    created_at: datetime,
) -> Draft:
    draft = Draft(
        id=f"draft_{uuid.uuid4().hex[:12]}",
        project_id=project_id,
        target_type="node",
        target_id=target_id,
        content="stub",
        status=status,
        batch_id=f"batch_{uuid.uuid4().hex[:12]}",
        change_summary=change_summary,
        discard_reason=discard_reason,
        created_at=created_at,
    )
    db.add(draft)
    db.commit()
    return draft


class TestDraftHistoryRoute:
    def test_returns_newest_first(self, client, db, project):
        now = datetime(2026, 4, 23, 12, 0, 0)
        target_id = "reqs_abc12345"
        oldest = _seed_draft(
            db,
            project_id=project.id,
            target_id=target_id,
            status="discarded",
            change_summary="Initial pass.",
            discard_reason="user_regen",
            created_at=now,
        )
        middle = _seed_draft(
            db,
            project_id=project.id,
            target_id=target_id,
            status="discarded",
            change_summary="Split Auth into five atoms.",
            discard_reason="auto_revision",
            created_at=now + timedelta(minutes=1),
        )
        newest = _seed_draft(
            db,
            project_id=project.id,
            target_id=target_id,
            status="approved",
            change_summary=None,
            discard_reason=None,
            created_at=now + timedelta(minutes=2),
        )

        resp = client.get(f"/api/projects/{project.id}/drafts/by-target/{target_id}/history")
        assert resp.status_code == 200
        entries = resp.json()["entries"]
        ids = [e["draft_id"] for e in entries]
        assert ids == [newest.id, middle.id, oldest.id]
        assert entries[1]["change_summary"] == "Split Auth into five atoms."
        assert entries[1]["discard_reason"] == "auto_revision"
        assert entries[0]["change_summary"] is None

    def test_empty_history_returns_empty_list(self, client, project):
        resp = client.get(f"/api/projects/{project.id}/drafts/by-target/reqs_nothing/history")
        assert resp.status_code == 200
        assert resp.json() == {"entries": []}

    def test_unknown_project_returns_404(self, client):
        resp = client.get("/api/projects/project_does_not_exist/drafts/by-target/reqs_x/history")
        assert resp.status_code == 404

    def test_cross_project_isolation(self, client, db, project):
        other_project = Project(id=str(uuid.uuid4()), name="Other", git_repo_path="/tmp/o")
        db.add(other_project)
        db.commit()
        target_id = "reqs_shared_id"
        _seed_draft(
            db,
            project_id=other_project.id,
            target_id=target_id,
            status="approved",
            change_summary="Other project draft.",
            discard_reason=None,
            created_at=datetime(2026, 4, 23, 10, 0, 0),
        )
        resp = client.get(f"/api/projects/{project.id}/drafts/by-target/{target_id}/history")
        assert resp.status_code == 200
        # Only drafts for ``project`` show up — the other project's draft
        # sharing the same target_id is filtered out by project_id.
        assert resp.json() == {"entries": []}
