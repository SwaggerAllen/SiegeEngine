"""Tests for ``backend.graph.prompts.requirements.render_system_prompt``.

The requirements system prompt cites a typical range plus a floor
and ceiling for top-level responsibility count. These numbers are
now substituted from the project's ``NodeCountRange`` at render
time rather than baked into the template.
"""

from __future__ import annotations

from backend.graph.prompts.requirements import render_system_prompt, render_user_prompt
from backend.projects.settings import NodeCountRange, ProjectSettings


class TestRenderSystemPrompt:
    def test_substitutes_default_numbers(self) -> None:
        # Defaults on ProjectSettings preserve the pre-refactor
        # prompt numbers (3 / 8 / 20 / 40). The rendered prompt must
        # cite those verbatim.
        counts = ProjectSettings().top_level_responsibilities
        out = render_system_prompt(counts)
        # Typical band shows up in the "typical project produces"
        # clause — substitute with an en dash.
        assert "8–20 top-level" in out
        # Floor shows up in the "fewer than" clause; ceiling in
        # the "or more" clause.
        assert "3 or fewer" in out
        assert "40 or more" in out

    def test_substitutes_custom_numbers(self) -> None:
        counts = NodeCountRange(floor=7, typical_min=11, typical_max=13, ceiling=17)
        out = render_system_prompt(counts)
        assert "11–13 top-level" in out
        assert "7 or fewer" in out
        assert "17 or more" in out
        # Make sure the defaults don't leak through on a custom
        # range — catches the "handler forgot to call the renderer"
        # footgun.
        assert "8–20" not in out
        assert "40 or more" not in out

    def test_no_raw_placeholder_tokens_leak(self) -> None:
        counts = ProjectSettings().top_level_responsibilities
        out = render_system_prompt(counts)
        for token in ("{{FLOOR}}", "{{TYPICAL_MIN}}", "{{TYPICAL_MAX}}", "{{CEILING}}"):
            assert token not in out

    def test_is_nonempty_str(self) -> None:
        out = render_system_prompt(ProjectSettings().top_level_responsibilities)
        assert isinstance(out, str)
        assert len(out) > 500  # Whole thing, not just the granularity bullet.
        assert "<requirements>" in out


class TestRenderUserPromptInputDoc:
    """The ``input_doc`` kwarg feeds the project input document into
    the user prompt as a leading section. The handler passes it
    only on the initial bootstrap call; the prompt function honors
    whatever it's given and omits the section when empty."""

    def _kwargs(self, **overrides: object) -> dict:
        base = {
            "features_summary": "- `feat_abc12345` **Widget**: Does widget things.",
            "prior_approved": None,
            "prior_pending": None,
            "feedback": None,
        }
        base.update(overrides)
        return base

    def test_input_doc_renders_when_supplied(self) -> None:
        out = render_user_prompt(**self._kwargs(input_doc="A widget tracker for hobbyists."))
        assert "# Project input document" in out
        assert "A widget tracker for hobbyists." in out
        # Section must lead the features block so the LLM reads the
        # framing before the derived data.
        doc_idx = out.index("# Project input document")
        feat_idx = out.index("# Project features")
        assert doc_idx < feat_idx

    def test_input_doc_omitted_when_empty(self) -> None:
        out = render_user_prompt(**self._kwargs(input_doc=""))
        assert "# Project input document" not in out

    def test_input_doc_omitted_when_whitespace_only(self) -> None:
        out = render_user_prompt(**self._kwargs(input_doc="   \n  \n"))
        assert "# Project input document" not in out

    def test_default_omits_input_doc(self) -> None:
        # No explicit input_doc kwarg — default "" — section stays off.
        out = render_user_prompt(**self._kwargs())
        assert "# Project input document" not in out
