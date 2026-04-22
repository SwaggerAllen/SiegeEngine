"""Tests for Phase 12 batched-review supporting state.

Covers the helpers in ``backend/graph/review.py`` end-to-end:

* ``open_review_batch`` / ``close_review_batch`` — lifecycle of a
  ``ReviewBatch`` row, including idempotency of the close path and
  stable pinning against the project's latest event offset.
* ``get_or_build_snapshot`` — cache miss replays the reducer inside
  a savepoint so the live projection survives the snapshot build,
  cache hit returns the stored JSON without rebuilding, and
  project scoping keeps snapshots from leaking across tenants.

Keeps a separate module from ``test_queries`` because the review
tables are primary state rather than projections — exercising them
touches different machinery (savepoints, JSON roundtrip) than the
read-only projection queries.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database import Base
from backend.graph import events as ev
from backend.graph.ids import Kind, mint
from backend.graph.reducer import append_event, rebuild_projections
from backend.graph.review import (
    close_review_batch,
    get_or_build_snapshot,
    get_review_batch,
    open_review_batch,
)
from backend.models import Project
from backend.models.node import Node
from backend.models.review import ProjectionSnapshot, ReviewBatch


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


def _new_project(db: Session) -> str:
    pid = str(uuid.uuid4())
    db.add(Project(id=pid, name="T", git_repo_path="/tmp/t"))
    db.flush()
    return pid


def _seed_feat(db: Session, project_id: str, name: str, order: int) -> str:
    fid = mint(db, Kind.FEAT)
    append_event(
        db,
        project_id,
        ev.NodeCreated(
            node_id=fid,
            tier="feat",
            kind="domain",
            parent_id=None,
            name=name,
            display_order=order,
            content=f"{name} content.",
        ),
    )
    return fid


class TestReviewBatchLifecycle:
    def test_open_pins_latest_offset(self, db):
        pid = _new_project(db)
        _seed_feat(db, pid, "Login", 0)
        _seed_feat(db, pid, "Billing", 1)
        db.commit()

        batch = open_review_batch(db, pid)
        db.commit()

        # Two NodeCreated events → latest offset is 2.
        assert batch.pinned_offset == 2
        assert batch.project_id == pid
        assert batch.closed_at is None
        assert batch.id.startswith("batch_")

    def test_open_on_empty_project_pins_zero(self, db):
        pid = _new_project(db)
        db.commit()
        batch = open_review_batch(db, pid)
        db.commit()
        assert batch.pinned_offset == 0

    def test_open_rejects_unknown_project(self, db):
        with pytest.raises(ValueError, match="No project"):
            open_review_batch(db, "proj_missing")

    def test_close_stamps_timestamp(self, db):
        pid = _new_project(db)
        db.commit()
        batch = open_review_batch(db, pid)
        db.commit()
        assert batch.closed_at is None

        closed = close_review_batch(db, batch.id)
        db.commit()
        assert closed.closed_at is not None

    def test_close_is_idempotent(self, db):
        pid = _new_project(db)
        db.commit()
        batch = open_review_batch(db, pid)
        db.commit()
        first = close_review_batch(db, batch.id)
        db.commit()
        first_ts = first.closed_at
        # Second close leaves the first timestamp intact (close is a
        # one-way latch, not a toggle).
        second = close_review_batch(db, batch.id)
        db.commit()
        assert second.closed_at == first_ts

    def test_close_rejects_unknown_batch(self, db):
        with pytest.raises(ValueError, match="No review batch"):
            close_review_batch(db, "batch_deadbeef")

    def test_get_review_batch_returns_none_for_missing(self, db):
        assert get_review_batch(db, "batch_missing") is None

    def test_get_review_batch_fetches_existing(self, db):
        pid = _new_project(db)
        db.commit()
        batch = open_review_batch(db, pid)
        db.commit()
        fetched = get_review_batch(db, batch.id)
        assert fetched is not None
        assert fetched.id == batch.id


class TestGetOrBuildSnapshot:
    def test_cache_miss_builds_then_cache_hit_returns_same(self, db):
        pid = _new_project(db)
        _seed_feat(db, pid, "Login", 0)
        _seed_feat(db, pid, "Billing", 1)
        db.commit()

        # Cache empty on first call.
        assert db.execute(select(ProjectionSnapshot)).scalars().first() is None

        first = get_or_build_snapshot(db, pid, 2)
        db.commit()

        # Snapshot persisted.
        cached_rows = db.execute(select(ProjectionSnapshot)).scalars().all()
        assert len(cached_rows) == 1
        cached_row = cached_rows[0]
        assert cached_row.project_id == pid
        assert cached_row.offset == 2

        # Second call returns the same content without adding a row.
        second = get_or_build_snapshot(db, pid, 2)
        assert second == first
        assert db.execute(select(ProjectionSnapshot)).scalars().all() == [cached_row]

    def test_snapshot_captures_projection_at_offset(self, db):
        pid = _new_project(db)
        _seed_feat(db, pid, "Login", 0)
        _seed_feat(db, pid, "Billing", 1)
        db.commit()

        # Snapshot at offset 1 should see only Login, not Billing.
        payload = get_or_build_snapshot(db, pid, 1)
        db.commit()

        node_names = sorted(n["name"] for n in payload["nodes"])
        assert node_names == ["Login"]

    def test_live_projection_survives_snapshot_build(self, db):
        pid = _new_project(db)
        _seed_feat(db, pid, "Login", 0)
        _seed_feat(db, pid, "Billing", 1)
        db.commit()

        # Live projection has both features.
        live_before = db.execute(select(Node).where(Node.project_id == pid)).scalars().all()
        names_before = sorted(n.name for n in live_before)
        assert names_before == ["Billing", "Login"]

        # Build snapshot at offset 1 — replays only Login.
        get_or_build_snapshot(db, pid, 1)
        db.commit()

        # Savepoint rollback must leave the live projection intact.
        live_after = db.execute(select(Node).where(Node.project_id == pid)).scalars().all()
        names_after = sorted(n.name for n in live_after)
        assert names_after == ["Billing", "Login"]

    def test_project_scoping(self, db):
        pid_a = _new_project(db)
        pid_b = _new_project(db)
        _seed_feat(db, pid_a, "AuthLogin", 0)
        _seed_feat(db, pid_b, "BillingCharge", 0)
        db.commit()

        snap_a = get_or_build_snapshot(db, pid_a, 1)
        snap_b = get_or_build_snapshot(db, pid_b, 1)
        db.commit()

        names_a = {n["name"] for n in snap_a["nodes"]}
        names_b = {n["name"] for n in snap_b["nodes"]}
        assert names_a == {"AuthLogin"}
        assert names_b == {"BillingCharge"}

        # Each project has exactly one cached snapshot row.
        per_project = db.execute(
            select(ProjectionSnapshot.project_id, ProjectionSnapshot.offset)
        ).all()
        assert sorted(per_project) == sorted([(pid_a, 1), (pid_b, 1)])

    def test_rejects_offsets_past_latest(self, db):
        pid = _new_project(db)
        _seed_feat(db, pid, "Login", 0)
        db.commit()
        with pytest.raises(ValueError, match="past project"):
            get_or_build_snapshot(db, pid, 99)

    def test_rejects_negative_offset(self, db):
        pid = _new_project(db)
        db.commit()
        with pytest.raises(ValueError, match=">= 0"):
            get_or_build_snapshot(db, pid, -1)

    def test_review_state_survives_rebuild_projections(self, db):
        """ReviewBatch + ProjectionSnapshot rows are primary state.

        ``rebuild_projections`` wipes the event-derived tables
        (nodes, edges, fragments, drafts, staleness_ledger) but must
        NOT wipe the review tables, or the walker UI would lose its
        batch pin every time someone hits a debug rebuild.
        """
        pid = _new_project(db)
        _seed_feat(db, pid, "Login", 0)
        db.commit()

        batch = open_review_batch(db, pid)
        get_or_build_snapshot(db, pid, 1)
        db.commit()

        rebuild_projections(db, pid)
        db.commit()

        # Batch still present.
        assert db.get(ReviewBatch, batch.id) is not None
        # Snapshot still present.
        snaps = db.execute(select(ProjectionSnapshot)).scalars().all()
        assert len(snaps) == 1
