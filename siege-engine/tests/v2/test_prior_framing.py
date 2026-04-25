"""Tests for backend.graph.prompts._prior_framing.

The helpers split a prior-pending tier draft into its
``<introduction>`` block + body and render two prompt sections:
prior framing (the introduction, labeled as superseded historical
commentary) and prior review (the AI critique of the prior draft).
"""

from __future__ import annotations

from backend.graph.prompts._prior_framing import (
    render_prior_framing_section,
    render_prior_review_section,
    split_prior_introduction,
)


class TestSplitPriorIntroduction:
    def test_extracts_introduction_and_returns_body_without_it(self):
        prior = (
            "<introduction>I considered breaking up projection but "
            "kept it cohesive.</introduction>"
            "<sysarch><components/></sysarch>"
        )
        intro, body = split_prior_introduction(prior)
        assert intro == "I considered breaking up projection but kept it cohesive."
        assert body == "<sysarch><components/></sysarch>"

    def test_no_introduction_returns_none_and_full_prior(self):
        prior = "<sysarch><components/></sysarch>"
        intro, body = split_prior_introduction(prior)
        assert intro is None
        assert body == prior

    def test_empty_input_returns_none_and_empty_string(self):
        assert split_prior_introduction("") == (None, "")
        assert split_prior_introduction(None) == (None, "")

    def test_introduction_with_inner_whitespace_is_stripped(self):
        prior = "<introduction>\n   hello\n</introduction><sysarch/>"
        intro, body = split_prior_introduction(prior)
        assert intro == "hello"
        assert body == "<sysarch/>"

    def test_introduction_only_no_body(self):
        prior = "<introduction>just thinking</introduction>"
        intro, body = split_prior_introduction(prior)
        assert intro == "just thinking"
        assert body == ""

    def test_empty_introduction_block_returns_none(self):
        # An empty (or whitespace-only) introduction is not useful
        # historical commentary; return None so the caller skips
        # rendering an empty framing section.
        prior = "<introduction>   </introduction><sysarch/>"
        intro, body = split_prior_introduction(prior)
        assert intro is None
        assert body == "<sysarch/>"

    def test_multiline_introduction_preserved(self):
        prior = "<introduction>Line one.\nLine two.\nLine three.</introduction><sysarch/>"
        intro, _ = split_prior_introduction(prior)
        assert intro == "Line one.\nLine two.\nLine three."


class TestRenderPriorFramingSection:
    def test_returns_lines_with_superseded_header_and_intro(self):
        lines = render_prior_framing_section("My prior framing.")
        # Joined for easy substring checking.
        rendered = "\n".join(lines)
        assert "Prior framing (superseded" in rendered
        assert "My prior framing." in rendered
        # The framing instruction must clearly tell the model not
        # to treat this as live instruction — this is the load-
        # bearing fix for the introduction-bleed-forward bug.
        assert "historical" in rendered.lower()
        assert "not live instruction" in rendered.lower()

    def test_empty_intro_returns_no_lines(self):
        assert render_prior_framing_section(None) == []
        assert render_prior_framing_section("") == []
        assert render_prior_framing_section("   ") == []


class TestRenderPriorReviewSection:
    def test_returns_lines_with_review_and_advisory_framing(self):
        lines = render_prior_review_section("## Handles & structure\nReview body here.")
        rendered = "\n".join(lines)
        assert "AI review of the prior draft" in rendered
        assert "advisory" in rendered.lower()
        assert "Review body here." in rendered
        # User feedback always wins over review.
        assert "prefer the user" in rendered.lower()

    def test_empty_review_returns_no_lines(self):
        assert render_prior_review_section(None) == []
        assert render_prior_review_section("") == []
        assert render_prior_review_section("   \n   ") == []
