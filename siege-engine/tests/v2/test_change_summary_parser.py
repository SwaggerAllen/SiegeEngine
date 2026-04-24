"""Unit tests for :func:`backend.graph.parsers.change_summary.extract_change_summary`."""

from __future__ import annotations

from backend.graph.parsers.change_summary import extract_change_summary


class TestExtractChangeSummary:
    def test_happy_path_lifts_body_and_strips_tag(self) -> None:
        raw = (
            "<introduction>Stub intro.</introduction>"
            "<change-summary>Split Auth into five atoms.</change-summary>"
            "<requirements><responsibility><name>x</name><feats/></responsibility></requirements>"
        )
        summary, stripped = extract_change_summary(raw)
        assert summary == "Split Auth into five atoms."
        assert "<change-summary>" not in stripped
        assert "<introduction>" in stripped
        assert "<requirements>" in stripped

    def test_missing_tag_returns_raw_unchanged(self) -> None:
        raw = (
            "<introduction>Stub.</introduction>"
            "<requirements><responsibility><name>x</name><feats/></responsibility></requirements>"
        )
        summary, stripped = extract_change_summary(raw)
        assert summary == ""
        # Only whitespace-trimmed, otherwise identical.
        assert stripped.strip() == raw.strip()

    def test_empty_tag_returns_empty_summary(self) -> None:
        raw = (
            "<introduction>x</introduction>"
            "<change-summary>   </change-summary>"
            "<requirements></requirements>"
        )
        summary, stripped = extract_change_summary(raw)
        assert summary == ""
        assert "<change-summary>" not in stripped

    def test_multiple_tags_keeps_first_body_and_strips_all(self) -> None:
        raw = (
            "<introduction>x</introduction>"
            "<change-summary>First summary.</change-summary>"
            "<requirements></requirements>"
            "<change-summary>Second summary.</change-summary>"
        )
        summary, stripped = extract_change_summary(raw)
        assert summary == "First summary."
        assert "<change-summary>" not in stripped
        assert "Second summary." not in stripped

    def test_attributes_on_opening_tag_tolerated(self) -> None:
        raw = (
            "<introduction>x</introduction>"
            '<change-summary version="1">Body.</change-summary>'
            "<requirements></requirements>"
        )
        summary, stripped = extract_change_summary(raw)
        assert summary == "Body."
        assert "<change-summary" not in stripped

    def test_case_insensitive_tag_name(self) -> None:
        raw = (
            "<introduction>x</introduction>"
            "<Change-Summary>Mixed case.</Change-Summary>"
            "<requirements></requirements>"
        )
        summary, stripped = extract_change_summary(raw)
        assert summary == "Mixed case."
        assert "Change-Summary" not in stripped

    def test_multiline_body_preserved(self) -> None:
        raw = (
            "<change-summary>Line one.\n\n"
            "Line two continues the summary.</change-summary>"
            "<requirements></requirements>"
        )
        summary, _ = extract_change_summary(raw)
        assert "Line one." in summary
        assert "Line two" in summary

    def test_empty_input_returns_empty_tuple(self) -> None:
        summary, stripped = extract_change_summary("")
        assert summary == ""
        assert stripped == ""

    def test_whitespace_between_paragraphs_collapsed_after_strip(self) -> None:
        """Stripping a tag from between paragraphs shouldn't leave
        triple-blank-line gaps in the stored content."""
        raw = (
            "<introduction>Para one.</introduction>\n\n\n"
            "<change-summary>Lifted out.</change-summary>\n\n\n"
            "<requirements>Para three.</requirements>"
        )
        _, stripped = extract_change_summary(raw)
        assert "\n\n\n" not in stripped
