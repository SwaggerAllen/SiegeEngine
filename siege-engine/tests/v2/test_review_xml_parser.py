"""Unit tests for the review XML parser + validator."""

from __future__ import annotations

import pytest

from backend.graph.parsers.review_xml import (
    ReviewXMLError,
    parse_review,
)


class TestParseReview:
    def test_valid_two_sections_with_findings(self) -> None:
        raw = (
            "<review>"
            "<handles-structure>"
            '<finding id="h1">Feature names overlap — "Dashboard" and "Reports".</finding>'
            '<finding id="h2">Intent for X is a restated name.</finding>'
            "</handles-structure>"
            "<architectural-decisions>"
            '<finding id="a1">Decomposition axis is split across two concerns.</finding>'
            "</architectural-decisions>"
            "</review>"
        )
        parsed = parse_review(raw)
        assert [f.id for f in parsed.handles_structure] == ["h1", "h2"]
        assert [f.id for f in parsed.architectural_decisions] == ["a1"]
        assert parsed.handles_structure[0].text.startswith("Feature names overlap")

    def test_empty_sections_are_valid(self) -> None:
        raw = (
            "<review>"
            "<handles-structure></handles-structure>"
            "<architectural-decisions></architectural-decisions>"
            "</review>"
        )
        parsed = parse_review(raw)
        assert parsed.handles_structure == ()
        assert parsed.architectural_decisions == ()

    def test_missing_review_root_raises(self) -> None:
        with pytest.raises(ReviewXMLError):
            parse_review("<handles-structure></handles-structure>")

    def test_missing_handles_section_raises(self) -> None:
        raw = "<review><architectural-decisions></architectural-decisions></review>"
        with pytest.raises(ReviewXMLError, match="handles-structure"):
            parse_review(raw)

    def test_missing_arch_section_raises(self) -> None:
        raw = "<review><handles-structure></handles-structure></review>"
        with pytest.raises(ReviewXMLError, match="architectural-decisions"):
            parse_review(raw)

    def test_finding_without_id_raises(self) -> None:
        raw = (
            "<review>"
            "<handles-structure><finding>no id here</finding></handles-structure>"
            "<architectural-decisions></architectural-decisions>"
            "</review>"
        )
        with pytest.raises(ReviewXMLError, match="missing required id"):
            parse_review(raw)

    def test_finding_with_empty_body_raises(self) -> None:
        raw = (
            "<review>"
            '<handles-structure><finding id="h1">  </finding></handles-structure>'
            "<architectural-decisions></architectural-decisions>"
            "</review>"
        )
        with pytest.raises(ReviewXMLError, match="empty body"):
            parse_review(raw)

    def test_duplicate_ids_raise(self) -> None:
        raw = (
            "<review>"
            '<handles-structure><finding id="h1">A</finding></handles-structure>'
            '<architectural-decisions><finding id="h1">B</finding></architectural-decisions>'
            "</review>"
        )
        with pytest.raises(ReviewXMLError, match="duplicate finding id"):
            parse_review(raw)

    def test_tolerates_preamble_and_postamble(self) -> None:
        """Lenient wrapper: prose around the ``<review>`` block is ignored."""
        raw = (
            "Sure, here's the review:\n\n"
            "<review>"
            '<handles-structure><finding id="h1">ok</finding></handles-structure>'
            "<architectural-decisions></architectural-decisions>"
            "</review>\n\n"
            "Let me know if you want me to expand."
        )
        parsed = parse_review(raw)
        assert len(parsed.handles_structure) == 1
        assert parsed.handles_structure[0].text == "ok"
