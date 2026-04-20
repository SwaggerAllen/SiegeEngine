"""B9 — Aggregate feedback history query.

Combines user prose feedback (from ``Job.payload['feedback']``)
with AI review text (from ``Draft.review_text``) for a single
target node, returned in chronological order.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from backend.graph import events as ev
from backend.graph.ids import Kind, mint
from backend.graph.queries import feedback_history
from backend.graph.reducer import append_event
from backend.models.job import Job
from backend.models.node import Draft


def _mint_expansion_node(db, project_id: str) -> str:
    nid = mint(db, Kind.EXPANSION)
    append_event(
        db,
        project_id,
        ev.NodeCreated(
            node_id=nid,
            tier="expansion",
            kind="domain",
            parent_id=None,
            name="Feature Expansion",
            content="",
        ),
    )
    return nid


def _add_job(db, project_id: str, job_type: str, feedback: str | None, when: datetime) -> None:
    payload: dict = {"project_id": project_id}
    if feedback is not None:
        payload["feedback"] = feedback
    db.add(
        Job(
            id=str(uuid.uuid4()),
            job_type=job_type,
            payload=payload,
            status="completed",
            created_at=when,
        )
    )
    db.flush()


def _add_draft_with_review(
    db, project_id: str, target_id: str, review: str, when: datetime
) -> None:
    db.add(
        Draft(
            id=str(uuid.uuid4()),
            project_id=project_id,
            target_type="node",
            target_id=target_id,
            content="<features/>",
            status="approved",
            batch_id="batch_test",
            review_text=review,
            created_at=when,
        )
    )
    db.flush()


class TestFeedbackHistory:
    def test_returns_empty_when_no_history(self, db, project):
        nid = _mint_expansion_node(db, project.id)
        assert feedback_history(db, project.id, nid) == []

    def test_returns_missing_node_gracefully(self, db, project):
        assert feedback_history(db, project.id, "expansion_GHOST001") == []

    def test_walks_jobs_for_user_feedback(self, db, project):
        nid = _mint_expansion_node(db, project.id)
        now = datetime(2026, 4, 20, 12, 0, 0)
        _add_job(
            db,
            project.id,
            "v2.generate_feature_expansion",
            "Please sharpen the onboarding feature names.",
            now,
        )
        _add_job(
            db,
            project.id,
            "v2.generate_feature_expansion",
            None,  # no feedback — initial generation
            now - timedelta(minutes=10),
        )

        entries = feedback_history(db, project.id, nid)
        assert len(entries) == 1
        assert entries[0].source == "user"
        assert "sharpen the onboarding" in entries[0].text

    def test_walks_drafts_for_ai_reviews(self, db, project):
        nid = _mint_expansion_node(db, project.id)
        now = datetime(2026, 4, 20, 12, 0, 0)
        _add_draft_with_review(
            db,
            project.id,
            nid,
            "## Handles\nFlag: Onboarding intent reads generic.",
            now,
        )
        _add_draft_with_review(
            db,
            project.id,
            nid,
            "",  # empty review — should be filtered
            now + timedelta(minutes=1),
        )

        entries = feedback_history(db, project.id, nid)
        assert len(entries) == 1
        assert entries[0].source == "ai_review"
        assert "reads generic" in entries[0].text

    def test_merges_sources_chronologically(self, db, project):
        nid = _mint_expansion_node(db, project.id)
        base = datetime(2026, 4, 20, 12, 0, 0)
        _add_job(
            db,
            project.id,
            "v2.generate_feature_expansion",
            "First user feedback.",
            base + timedelta(minutes=3),
        )
        _add_draft_with_review(
            db,
            project.id,
            nid,
            "First AI review.",
            base + timedelta(minutes=1),
        )
        _add_draft_with_review(
            db,
            project.id,
            nid,
            "Second AI review.",
            base + timedelta(minutes=5),
        )

        entries = feedback_history(db, project.id, nid)
        assert [e.source for e in entries] == ["ai_review", "user", "ai_review"]
        assert "First AI review" in entries[0].text
        assert "First user feedback" in entries[1].text
        assert "Second AI review" in entries[2].text

    def test_filters_by_project_id(self, db, project):
        """Jobs from other projects must not leak into this project's history."""
        from backend.models import Project

        nid = _mint_expansion_node(db, project.id)
        other = Project(id=str(uuid.uuid4()), name="Other", git_repo_path="/tmp/other")
        db.add(other)
        db.flush()
        _add_job(
            db,
            other.id,
            "v2.generate_feature_expansion",
            "Other project feedback — must not appear.",
            datetime(2026, 4, 20, 12, 0, 0),
        )
        assert feedback_history(db, project.id, nid) == []
