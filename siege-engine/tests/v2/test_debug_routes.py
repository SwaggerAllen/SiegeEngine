"""Tests for the project debug-snapshot endpoint."""

from __future__ import annotations

import os
import uuid

import pytest

os.environ.setdefault("SIEGE_DISABLE_WORKER_LOOP", "1")

try:
    import cryptography.hazmat.bindings._rust  # noqa: F401
except BaseException as _exc:  # pragma: no cover
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
from backend.graph import events as ev  # noqa: E402
from backend.graph.ids import Kind, mint  # noqa: E402
from backend.graph.reducer import append_event  # noqa: E402
from backend.main import app  # noqa: E402
from backend.models import Project  # noqa: E402
from backend.pipeline import queue as pipeline_queue  # noqa: E402


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
def client(db):
    project_id = str(uuid.uuid4())
    db.add(Project(id=project_id, name="T", git_repo_path="/tmp/t"))
    db.flush()

    feat_id = mint(db, Kind.FEAT)
    append_event(
        db,
        project_id,
        ev.NodeCreated(
            node_id=feat_id,
            tier="feat",
            kind="domain",
            parent_id=None,
            name="Feature A",
            display_order=0,
            content="Feature A intent.",
        ),
    )
    pipeline_queue.enqueue(
        db,
        job_type="v2.generate_requirements",
        payload={"project_id": project_id, "feedback": None},
    )
    db.commit()

    def _get_db():
        yield db

    def _get_user():
        return object()

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[get_current_user] = _get_user
    try:
        yield TestClient(app), project_id
    finally:
        app.dependency_overrides.clear()


def test_snapshot_returns_full_project_state(client):
    c, pid = client
    r = c.get(f"/api/projects/{pid}/debug/snapshot")
    assert r.status_code == 200
    body = r.json()
    assert body["project"]["id"] == pid
    assert body["summary"]["node_count"] == 1
    assert body["summary"]["edge_count"] == 0
    assert body["summary"]["events_returned"] >= 1
    assert body["summary"]["jobs_returned"] == 1

    # Node payload echoes the seeded feature.
    feat_node = next(n for n in body["nodes"] if n["tier"] == "feat")
    assert feat_node["name"] == "Feature A"
    assert feat_node["content_length"] > 0

    # Recent events include the NodeCreated.
    event_types = {e["event_type"] for e in body["recent_events"]}
    assert "NodeCreated" in event_types

    # Recent jobs filter by project_id from the payload.
    job = body["recent_jobs"][0]
    assert job["job_type"] == "v2.generate_requirements"
    assert job["payload"]["project_id"] == pid


def test_unknown_project_404s(client):
    c, _ = client
    r = c.get(f"/api/projects/{uuid.uuid4()}/debug/snapshot")
    assert r.status_code == 404


def test_event_and_job_limits_clamp(client):
    c, pid = client
    r = c.get(f"/api/projects/{pid}/debug/snapshot?events=5000&jobs=5000")
    assert r.status_code == 200
    body = r.json()
    # Caps at 2000 events / 500 jobs even when caller asks for more.
    assert body["summary"]["events_returned"] <= 2000
    assert body["summary"]["jobs_returned"] <= 500


def test_event_payload_strips_long_content_fields(client, db):
    c, pid = client
    # Append events that carry a long ``content`` body and a long
    # ``new_content``. The snapshot should replace each with an
    # ``[content elided: N chars]`` placeholder so the dump stays
    # paste-friendly. We exercise NodeCreated.content and
    # NodeContentUpdated.new_content here; review_text elision is
    # covered by the unit test on _strip_event_content below.
    big_body = "<comparch>" + ("x" * 5000) + "</comparch>"

    comp_id = mint(db, Kind.COMP)
    append_event(
        db,
        pid,
        ev.NodeCreated(
            node_id=comp_id,
            tier="comp",
            kind="domain",
            parent_id=None,
            name="Big",
            display_order=0,
            content=big_body,
        ),
    )
    append_event(
        db,
        pid,
        ev.NodeContentUpdated(node_id=comp_id, new_content=big_body),
    )
    db.commit()

    r = c.get(f"/api/projects/{pid}/debug/snapshot?events=2000")
    body = r.json()
    big_created = next(
        e
        for e in body["recent_events"]
        if e["event_type"] == "NodeCreated" and e["payload"].get("node_id") == comp_id
    )
    big_updated = next(e for e in body["recent_events"] if e["event_type"] == "NodeContentUpdated")

    assert big_created["payload"]["content"].startswith("[content elided:")
    assert big_updated["payload"]["new_content"].startswith("[content elided:")
    # Other payload fields stay as-is.
    assert big_created["payload"]["node_id"] == comp_id
    assert big_updated["payload"]["node_id"] == comp_id


