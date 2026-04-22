"""Phase 12d — accept semantics on the review walker.

Covers both branches of ``accept_review`` and its route surface:

* Non-destructive accept clears the ledger and enqueues no new jobs
  (the auto-cascade already fired at trigger time).
* Destructive accept (any ledger row with ``structural_change``)
  clears the ledger *and* enqueues a regen for the accepted node,
  re-firing the cascade that was halted when the destructive event
  landed.
* Idempotent: a second accept on the same node is a no-op.
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
from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from backend.auth.routes import get_current_user  # noqa: E402
from backend.database import Base, get_db  # noqa: E402
from backend.graph import events as ev  # noqa: E402
from backend.graph.reducer import append_event  # noqa: E402
from backend.graph.review import accept_review, open_review_batch  # noqa: E402
from backend.main import app  # noqa: E402
from backend.models import Project  # noqa: E402
from backend.models.job import Job  # noqa: E402
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


def _seed_project_with_stale_comp(db, destructive: bool) -> tuple[Project, str]:
    """Seed a project with a stale comp_* node + one ledger row.

    Returns ``(project, node_id)``. The ledger row's reason toggles
    between ``content_changed`` (non-destructive) and
    ``structural_change`` (destructive) based on the flag.
    """
    p = Project(id=str(uuid.uuid4()), name="T", git_repo_path="/tmp/t")
    db.add(p)
    node_id = "comp_XXXX1111"
    source_id = "comp_YYYY2222"
    append_event(
        db,
        p.id,
        ev.NodeCreated(
            node_id=node_id,
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
            node_id=source_id,
            tier="comp",
            kind="domain",
            parent_id=None,
            name="Billing",
            display_order=1,
            content="Billing content.",
        ),
    )
    db.add(
        StalenessLedger(
            project_id=p.id,
            stale_node_id=node_id,
            source_node_id=source_id,
            source_offset=1,
            reason="structural_change" if destructive else "content_changed",
            created_at=datetime.utcnow(),
        )
    )
    db.commit()
    return p, node_id


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


class TestAcceptReviewHelper:
    def test_non_destructive_clears_ledger_without_regen(self, db):
        p, node_id = _seed_project_with_stale_comp(db, destructive=False)
        batch = open_review_batch(db, p.id)
        db.commit()

        result = accept_review(db, p.id, batch.id, node_id)
        db.commit()

        assert result.is_destructive is False
        assert result.cleared_count == 1
        assert result.regen_job_ids == []
        remaining = (
            db.execute(
                select(StalenessLedger).where(
                    StalenessLedger.stale_node_id == node_id,
                )
            )
            .scalars()
            .all()
        )
        assert remaining == []
        # No jobs enqueued.
        assert db.execute(select(Job)).scalars().all() == []

    def test_destructive_enqueues_regen_for_accepted_node(self, db):
        p, node_id = _seed_project_with_stale_comp(db, destructive=True)
        batch = open_review_batch(db, p.id)
        db.commit()

        result = accept_review(db, p.id, batch.id, node_id)
        db.commit()

        assert result.is_destructive is True
        assert result.cleared_count == 1
        assert len(result.regen_job_ids) == 1

        # The regen is a v2.generate_comparch for the node (top-level
        # comp with parent_id=None).
        jobs = db.execute(select(Job)).scalars().all()
        assert len(jobs) == 1
        assert jobs[0].job_type == "v2.generate_comparch"
        assert jobs[0].payload["component_id"] == node_id

    def test_idempotent_second_accept_is_noop(self, db):
        p, node_id = _seed_project_with_stale_comp(db, destructive=True)
        batch = open_review_batch(db, p.id)
        db.commit()

        first = accept_review(db, p.id, batch.id, node_id)
        db.commit()
        second = accept_review(db, p.id, batch.id, node_id)
        db.commit()

        assert first.cleared_count == 1
        assert second.cleared_count == 0
        assert second.regen_job_ids == []
        # Only the first accept enqueued a job.
        assert len(db.execute(select(Job)).scalars().all()) == 1

    def test_rejects_node_not_in_project(self, db):
        p, _node_id = _seed_project_with_stale_comp(db, destructive=False)
        batch = open_review_batch(db, p.id)
        db.commit()
        with pytest.raises(ValueError, match="No node"):
            accept_review(db, p.id, batch.id, "comp_MISSINGX")

    def test_rejects_batch_from_other_project(self, db):
        p, node_id = _seed_project_with_stale_comp(db, destructive=False)
        other = Project(id=str(uuid.uuid4()), name="O", git_repo_path="/tmp/o")
        db.add(other)
        db.flush()
        other_batch = open_review_batch(db, other.id)
        db.commit()
        with pytest.raises(ValueError, match="No review batch"):
            accept_review(db, p.id, other_batch.id, node_id)


class TestAcceptReviewRoute:
    def test_post_clears_ledger_and_returns_result(self, db, client):
        p, node_id = _seed_project_with_stale_comp(db, destructive=False)
        opened = client.post(f"/api/projects/{p.id}/review/batches").json()
        resp = client.post(
            f"/api/projects/{p.id}/review/batches/{opened['id']}/nodes/{node_id}/accept"
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["cleared_count"] == 1
        assert body["is_destructive"] is False
        assert body["regen_job_ids"] == []

    def test_post_destructive_enqueues_regen(self, db, client):
        p, node_id = _seed_project_with_stale_comp(db, destructive=True)
        opened = client.post(f"/api/projects/{p.id}/review/batches").json()
        resp = client.post(
            f"/api/projects/{p.id}/review/batches/{opened['id']}/nodes/{node_id}/accept"
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["is_destructive"] is True
        assert len(body["regen_job_ids"]) == 1

    def test_post_rejects_missing_node(self, db, client):
        p, _ = _seed_project_with_stale_comp(db, destructive=False)
        opened = client.post(f"/api/projects/{p.id}/review/batches").json()
        resp = client.post(
            f"/api/projects/{p.id}/review/batches/{opened['id']}/nodes/comp_NOPENOPE/accept"
        )
        assert resp.status_code == 404
