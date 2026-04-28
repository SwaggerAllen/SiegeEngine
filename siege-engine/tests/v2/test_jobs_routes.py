"""Tests for the generation-queue routes (list / cancel / reprioritize / delete).

The routes wrap the existing ``backend.pipeline.queue`` primitives;
the tests focus on the project-scoping wrapper + the state-machine
gates that the route layer adds (queued-only reprioritize, no-delete
on running, etc.).
"""

from __future__ import annotations

import os
import uuid

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
from backend.models.job import Job  # noqa: E402


@pytest.fixture()
def engine_and_factory(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    import backend.database as _database_mod

    monkeypatch.setattr(_database_mod, "SessionLocal", factory)
    yield engine, factory
    engine.dispose()


@pytest.fixture()
def db(engine_and_factory):
    _, factory = engine_and_factory
    s: Session = factory()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture()
def project_id(db):
    pid = str(uuid.uuid4())
    db.add(Project(id=pid, name="T", git_repo_path="/tmp/t"))
    db.commit()
    return pid


@pytest.fixture()
def client(db):
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


def _make_job(
    db: Session,
    project_id: str,
    *,
    job_type: str = "v2.generate_sysarch",
    status: str = "queued",
    priority: int = 10,
    extra_payload: dict | None = None,
) -> str:
    payload = {"project_id": project_id, "feedback": None}
    if extra_payload:
        payload.update(extra_payload)
    job = Job(job_type=job_type, status=status, priority=priority, payload=payload)
    db.add(job)
    db.commit()
    return job.id


class TestListJobs:
    def test_returns_only_jobs_for_this_project(self, client, db, project_id):
        # One job for our project, one for another.
        my_id = _make_job(db, project_id)
        other_pid = str(uuid.uuid4())
        db.add(Project(id=other_pid, name="X", git_repo_path="/tmp/x"))
        db.commit()
        _make_job(db, other_pid)

        r = client.get(f"/api/projects/{project_id}/jobs")
        assert r.status_code == 200
        body = r.json()
        ids = [j["id"] for j in body["jobs"]]
        assert my_id in ids
        assert len(body["jobs"]) == 1

    def test_filters_by_status(self, client, db, project_id):
        _make_job(db, project_id, status="queued")
        _make_job(db, project_id, status="completed")
        r = client.get(f"/api/projects/{project_id}/jobs?status=queued")
        body = r.json()
        assert len(body["jobs"]) == 1
        assert body["jobs"][0]["status"] == "queued"

    def test_filters_by_job_type(self, client, db, project_id):
        _make_job(db, project_id, job_type="v2.generate_sysarch")
        _make_job(db, project_id, job_type="v2.review_sysarch")
        r = client.get(f"/api/projects/{project_id}/jobs?job_type=v2.review_sysarch")
        body = r.json()
        assert len(body["jobs"]) == 1
        assert body["jobs"][0]["job_type"] == "v2.review_sysarch"

    def test_returns_status_counts(self, client, db, project_id):
        _make_job(db, project_id, status="queued")
        _make_job(db, project_id, status="queued")
        _make_job(db, project_id, status="running")
        r = client.get(f"/api/projects/{project_id}/jobs")
        body = r.json()
        assert body["status_counts"]["queued"] == 2
        assert body["status_counts"]["running"] == 1

    def test_unknown_project_404s(self, client):
        r = client.get(f"/api/projects/{uuid.uuid4()}/jobs")
        assert r.status_code == 404


class TestCancelJob:
    def test_cancels_queued_job(self, client, db, project_id):
        jid = _make_job(db, project_id)
        r = client.post(f"/api/projects/{project_id}/jobs/{jid}/cancel")
        assert r.status_code == 200
        assert r.json()["cancelled"] is True
        db.expire_all()
        assert db.get(Job, jid).status == "cancelled"

    def test_404s_for_other_project(self, client, db, project_id):
        other_pid = str(uuid.uuid4())
        db.add(Project(id=other_pid, name="X", git_repo_path="/tmp/x"))
        db.commit()
        jid = _make_job(db, other_pid)
        r = client.post(f"/api/projects/{project_id}/jobs/{jid}/cancel")
        assert r.status_code == 404


class TestReprioritize:
    def test_changes_priority_on_queued(self, client, db, project_id):
        jid = _make_job(db, project_id, priority=10)
        r = client.post(
            f"/api/projects/{project_id}/jobs/{jid}/reprioritize",
            json={"priority": 1},
        )
        assert r.status_code == 200
        assert r.json()["priority"] == 1
        db.expire_all()
        assert db.get(Job, jid).priority == 1

    def test_409_on_running(self, client, db, project_id):
        jid = _make_job(db, project_id, status="running")
        r = client.post(
            f"/api/projects/{project_id}/jobs/{jid}/reprioritize",
            json={"priority": 1},
        )
        assert r.status_code == 409

    def test_validates_priority_range(self, client, db, project_id):
        jid = _make_job(db, project_id)
        r = client.post(
            f"/api/projects/{project_id}/jobs/{jid}/reprioritize",
            json={"priority": -5},
        )
        assert r.status_code == 422


class TestReapOrphanedRunningJobs:
    """The startup reaper that lifespan calls before worker_loop starts.

    Any row left in ``running`` at startup is a tombstone from a
    previous process that died mid-flight. The reaper flips them
    to ``cancelled`` with an "abandoned at restart" message so
    the Resume Tier flow can pick them up.
    """

    def test_reaps_running_rows(self, db, project_id):
        from backend.pipeline import queue as pipeline_queue

        running_id = _make_job(db, project_id, status="running")
        queued_id = _make_job(db, project_id, status="queued")
        completed_id = _make_job(db, project_id, status="completed")

        n = pipeline_queue.reap_orphaned_running_jobs(db)
        assert n == 1

        db.expire_all()
        running = db.get(Job, running_id)
        assert running.status == "cancelled"
        assert running.error_message == "Abandoned at server restart"
        assert running.completed_at is not None
        # Other statuses untouched.
        assert db.get(Job, queued_id).status == "queued"
        assert db.get(Job, completed_id).status == "completed"

    def test_no_running_rows_is_a_noop(self, db, project_id):
        from backend.pipeline import queue as pipeline_queue

        _make_job(db, project_id, status="queued")
        _make_job(db, project_id, status="completed")
        n = pipeline_queue.reap_orphaned_running_jobs(db)
        assert n == 0


class TestDelete:
    def test_deletes_terminal_job(self, client, db, project_id):
        jid = _make_job(db, project_id, status="completed")
        r = client.delete(f"/api/projects/{project_id}/jobs/{jid}")
        assert r.status_code == 200
        db.expire_all()
        assert db.get(Job, jid) is None

    def test_cancels_then_deletes_queued(self, client, db, project_id):
        jid = _make_job(db, project_id, status="queued")
        r = client.delete(f"/api/projects/{project_id}/jobs/{jid}")
        assert r.status_code == 200
        db.expire_all()
        assert db.get(Job, jid) is None

    def test_409_on_running(self, client, db, project_id):
        jid = _make_job(db, project_id, status="running")
        r = client.delete(f"/api/projects/{project_id}/jobs/{jid}")
        assert r.status_code == 409
        db.expire_all()
        assert db.get(Job, jid) is not None
