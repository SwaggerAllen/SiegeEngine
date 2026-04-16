"""Tests for ``backend.graph.prompts.requirements`` prompt rendering."""

from __future__ import annotations

from backend.graph.prompts.requirements import render_system_prompt, render_user_prompt


class TestRenderSystemPrompt:
    def test_is_nonempty_str(self) -> None:
        out = render_system_prompt()
        assert isinstance(out, str)
        assert len(out) > 500
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
        out = render_user_prompt(**self._kwargs())
        assert "# Project input document" not in out