def test_strip_payload_content_handles_review_text_directly():
    from backend.graph.debug_routes import _strip_payload_content

    big_review = "<review>" + ("y" * 4000) + "</review>"
    payload = {
        "event_type": "DraftReviewUpdated",
        "draft_id": "draft_xxx",
        "node_id": "comp_AAAA0000",
        "review_text": big_review,
    }
    out = _strip_payload_content(payload)
    assert out is not None
    assert out["review_text"].startswith("[content elided:")
    assert out["draft_id"] == "draft_xxx"
    assert out["node_id"] == "comp_AAAA0000"


def test_strip_payload_content_elides_prior_review_text_and_failed_raw_output():
    from backend.graph.debug_routes import _strip_payload_content

    big_review = "<review>" + ("y" * 4000) + "</review>"
    big_raw = "raw model output\n" * 1000
    payload = {
        "project_id": "proj_xxx",
        "component_id": "comp_AAAA0000",
        "feedback": "make it better",
        "prior_review_text": big_review,
        "_failed_raw_output": big_raw,
        "_current_attempt": 3,
        "_max_attempts": 4,
    }
    out = _strip_payload_content(payload)
    assert out is not None
    assert out["prior_review_text"].startswith("[content elided:")
    assert out["_failed_raw_output"].startswith("[content elided:")
    # Short / non-target fields stay verbatim.
    assert out["feedback"] == "make it better"
    assert out["component_id"] == "comp_AAAA0000"
    assert out["_current_attempt"] == 3


def test_recent_jobs_payload_elides_prior_review_text(client, db):
    c, pid = client
    big_review = "<review>" + ("y" * 4000) + "</review>"
    pipeline_queue.enqueue(
        db,
        job_type="v2.generate_comparch",
        payload={
            "project_id": pid,
            "component_id": "comp_BIGGGGGG",
            "feedback": None,
            "prior_review_text": big_review,
        },
    )
    db.commit()

    r = c.get(f"/api/projects/{pid}/debug/snapshot?jobs=500")
    body = r.json()
    big_job = next(
        j
        for j in body["recent_jobs"]
        if (j["payload"] or {}).get("component_id") == "comp_BIGGGGGG"
    )
    assert big_job["payload"]["prior_review_text"].startswith("[content elided:")
    # Other payload fields stay as-is.
    assert big_job["payload"]["component_id"] == "comp_BIGGGGGG"
    assert big_job["payload"]["project_id"] == pid


def test_short_content_strings_are_not_elided(client, db):
    c, pid = client
    short_body = "<sysarch/>"  # well under 200 chars
    sysarch_id = mint(db, Kind.SYSARCH)
    append_event(
        db,
        pid,
        ev.NodeCreated(
            node_id=sysarch_id,
            tier="sysarch",
            kind="domain",
            parent_id=None,
            name="Short",
            display_order=0,
            content=short_body,
        ),
    )
    db.commit()

    r = c.get(f"/api/projects/{pid}/debug/snapshot?events=2000")
    body = r.json()
    short_event = next(
        e
        for e in body["recent_events"]
        if e["event_type"] == "NodeCreated" and e["payload"].get("node_id") == sysarch_id
    )
    assert short_event["payload"]["content"] == short_body
