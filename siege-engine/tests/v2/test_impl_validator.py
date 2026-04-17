"""Tests for ``validate_implementation`` (Phase 8).

Enforces the ``<implementation>`` grammar: required
``<behavior>`` / ``<invariants>`` / ``<sequencing>`` /
``<edge-cases>`` in fixed order, each non-empty prose.
"""

from __future__ import annotations

import pytest

from backend.graph.parsers.validators import (
    ImplementationEntry,
    ValidationError,
    parse_and_validate_implementation,
    validate_implementation,
)
from backend.graph.parsers.xml_sections import ParseError, extract_tag_tree


def _parse(raw: str):
    return extract_tag_tree(raw, "implementation")


_VALID = (
    "<implementation>"
    "<behavior>Does the thing on every call.</behavior>"
    "<invariants>Input validated; state consistent.</invariants>"
    "<sequencing>Idempotent except for state mutation.</sequencing>"
    "<edge-cases>Empty input returns None.</edge-cases>"
    "</implementation>"
)


class TestValidImpl:
    def test_minimal(self):
        entry = validate_implementation(_parse(_VALID), raw_content=_VALID)
        assert isinstance(entry, ImplementationEntry)
        assert entry.behavior == "Does the thing on every call."
        assert entry.invariants == "Input validated; state consistent."
        assert entry.sequencing == "Idempotent except for state mutation."
        assert entry.edge_cases == "Empty input returns None."
        assert entry.raw_content == _VALID

    def test_parse_and_validate_end_to_end(self):
        entry = parse_and_validate_implementation(_VALID)
        assert entry.behavior.startswith("Does the thing")

    def test_body_with_nested_markup_flattened(self):
        raw = (
            "<implementation>"
            "<behavior>Runs <em>every</em> call.</behavior>"
            "<invariants>Inv.</invariants>"
            "<sequencing>Seq.</sequencing>"
            "<edge-cases>Edge.</edge-cases>"
            "</implementation>"
        )
        entry = validate_implementation(_parse(raw), raw_content=raw)
        # Nested markup flattens to text; "every" must appear somewhere.
        assert "every" in entry.behavior


class TestStructuralErrors:
    def test_wrong_root_rejected(self):
        raw = "<impl><behavior>x</behavior></impl>"
        with pytest.raises(ParseError):
            parse_and_validate_implementation(raw)

    def test_missing_behavior(self):
        raw = (
            "<implementation>"
            "<invariants>I</invariants>"
            "<sequencing>S</sequencing>"
            "<edge-cases>E</edge-cases>"
            "</implementation>"
        )
        with pytest.raises(ValidationError, match="missing the required <behavior>"):
            validate_implementation(_parse(raw), raw_content=raw)

    def test_missing_invariants(self):
        raw = (
            "<implementation>"
            "<behavior>B</behavior>"
            "<sequencing>S</sequencing>"
            "<edge-cases>E</edge-cases>"
            "</implementation>"
        )
        with pytest.raises(ValidationError, match="missing the required <invariants>"):
            validate_implementation(_parse(raw), raw_content=raw)

    def test_missing_sequencing(self):
        raw = (
            "<implementation>"
            "<behavior>B</behavior>"
            "<invariants>I</invariants>"
            "<edge-cases>E</edge-cases>"
            "</implementation>"
        )
        with pytest.raises(ValidationError, match="missing the required <sequencing>"):
            validate_implementation(_parse(raw), raw_content=raw)

    def test_missing_edge_cases(self):
        raw = (
            "<implementation>"
            "<behavior>B</behavior>"
            "<invariants>I</invariants>"
            "<sequencing>S</sequencing>"
            "</implementation>"
        )
        with pytest.raises(ValidationError, match="missing the required <edge-cases>"):
            validate_implementation(_parse(raw), raw_content=raw)

    def test_duplicate_section_rejected(self):
        raw = (
            "<implementation>"
            "<behavior>B1</behavior>"
            "<behavior>B2</behavior>"
            "<invariants>I</invariants>"
            "<sequencing>S</sequencing>"
            "<edge-cases>E</edge-cases>"
            "</implementation>"
        )
        with pytest.raises(ValidationError, match="more than one <behavior>"):
            validate_implementation(_parse(raw), raw_content=raw)

    def test_out_of_order_rejected(self):
        raw = (
            "<implementation>"
            "<invariants>I</invariants>"
            "<behavior>B</behavior>"
            "<sequencing>S</sequencing>"
            "<edge-cases>E</edge-cases>"
            "</implementation>"
        )
        with pytest.raises(ValidationError, match="not in the required order"):
            validate_implementation(_parse(raw), raw_content=raw)

    def test_empty_behavior_rejected(self):
        raw = (
            "<implementation>"
            "<behavior>   </behavior>"
            "<invariants>I</invariants>"
            "<sequencing>S</sequencing>"
            "<edge-cases>E</edge-cases>"
            "</implementation>"
        )
        with pytest.raises(ValidationError, match="<behavior> is empty"):
            validate_implementation(_parse(raw), raw_content=raw)

    def test_unknown_child_rejected(self):
        raw = (
            "<implementation>"
            "<behavior>B</behavior>"
            "<invariants>I</invariants>"
            "<sequencing>S</sequencing>"
            "<edge-cases>E</edge-cases>"
            "<unknown>X</unknown>"
            "</implementation>"
        )
        with pytest.raises(ValidationError, match="unexpected child <unknown>"):
            validate_implementation(_parse(raw), raw_content=raw)

    def test_wrong_root_via_validate(self):
        tree = extract_tag_tree("<other><behavior>B</behavior></other>", "other")
        with pytest.raises(ValidationError, match="Expected root tag <implementation>"):
            validate_implementation(tree, raw_content="<other/>")
