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

    def test_describes_tagged_output_format(self):
        # The prompt must instruct the model to emit a <features>
        # block with <feature>/<name>/<intent> structure — the
        # format the mint handler's parser-validator expects.
        assert "<features>" in SYSTEM_PROMPT
        assert "<feature>" in SYSTEM_PROMPT
        assert "<name>" in SYSTEM_PROMPT
        assert "<intent>" in SYSTEM_PROMPT

    def test_describes_name_and_intent_shape(self):
        # Name is a short identifier, intent is a paragraph. Loose
        # assertions — we want the prompt to be able to evolve
        # without breaking tests, but the *concept* has to be there.
        assert "title case" in SYSTEM_PROMPT or "short" in SYSTEM_PROMPT
        assert "paragraph" in SYSTEM_PROMPT or "sentences" in SYSTEM_PROMPT


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


class TestRenderUserPromptParseErrorRetry:
    """The mint handler's parse-validate retry loop passes the
    parse/validation error back into the prompt via ``parse_error``
    so the LLM can correct its own structural mistakes."""

    def test_parse_error_section_renders(self):
        out = render_user_prompt(
            input_doc="A note-taking app.",
            prior_approved=None,
            prior_pending="<features>(malformed)</features>",
            feedback=None,
            parse_error="<feature> at position 0 is missing a <name> child.",
        )
        assert "Previous output failed structural validation" in out
        assert "<feature> at position 0 is missing a <name> child." in out
        assert "Re-emit the feature expansion" in out

    def test_parse_error_takes_precedence_over_feedback_task(self):
        # Even when feedback is also present, the task line on a
        # retry should be the "re-emit corrected block" variant,
        # not the normal "revise" one.
        out = render_user_prompt(
            input_doc="A CRM.",
            prior_approved=None,
            prior_pending="<features>junk</features>",
            feedback="Add reporting",
            parse_error="no valid <feature> children",
        )
        assert "Re-emit the feature expansion" in out
        # The feedback is still shown (for context), but the task
        # line is the retry one.
        assert "Add reporting" in out

    def test_no_parse_error_means_no_retry_section(self):
        out = render_user_prompt(
            input_doc="A note-taking app.",
            prior_approved=None,
            prior_pending=None,
            feedback=None,
            parse_error=None,
        )
        assert "Previous output failed structural validation" not in out
        assert "Re-emit" not in out
