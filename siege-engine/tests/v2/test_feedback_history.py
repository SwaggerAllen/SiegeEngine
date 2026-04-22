"""B9 — Aggregate feedback history query.

Combines user prose feedback (from ``Job.payload['feedback']``)
with AI review text (from ``Draft.review_text``) for a single
target node, returned in chronological order.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from sqlalchemy import select

from backend.graph import events as ev
from backend.graph.ids import Kind, mint
from backend.graph.queries import feedback_history
from backend.graph.reducer import append_event
from backend.models.graph_event import GraphEvent
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

    def _emit_feedback_cleared_at(self, db, project_id: str, node_id: str, when: datetime) -> None:
        """Emit a ``FeedbackCleared`` event and pin its ``created_at``.

        Production emits it during ``bootstrap_reset`` and takes the
        wall-clock ``utcnow()`` stamp. Tests need deterministic time,
        so we rewrite the row's ``created_at`` after append.
        """
        append_event(db, project_id, ev.FeedbackCleared(node_id=node_id))
        row = (
            db.execute(
                select(GraphEvent)
                .where(
                    GraphEvent.project_id == project_id,
                    GraphEvent.event_type == "FeedbackCleared",
                )
                .order_by(GraphEvent.offset.desc())
            )
            .scalars()
            .first()
        )
        assert row is not None
        row.created_at = when
        db.flush()

    def test_feedback_cleared_filters_prior_user_feedback(self, db, project):
        nid = _mint_expansion_node(db, project.id)
        base = datetime(2026, 4, 20, 12, 0, 0)
        _add_job(
            db,
            project.id,
            "v2.generate_feature_expansion",
            "Pre-reset feedback — should be hidden.",
            base,
        )
        self._emit_feedback_cleared_at(db, project.id, nid, base + timedelta(minutes=5))
        _add_job(
            db,
            project.id,
            "v2.generate_feature_expansion",
            "Post-reset feedback — should show through.",
            base + timedelta(minutes=10),
        )

        entries = feedback_history(db, project.id, nid)
        assert [e.text for e in entries] == ["Post-reset feedback — should show through."]

    def test_feedback_cleared_filters_prior_ai_reviews(self, db, project):
        nid = _mint_expansion_node(db, project.id)
        base = datetime(2026, 4, 20, 12, 0, 0)
        _add_draft_with_review(db, project.id, nid, "Pre-reset review.", base)
        self._emit_feedback_cleared_at(db, project.id, nid, base + timedelta(minutes=5))
        _add_draft_with_review(
            db, project.id, nid, "Post-reset review.", base + timedelta(minutes=10)
        )

        entries = feedback_history(db, project.id, nid)
        assert [e.text for e in entries] == ["Post-reset review."]

    def test_feedback_cleared_most_recent_wins(self, db, project):
        """A second reset pushes the cutoff forward; post-first-reset entries
        that predate the second reset are also hidden."""
        nid = _mint_expansion_node(db, project.id)
        base = datetime(2026, 4, 20, 12, 0, 0)
        _add_job(db, project.id, "v2.generate_feature_expansion", "Before first reset.", base)
        self._emit_feedback_cleared_at(db, project.id, nid, base + timedelta(minutes=5))
        _add_job(
            db,
            project.id,
            "v2.generate_feature_expansion",
            "Between resets.",
            base + timedelta(minutes=10),
        )
        self._emit_feedback_cleared_at(db, project.id, nid, base + timedelta(minutes=15))
        _add_job(
            db,
            project.id,
            "v2.generate_feature_expansion",
            "After second reset.",
            base + timedelta(minutes=20),
        )

        entries = feedback_history(db, project.id, nid)
        assert [e.text for e in entries] == ["After second reset."]

    def test_feedback_cleared_scoped_to_node(self, db, project):
        """A reset on one node must not hide another node's feedback."""
        nid_a = _mint_expansion_node(db, project.id)
        # Second node on the same project.
        nid_b = mint(db, Kind.EXPANSION)
        append_event(
            db,
            project.id,
            ev.NodeCreated(
                node_id=nid_b,
                tier="expansion",
                kind="domain",
                parent_id=None,
                name="Other",
                content="",
            ),
        )
        base = datetime(2026, 4, 20, 12, 0, 0)
        _add_job(
            db,
            project.id,
            "v2.generate_feature_expansion",
            "Feedback on B.",
            base,
        )
        # But jobs aren't node-scoped in _add_job — bind by payload key.
        # Update the job we just added to target nid_b.
        latest_job = db.execute(select(Job).order_by(Job.created_at.desc())).scalars().first()
        latest_job.payload = {
            **(latest_job.payload or {}),
            "expansion_id": nid_b,
        }
        db.flush()
        # Reset only targets nid_a.
        self._emit_feedback_cleared_at(db, project.id, nid_a, base + timedelta(minutes=5))

        # Feedback on B must survive the reset on A.
        entries = feedback_history(db, project.id, nid_b)
        assert [e.text for e in entries] == ["Feedback on B."]

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
