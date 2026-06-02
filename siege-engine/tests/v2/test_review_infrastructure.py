"""Phase 8 — tests for the review infrastructure scaffolding.

Covers:
- Reducer applies ``DraftReviewUpdated`` to both Draft and Node
  targets.
- Broadcaster surfaces the event with the owning node_id.
- ``running_node_ids`` includes nodes with active review jobs.
- ``bootstrap_get_state`` threads the five new review fields
  through per-tier responses.
"""

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

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from backend.database import Base  # noqa: E402
from backend.graph import events as ev  # noqa: E402
from backend.graph.broadcast import _node_ids_for_event  # noqa: E402
from backend.graph.ids import Kind, mint  # noqa: E402
from backend.graph.reducer import append_event  # noqa: E402
from backend.models import Project  # noqa: E402
from backend.models.node import Draft, Node  # noqa: E402


@pytest.fixture()
def factory(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    import backend.database as _database_mod

    monkeypatch.setattr(_database_mod, "SessionLocal", factory)
    yield factory
    engine.dispose()


@pytest.fixture()
def db(factory):
    s: Session = factory()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture()
def project(db):
    p = Project(id=str(uuid.uuid4()), name="Test", git_repo_path="/tmp/test")
    db.add(p)
    db.commit()
    return p


class TestReducerApplyDraftReviewUpdated:
    """``DraftReviewUpdated`` writes to the right target row."""

    def test_applies_to_draft_target(self, db, project):
        # Seed a comp + a pending draft targeting it.
        cid = mint(db, Kind.COMP)
        append_event(
            db,
            project.id,
            ev.NodeCreated(node_id=cid, tier="comp", kind="domain", name="C"),
        )
        draft = Draft(
            id="draft_test000001",
            project_id=project.id,
            target_type="node",
            target_id=cid,
            content="<comparch/>",
            status="pending",
            batch_id="batch_test00000001",
        )
        db.add(draft)
        db.commit()

        append_event(
            db,
            project.id,
            ev.DraftReviewUpdated(
                draft_id=draft.id,
                node_id=cid,
                review_text="## Handles\n\nLooks good.",
            ),
        )
        db.commit()

        db.refresh(draft)
        assert draft.review_text == "## Handles\n\nLooks good."

    def test_applies_to_node_target_for_fanin(self, db, project):
        # Fanin has no draft lifecycle — review lands on the Node row.
        cid = mint(db, Kind.COMP)
        append_event(
            db,
            project.id,
            ev.NodeCreated(node_id=cid, tier="comp", kind="domain", name="Domain"),
        )
        fid = mint(db, Kind.FANIN)
        append_event(
            db,
            project.id,
            ev.NodeCreated(
                node_id=fid,
                tier="fanin",
                kind="domain",
                parent_id=cid,
                name="Domain fan-in",
            ),
        )
        db.commit()

        append_event(
            db,
            project.id,
            ev.DraftReviewUpdated(
                draft_id=None,
                node_id=fid,
                review_text="## Handles\n\nSynthesis is faithful.",
            ),
        )
        db.commit()

        fanin_node = db.get(Node, fid)
        assert fanin_node is not None
        assert fanin_node.review_text == "## Handles\n\nSynthesis is faithful."


class TestBroadcasterMapping:
    """``_node_ids_for_event`` picks node_id out of the payload."""

    def test_emits_node_id_for_draft_review_updated(self):
        payload = {
            "draft_id": "draft_test000001",
            "node_id": "comp_AAAAAAAA",
            "review_text": "…",
        }
        ids = _node_ids_for_event("DraftReviewUpdated", payload)
        assert ids == ("comp_AAAAAAAA",)

    def test_returns_empty_when_node_id_missing(self):
        # Defensive guard: malformed payload should not crash.
        ids = _node_ids_for_event("DraftReviewUpdated", {"draft_id": "d"})
        assert ids == ()


# TestRunningIncludesReview removed: per-tier review handlers + their
# job types retired with the rest of the per-tier surface. The
# reducer-level DraftReviewUpdated path stays — drafts can still
# carry review_text from the historical chain — but no new review
# jobs are enqueued.


class TestBootstrapGetStateReviewFields:
    """The five new review fields surface on the response dict."""

    def test_review_fields_idle_by_default(self, db, project, monkeypatch):
        # Use the sysarch config, which has an actual bootstrap lifecycle.
        from backend.graph.bootstrap_routes import (
            BootstrapTierConfig,
            bootstrap_get_state,
        )
        from backend.graph.sysarch import (
            bootstrap_sysarch_node,
            get_sysarch_node,
            pending_sysarch_draft,
        )

        cfg = BootstrapTierConfig(
            tier_name="Sysarch",
            get_node=get_sysarch_node,
            get_pending_draft=pending_sysarch_draft,
            has_been_approved=None,
            bootstrap_node=bootstrap_sysarch_node,
            generate_job_type="v2.generate_sysarch",
            mint_job_type="v2.mint_sysarch",
            serialize_node=lambda n: {
                "id": n.id,
                "name": n.name,
                "content": n.content or "",
                "updated_at": n.updated_at.isoformat() if n.updated_at else "",
            },
            serialize_draft=lambda d: {
                "id": d.id,
                "content": d.content,
                "created_at": d.created_at.isoformat() if d.created_at else "",
            },
            review_job_type="v2.review_sysarch",
        )

        def _require_project(db, pid):
            pass

        state = bootstrap_get_state(db, project.id, (), cfg, _require_project)
        assert state["review_text"] == ""
        assert state["review_status"] == "idle"
        assert state["review_last_error"] is None
        assert state["review_started_at"] is None
        assert state["review_current_attempt"] is None
        assert state["review_max_attempts"] is None

    def test_review_fields_absent_when_review_job_type_unset(self, db, project):
        # A config with review_job_type="" still returns the keys
        # but with default "idle" semantics.
        from backend.graph.bootstrap_routes import (
            BootstrapTierConfig,
            bootstrap_get_state,
        )
        from backend.graph.sysarch import (
            bootstrap_sysarch_node,
            get_sysarch_node,
            pending_sysarch_draft,
        )

        cfg = BootstrapTierConfig(
            tier_name="Sysarch",
            get_node=get_sysarch_node,
            get_pending_draft=pending_sysarch_draft,
            has_been_approved=None,
            bootstrap_node=bootstrap_sysarch_node,
            generate_job_type="v2.generate_sysarch",
            mint_job_type="v2.mint_sysarch",
            serialize_node=lambda n: {
                "id": n.id,
                "name": n.name,
                "content": n.content or "",
                "updated_at": n.updated_at.isoformat() if n.updated_at else "",
            },
            serialize_draft=lambda d: {
                "id": d.id,
                "content": d.content,
                "created_at": d.created_at.isoformat() if d.created_at else "",
            },
            # review_job_type left unset
        )

        def _require_project(db, pid):
            pass

        state = bootstrap_get_state(db, project.id, (), cfg, _require_project)
        assert state["review_text"] == ""
        assert state["review_status"] == "idle"
