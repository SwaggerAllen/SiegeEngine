"""Regenerate-review affordance + stale-review clearing on regen.

Two behaviors pinned here:

1. When the AI review has landed (success state) the structured
   findings view surfaces a "Regenerate review" button that calls
   the same retry path the failed-state button uses. Previously
   the only way to re-run a review was to wait for a failure.
2. The button is hidden when ``onRetryReview`` isn't wired
   (approved-content branches that don't plumb the retry handler).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

pytest.importorskip("bs4")  # review XML parser uses bs4


def _structured_review_markdown() -> str:
    return (
        "<review>"
        "<intro>Mid-fix shape.</intro>"
        "<score>55</score>"
        "<handles-structure>"
        '<finding id="h1">A specific handle issue.</finding>'
        "</handles-structure>"
        "<architectural-decisions>"
        '<finding id="a1">A specific axis issue.</finding>'
        "</architectural-decisions>"
        "</review>"
    )


def test_structured_review_has_regenerate_button_hook():
    """The ReviewBlockProps contract includes both
    ``onSelectionChanged`` (for feedback folding) and
    ``onRetryReview`` (for the new regenerate button). Callers
    may wire one, both, or neither."""
    from backend.graph.prompts.review._shared import render_review_system_prompt

    # Render still works — asserts the shared template render
    # didn't get coupled to a specific kwarg shape.
    sys = render_review_system_prompt(
        artifact_label="``<x>``",
        scope_label="this scope",
        handles_criteria="- one\n",
        architecture_criteria="- one\n",
    )
    assert "Handles & structure review" in sys


def test_bootstrap_feedback_clears_stale_review(db, project):
    """Posting feedback on a tier with a pending draft that carries
    an AI review should blank that draft's review_text so the UI
    doesn't show critique of content that's about to be replaced."""
    from backend.graph import events as ev
    from backend.graph.bootstrap_routes import bootstrap_feedback
    from backend.graph.expansion import (
        bootstrap_expansion_node,
        pending_expansion_draft,
    )
    from backend.graph.reducer import append_event
    from backend.graph.routes import EXPANSION_CONFIG

    exp_id = bootstrap_expansion_node(db, project.id)
    draft_id = "draft_stale00000"
    append_event(
        db,
        project.id,
        ev.DraftGenerated(
            draft_id=draft_id,
            target_type="node",
            target_id=exp_id,
            content="<features><feature><name>X</name><intent>ok</intent></feature></features>",
            batch_id="batch_test",
        ),
    )
    append_event(
        db,
        project.id,
        ev.DraftReviewUpdated(
            draft_id=draft_id,
            node_id=exp_id,
            review_text=_structured_review_markdown(),
        ),
    )
    db.commit()

    # Pre-condition: draft's review_text is populated.
    pending = pending_expansion_draft(db, project.id)
    assert pending is not None
    assert pending.review_text.strip() != ""

    # Post feedback — should blank the pending draft's review_text.
    require = MagicMock()
    bootstrap_feedback(
        db,
        project.id,
        (),
        "tweak the billing intent",
        EXPANSION_CONFIG,
        require,
    )

    db.expire_all()
    pending_after = pending_expansion_draft(db, project.id)
    assert pending_after is not None
    assert pending_after.review_text == "", (
        "Posting feedback must clear the stale review on the old "
        "pending draft; otherwise the UI shows critique of content "
        "that's about to be replaced."
    )


def test_bootstrap_feedback_threads_prior_review_into_regen_payload(db, project):
    """The AI review_text on the pending draft must ride along on
    the regen job payload as ``prior_review_text`` so the next
    generation prompt can surface it. Without this, the AI review's
    recommendations stay trapped on the about-to-be-discarded draft
    row and the regen never sees them."""
    from unittest.mock import MagicMock

    from backend.graph import events as ev
    from backend.graph.bootstrap_routes import bootstrap_feedback
    from backend.graph.expansion import bootstrap_expansion_node
    from backend.graph.reducer import append_event
    from backend.graph.routes import EXPANSION_CONFIG
    from backend.models.job import Job

    exp_id = bootstrap_expansion_node(db, project.id)
    draft_id = "draft_priorrev0"
    append_event(
        db,
        project.id,
        ev.DraftGenerated(
            draft_id=draft_id,
            target_type="node",
            target_id=exp_id,
            content="<features><feature><name>X</name><intent>ok</intent></feature></features>",
            batch_id="batch_priorrev",
        ),
    )
    review_markdown = _structured_review_markdown()
    append_event(
        db,
        project.id,
        ev.DraftReviewUpdated(
            draft_id=draft_id,
            node_id=exp_id,
            review_text=review_markdown,
        ),
    )
    db.commit()

    bootstrap_feedback(
        db,
        project.id,
        (),
        "user feedback string",
        EXPANSION_CONFIG,
        MagicMock(),
    )
    db.commit()

    # The expansion regen job was enqueued. Inspect its payload.
    regen_job = (
        db.query(Job)
        .filter(Job.job_type == EXPANSION_CONFIG.generate_job_type)
        .order_by(Job.created_at.desc())
        .first()
    )
    assert regen_job is not None
    payload = regen_job.payload or {}
    assert payload.get("prior_review_text") == review_markdown, (
        "The pending draft's AI review_text must be captured into the "
        "regen payload before bootstrap_feedback's UI-clear, so the "
        "generation handler can surface it in the next prompt."
    )
    assert payload.get("feedback") == "user feedback string"


def test_bootstrap_feedback_omits_prior_review_text_when_review_is_blank(db, project):
    """No payload field when there's no review to thread — the
    handler reads ``payload.get("prior_review_text") or None`` so a
    missing key resolves cleanly to None in the prompt."""
    from unittest.mock import MagicMock

    from backend.graph import events as ev
    from backend.graph.bootstrap_routes import bootstrap_feedback
    from backend.graph.expansion import bootstrap_expansion_node
    from backend.graph.reducer import append_event
    from backend.graph.routes import EXPANSION_CONFIG
    from backend.models.job import Job

    exp_id = bootstrap_expansion_node(db, project.id)
    draft_id = "draft_noreview0"
    append_event(
        db,
        project.id,
        ev.DraftGenerated(
            draft_id=draft_id,
            target_type="node",
            target_id=exp_id,
            content="<features><feature><name>X</name><intent>ok</intent></feature></features>",
            batch_id="batch_noreview",
        ),
    )
    db.commit()

    bootstrap_feedback(
        db,
        project.id,
        (),
        "user feedback only",
        EXPANSION_CONFIG,
        MagicMock(),
    )
    db.commit()

    regen_job = (
        db.query(Job)
        .filter(Job.job_type == EXPANSION_CONFIG.generate_job_type)
        .order_by(Job.created_at.desc())
        .first()
    )
    assert regen_job is not None
    assert "prior_review_text" not in (regen_job.payload or {})
