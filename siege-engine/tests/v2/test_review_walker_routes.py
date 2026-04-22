"""Walker route tests: list stale nodes + per-node diff.

Exercises the two walker endpoints added in PR-12c that back the
``ReviewBatchPage``'s left rail and detail pane.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime

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
from backend.graph import events as ev  # noqa: E402
from backend.graph.fragments import FragmentKind, fragment_id  # noqa: E402
from backend.graph.reducer import append_event  # noqa: E402
from backend.main import app  # noqa: E402
from backend.models import Project  # noqa: E402
from backend.models.node import StalenessLedger  # noqa: E402


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
    """Seed nodes + v1 fragment + a staleness marker at pinned offset.

    The later v2 fragment edit is emitted *inside the test* after
    the batch opens, so the pinned snapshot captures the v1 state
    and the live projection has v2 — giving the diff route a real
    before/after pair to surface.
    """
    p = Project(
        id=str(uuid.uuid4()),
        name="Walker Project",
        git_repo_path="/tmp/walker",
    )
    db.add(p)
    db.flush()

    append_event(
        db,
        p.id,
        ev.NodeCreated(
            node_id="comp_XXXX1111",
            tier="comp",
            kind="domain",
            parent_id=None,
            name="Auth",
            display_order=0,
            content="Auth content.",
        ),
    )
    append_event(
        db,
        p.id,
        ev.NodeCreated(
            node_id="comp_YYYY2222",
            tier="comp",
            kind="domain",
            parent_id=None,
            name="Billing",
            display_order=1,
            content="Billing content.",
        ),
    )
    frag = fragment_id("comp_XXXX1111", FragmentKind.TECHSPEC)
    append_event(
        db,
        p.id,
        ev.FragmentUpdated(
            fragment_id=frag,
            owner_id="comp_XXXX1111",
            fragment_kind=FragmentKind.TECHSPEC,
            new_content="v1 techspec",
        ),
    )
    db.flush()

    # Staleness marker: comp_XXXX1111 stale wrt comp_YYYY2222.
    db.add(
        StalenessLedger(
            project_id=p.id,
            stale_node_id="comp_XXXX1111",
            source_node_id="comp_YYYY2222",
            source_offset=2,
            reason="content_changed",
            created_at=datetime.utcnow(),
        )
    )
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


class TestWalkerNodesList:
    def test_lists_stale_nodes_for_batch(self, client, project):
        opened = client.post(f"/api/projects/{project.id}/review/batches").json()
        resp = client.get(f"/api/projects/{project.id}/review/batches/{opened['id']}/nodes")
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) == 1
        assert items[0]["node_id"] == "comp_XXXX1111"
        assert items[0]["reasons"] == ["content_changed"]
        assert items[0]["is_destructive"] is False

    def test_unknown_batch_is_404(self, client, project):
        resp = client.get(f"/api/projects/{project.id}/review/batches/batch_nope/nodes")
        assert resp.status_code == 404


class TestWalkerNodeDiff:
    def test_diff_returns_fragment_before_and_after(self, client, project, db):
        # Open batch at the v1-fragment offset, then land a v2 edit
        # so live differs from pinned.
        opened = client.post(f"/api/projects/{project.id}/review/batches").json()
        frag = fragment_id("comp_XXXX1111", FragmentKind.TECHSPEC)
        append_event(
            db,
            project.id,
            ev.FragmentUpdated(
                fragment_id=frag,
                owner_id="comp_XXXX1111",
                fragment_kind=FragmentKind.TECHSPEC,
                new_content="v2 techspec",
            ),
        )
        db.commit()

        resp = client.get(
            f"/api/projects/{project.id}/review/batches/{opened['id']}/nodes/comp_XXXX1111/diff"
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["node_content"]["before"] == "Auth content."
        assert body["node_content"]["after"] == "Auth content."
        frag_entries = {f["fragment_kind"]: f for f in body["fragments"]}
        assert FragmentKind.TECHSPEC in frag_entries
        techspec = frag_entries[FragmentKind.TECHSPEC]
        assert techspec["before"] == "v1 techspec"
        assert techspec["after"] == "v2 techspec"

    def test_diff_rejects_node_from_other_project(self, client, project, db):
        # Seed a node in a different project and make sure the
        # walker route won't diff it under this batch.
        other = Project(
            id=str(uuid.uuid4()),
            name="Other",
            git_repo_path="/tmp/o",
        )
        db.add(other)
        append_event(
            db,
            other.id,
            ev.NodeCreated(
                node_id="comp_ZZZZ3333",
                tier="comp",
                kind="domain",
                name="Other",
            ),
        )
        db.commit()
        opened = client.post(f"/api/projects/{project.id}/review/batches").json()
        resp = client.get(
            f"/api/projects/{project.id}/review/batches/{opened['id']}/nodes/comp_ZZZZ3333/diff"
        )
        assert resp.status_code == 404

    def test_diff_404_on_missing_node(self, client, project):
        opened = client.post(f"/api/projects/{project.id}/review/batches").json()
        resp = client.get(
            f"/api/projects/{project.id}/review/batches/{opened['id']}/nodes/comp_MISSING1/diff"
        )
        assert resp.status_code == 404
