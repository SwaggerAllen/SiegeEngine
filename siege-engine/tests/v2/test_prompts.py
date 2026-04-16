"""Tests for backend.graph.prompts.feature_expansion."""

from __future__ import annotations

from backend.graph.prompts.feature_expansion import (
    render_system_prompt,
    render_user_prompt,
)
from backend.projects.settings import NodeCountRange, ProjectSettings


def _default_system_prompt() -> str:
    """Shared helper: render the system prompt with project defaults."""
    return render_system_prompt(ProjectSettings().features_per_group)


class TestSystemPrompt:
    def test_is_nonempty_str(self):
        prompt = _default_system_prompt()
        assert isinstance(prompt, str)
        assert len(prompt) > 0
        assert "feature expansion" in prompt

    def test_describes_tagged_output_format(self):
        # The prompt must instruct the model to emit a <features>
        # block with <feature>/<name>/<intent> structure — the
        # format the mint handler's parser-validator expects.
        prompt = _default_system_prompt()
        assert "<features>" in prompt
        assert "<feature>" in prompt
        assert "<name>" in prompt
        assert "<intent>" in prompt

    def test_describes_name_and_intent_shape(self):
        # Name is a short identifier, intent is a paragraph. Loose
        # assertions — we want the prompt to be able to evolve
        # without breaking tests, but the *concept* has to be there.
        prompt = _default_system_prompt()
        assert "title case" in prompt or "short" in prompt
        assert "paragraph" in prompt or "sentences" in prompt

    def test_describes_implicit_features(self):
        # The prompt must explain when to mark features <implicit/>.
        prompt = _default_system_prompt()
        assert "<implicit" in prompt
        # Concept: inferred, obviously necessary, not in input doc.
        assert "obviously" in prompt or "inferred" in prompt

    def test_describes_feature_groups(self):
        # The prompt must describe the <group> wrapper and its name.
        prompt = _default_system_prompt()
        assert "<group>" in prompt
        # Concept: themes, bundling related features.
        assert "theme" in prompt or "related features" in prompt


class TestRenderSystemPrompt:
    """The granularity bullet cites the four features-per-group
    numbers substituted from :class:`NodeCountRange`."""

    def test_substitutes_default_numbers(self) -> None:
        # Defaults are floor=2 / typical_min=3 / typical_max=8 /
        # ceiling=15. All four must appear in the rendered text.
        prompt = _default_system_prompt()
        assert "3–8 features per group" in prompt
        assert "2 or fewer features" in prompt
        assert "15 or more features" in prompt

    def test_substitutes_custom_numbers(self) -> None:
        counts = NodeCountRange(floor=7, typical_min=11, typical_max=13, ceiling=17)
        prompt = render_system_prompt(counts)
        assert "11–13 features per group" in prompt
        assert "7 or fewer features" in prompt
        assert "17 or more features" in prompt
        # Sanity: none of the default numbers leaked through for
        # the granularity bullet.
        assert "3–8 features per group" not in prompt

    def test_no_raw_placeholder_tokens_leak(self) -> None:
        prompt = _default_system_prompt()
        for token in ("{{FLOOR}}", "{{TYPICAL_MIN}}", "{{TYPICAL_MAX}}", "{{CEILING}}"):
            assert token not in prompt


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
        assert "# Current version" in out
        assert "## Contacts" in out
        assert "Improve the feature expansion above" in out

    def test_feedback_with_prior_pending(self):
        out = render_user_prompt(
            input_doc="A CRM.",
            prior_approved=None,
            prior_pending="## Contacts\n- CRUD",
            feedback="Also cover pipeline management.",
        )
        assert "# Current version" in out
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
        assert "# Current version" in out
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
