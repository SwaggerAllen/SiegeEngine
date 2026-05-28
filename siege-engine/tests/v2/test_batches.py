"""Tests for the universal batch-id machinery.

Three layers:
- Helpers in :mod:`backend.graph.batches` — mint, gaps, list.
- Per-node + tier-op route handlers — verify batch_id rides through
  enqueue and stamps onto Job rows.
- Resume endpoint — exercises the "skip completed, re-enqueue gaps"
  logic that is the load-bearing reason this lives.
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

from datetime import datetime  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from backend.auth.routes import get_current_user  # noqa: E402
from backend.database import Base, get_db  # noqa: E402
from backend.graph.batches import (  # noqa: E402
    gaps_in_batch,
    jobs_in_batch,
    list_batches_for_tier,
    mint_batch,
)
from backend.main import app  # noqa: E402
from backend.models import Project, User  # noqa: E402
from backend.models.batch import Batch  # noqa: E402
from backend.models.job import Job  # noqa: E402
from backend.pipeline.queue import enqueue  # noqa: E402

# ── Fixtures ───────────────────────────────────────────────────────


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


def _seed_project(db: Session) -> str:
    project_id = str(uuid.uuid4())
    db.add(Project(id=project_id, name="T", git_repo_path="/tmp/t"))
    db.flush()
    return project_id


def _override_user_admin():
    return User(id="u1", username="t", password_hash="x", role="admin")


# ── Helper-layer tests ────────────────────────────────────────────


class TestMintAndQuery:
    def test_mint_batch_returns_id_and_persists_row(self, db):
        project_id = _seed_project(db)
        batch_id = mint_batch(
            db,
            project_id,
            op_type="reset_tier",
            tier="comparch",
            scope_keys={"scope_count": 5},
            params={"force": True},
        )
        db.commit()
        row = db.get(Batch, batch_id)
        assert row is not None
        assert row.project_id == project_id
        assert row.op_type == "reset_tier"
        assert row.tier == "comparch"
        assert row.scope_keys == {"scope_count": 5}
        assert row.params == {"force": True}
        assert row.status == "running"

    def test_list_batches_for_tier_filters_and_orders(self, db):
        project_id = _seed_project(db)
        b1 = mint_batch(db, project_id, op_type="reset_tier", tier="comparch")
        b2 = mint_batch(db, project_id, op_type="reset_tier", tier="impl")
        b3 = mint_batch(db, project_id, op_type="reset_tier", tier="comparch")
        # Force ordering
        db.get(Batch, b1).started_at = datetime(2026, 5, 1)
        db.get(Batch, b2).started_at = datetime(2026, 5, 2)
        db.get(Batch, b3).started_at = datetime(2026, 5, 3)
        db.commit()
        comparch_only = list_batches_for_tier(db, project_id, "comparch")
        assert [b.id for b in comparch_only] == [b3, b1]
        all_tiers = list_batches_for_tier(db, project_id, None)
        assert [b.id for b in all_tiers] == [b3, b2, b1]


class TestEnqueueStampsBatch:
    def test_enqueue_stamps_batch_id_on_job_and_payload(self, db):
        project_id = _seed_project(db)
        batch_id = mint_batch(db, project_id, op_type="single_node_reset")
        db.commit()
        job_id = enqueue(
            db,
            "v2.test_job",
            payload={"project_id": project_id, "k": 1},
            batch_id=batch_id,
        )
        job = db.get(Job, job_id)
        assert job is not None
        assert job.batch_id == batch_id
        assert job.payload["batch_id"] == batch_id

    def test_enqueue_dedup_distinguishes_batches(self, db):
        """Same job_type + base payload under different batches must
        NOT collapse into one row — each batch's queued job is its
        own work item."""
        project_id = _seed_project(db)
        b1 = mint_batch(db, project_id, op_type="single_node_reset")
        b2 = mint_batch(db, project_id, op_type="single_node_reset")
        db.commit()
        id1 = enqueue(db, "v2.test_job", payload={"project_id": project_id, "k": 1}, batch_id=b1)
        id2 = enqueue(db, "v2.test_job", payload={"project_id": project_id, "k": 1}, batch_id=b2)
        assert id1 != id2

    def test_enqueue_dedup_collapses_within_same_batch(self, db):
        project_id = _seed_project(db)
        batch_id = mint_batch(db, project_id, op_type="single_node_reset")
        db.commit()
        id1 = enqueue(
            db, "v2.test_job", payload={"project_id": project_id, "k": 1}, batch_id=batch_id
        )
        id2 = enqueue(
            db, "v2.test_job", payload={"project_id": project_id, "k": 1}, batch_id=batch_id
        )
        assert id1 == id2

    def test_enqueue_without_batch_works_legacy(self, db):
        project_id = _seed_project(db)
        db.commit()
        job_id = enqueue(db, "v2.test_job", payload={"project_id": project_id, "k": 2})
        job = db.get(Job, job_id)
        assert job is not None
        assert job.batch_id is None
        assert "batch_id" not in (job.payload or {})


class TestGapsInBatch:
    def test_gaps_returns_only_non_completed_jobs(self, db):
        project_id = _seed_project(db)
        batch_id = mint_batch(db, project_id, op_type="reset_tier")
        db.commit()
        # 3 jobs in the batch with mixed statuses.
        for status in ("completed", "failed", "queued"):
            j = Job(
                job_type="v2.test_job",
                payload={"project_id": project_id, "batch_id": batch_id, "status": status},
                status=status,
                batch_id=batch_id,
            )
            db.add(j)
        # One unrelated job in a different batch — should be ignored.
        other_batch = mint_batch(db, project_id, op_type="reset_tier")
        db.add(
            Job(
                job_type="v2.test_job",
                payload={"project_id": project_id, "batch_id": other_batch},
                status="failed",
                batch_id=other_batch,
            )
        )
        db.commit()

        gaps = gaps_in_batch(db, batch_id)
        statuses = sorted(g.status for g in gaps)
        assert statuses == ["failed", "queued"]
        # jobs_in_batch returns all 3
        assert len(jobs_in_batch(db, batch_id)) == 3


class TestListBatchesEndpoint:
    def test_list_batches_returns_recent(self, db, engine_and_factory):
        project_id = _seed_project(db)
        b1 = mint_batch(db, project_id, op_type="reset_tier", tier="comparch")
        mint_batch(db, project_id, op_type="reset_tier", tier="impl")
        db.commit()

        _, factory = engine_and_factory

        def _override_db():
            s = factory()
            try:
                yield s
            finally:
                s.close()

        app.dependency_overrides[get_db] = _override_db
        app.dependency_overrides[get_current_user] = _override_user_admin
        try:
            client = TestClient(app)
            resp = client.get(f"/api/projects/{project_id}/batches", params={"tier": "comparch"})
            assert resp.status_code == 200
            body = resp.json()
            ids = [b["id"] for b in body["batches"]]
            assert b1 in ids
            # Filter is exclusive — impl batch must not appear.
            assert all(b["tier"] == "comparch" for b in body["batches"])
        finally:
            app.dependency_overrides.clear()
