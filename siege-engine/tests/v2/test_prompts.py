"""Tests for backend.graph.prompts.feature_expansion."""

from __future__ import annotations

from backend.graph.prompts.feature_expansion import (
    SYSTEM_PROMPT,
    render_user_prompt,
)


class TestSystemPrompt:
    def test_is_nonempty_str(self):
        assert isinstance(SYSTEM_PROMPT, str)
        assert len(SYSTEM_PROMPT) > 0
        assert "feature expansion" in SYSTEM_PROMPT


class TestRenderUserPrompt:
    def test_initial_generation(self):
        out = render_user_prompt(
            input_doc="A note-taking app with tags.",
            prior_approved=None,
            prior_pending=None,
            feedback=None,
        )
        assert "A note-taking app with tags." in out
        assert "# Project input document" in out
        assert "# Task" in out
        assert "initial feature expansion" in out
        assert "Previously-approved" not in out
        assert "Current draft" not in out
        assert "User feedback" not in out
        assert out.endswith("\n")

    def test_feedback_only(self):
        out = render_user_prompt(
            input_doc="A CRM.",
            prior_approved=None,
            prior_pending=None,
            feedback="Focus more on SMB pain points.",
        )
        assert "Focus more on SMB pain points." in out
        assert "# User feedback" in out
        assert "Previously-approved" not in out
        assert "Current draft" not in out
        # Feedback with no prior content still routes through the
        # "initial generation" path because there's nothing to revise.
        assert "initial feature expansion" in out

    def test_prior_pending_no_feedback(self):
        out = render_user_prompt(
            input_doc="A CRM.",
            prior_approved=None,
            prior_pending="## Contacts\n- CRUD",
            feedback=None,
        )
        assert "# Current draft" in out
        assert "## Contacts" in out
        assert "Regenerate the feature expansion from scratch" in out
        assert "Previously-approved" not in out

    def test_feedback_with_prior_pending(self):
        out = render_user_prompt(
            input_doc="A CRM.",
            prior_approved=None,
            prior_pending="## Contacts\n- CRUD",
            feedback="Also cover pipeline management.",
        )
        assert "# Current draft" in out
        assert "# User feedback" in out
        assert "Also cover pipeline management." in out
        assert "Revise the feature expansion" in out

    def test_feedback_with_prior_approved(self):
        out = render_user_prompt(
            input_doc="A CRM.",
            prior_approved="## Contacts approved",
            prior_pending=None,
            feedback="Add reporting.",
        )
        assert "# Previously-approved feature expansion" in out
        assert "## Contacts approved" in out
        assert "# User feedback" in out
        assert "Revise the feature expansion" in out

    def test_empty_input_doc_is_marked(self):
        out = render_user_prompt(
            input_doc="",
            prior_approved=None,
            prior_pending=None,
            feedback=None,
        )
        assert "(no input document supplied)" in out
