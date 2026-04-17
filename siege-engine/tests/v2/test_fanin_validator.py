"""Tests for backend.graph.parsers.validators.validate_fanin (Phase 7).

Grammar coverage:
- required root <fanin>
- required children <summary> / <exposed-surface> / <realized-behavior>
- fixed order enforcement
- unknown-child rejection
- duplicate-child rejection
- empty-section rejection
- raw_content passthrough
"""

from __future__ import annotations

import pytest

from backend.graph.parsers.validators import (
    FanInEntry,
    ValidationError,
    parse_and_validate_fanin,
    validate_fanin,
)
from backend.graph.parsers.xml_sections import extract_tag_tree

_BARE = (
    "<fanin>"
    "<summary>S body.</summary>"
    "<exposed-surface>E body.</exposed-surface>"
    "<realized-behavior>R body.</realized-behavior>"
    "</fanin>"
)


def _parse(raw: str):
    return extract_tag_tree(raw, "fanin")


class TestHappyPath:
    def test_returns_populated_entry(self):
        entry = parse_and_validate_fanin(_BARE)
        assert isinstance(entry, FanInEntry)
        assert entry.summary == "S body."
        assert entry.exposed_surface == "E body."
        assert entry.realized_behavior == "R body."

    def test_raw_content_roundtrips(self):
        entry = parse_and_validate_fanin(_BARE)
        assert entry.raw_content == _BARE

    def test_multiline_prose_preserved(self):
        raw = (
            "<fanin>"
            "<summary>Line one.\n\nLine two.</summary>"
            "<exposed-surface>E</exposed-surface>"
            "<realized-behavior>R</realized-behavior>"
            "</fanin>"
        )
        entry = parse_and_validate_fanin(raw)
        assert "Line one." in entry.summary
        assert "Line two." in entry.summary


class TestRootTag:
    def test_wrong_root_rejected(self):
        # extract_tag_tree enforces the outer tag match; forge the
        # rejection by calling the validator with a hand-rolled tree.
        tree = _parse(_BARE)
        # Forge a mismatch by mutating the tag name.
        object.__setattr__(tree, "tag", "implementation")
        with pytest.raises(ValidationError, match="Expected root tag <fanin>"):
            validate_fanin(tree, raw_content="")


class TestRequiredChildren:
    def test_missing_summary(self):
        raw = (
            "<fanin>"
            "<exposed-surface>E</exposed-surface>"
            "<realized-behavior>R</realized-behavior>"
            "</fanin>"
        )
        with pytest.raises(ValidationError, match="missing the required <summary>"):
            parse_and_validate_fanin(raw)

    def test_missing_exposed_surface(self):
        raw = "<fanin><summary>S</summary><realized-behavior>R</realized-behavior></fanin>"
        with pytest.raises(ValidationError, match="missing the required <exposed-surface>"):
            parse_and_validate_fanin(raw)

    def test_missing_realized_behavior(self):
        raw = "<fanin><summary>S</summary><exposed-surface>E</exposed-surface></fanin>"
        with pytest.raises(ValidationError, match="missing the required <realized-behavior>"):
            parse_and_validate_fanin(raw)


class TestUnknownChildren:
    def test_unknown_child_rejected(self):
        raw = (
            "<fanin>"
            "<summary>S</summary>"
            "<exposed-surface>E</exposed-surface>"
            "<realized-behavior>R</realized-behavior>"
            "<policies>bogus</policies>"
            "</fanin>"
        )
        with pytest.raises(ValidationError, match="unexpected child <policies>"):
            parse_and_validate_fanin(raw)


class TestDuplicateChildren:
    def test_duplicate_summary_rejected(self):
        raw = (
            "<fanin>"
            "<summary>A</summary>"
            "<summary>B</summary>"
            "<exposed-surface>E</exposed-surface>"
            "<realized-behavior>R</realized-behavior>"
            "</fanin>"
        )
        with pytest.raises(ValidationError, match="more than one <summary>"):
            parse_and_validate_fanin(raw)

    def test_duplicate_realized_behavior_rejected(self):
        raw = (
            "<fanin>"
            "<summary>S</summary>"
            "<exposed-surface>E</exposed-surface>"
            "<realized-behavior>A</realized-behavior>"
            "<realized-behavior>B</realized-behavior>"
            "</fanin>"
        )
        with pytest.raises(ValidationError, match="more than one <realized-behavior>"):
            parse_and_validate_fanin(raw)


class TestOrdering:
    def test_out_of_order_rejected(self):
        raw = (
            "<fanin>"
            "<exposed-surface>E</exposed-surface>"
            "<summary>S</summary>"
            "<realized-behavior>R</realized-behavior>"
            "</fanin>"
        )
        with pytest.raises(ValidationError, match="not in the required order"):
            parse_and_validate_fanin(raw)

    def test_swapped_tail_rejected(self):
        raw = (
            "<fanin>"
            "<summary>S</summary>"
            "<realized-behavior>R</realized-behavior>"
            "<exposed-surface>E</exposed-surface>"
            "</fanin>"
        )
        with pytest.raises(ValidationError, match="not in the required order"):
            parse_and_validate_fanin(raw)


class TestEmptySections:
    def test_empty_summary_rejected(self):
        raw = (
            "<fanin>"
            "<summary>   </summary>"
            "<exposed-surface>E</exposed-surface>"
            "<realized-behavior>R</realized-behavior>"
            "</fanin>"
        )
        with pytest.raises(ValidationError, match="<summary> is empty"):
            parse_and_validate_fanin(raw)

    def test_empty_exposed_surface_rejected(self):
        raw = (
            "<fanin>"
            "<summary>S</summary>"
            "<exposed-surface></exposed-surface>"
            "<realized-behavior>R</realized-behavior>"
            "</fanin>"
        )
        with pytest.raises(ValidationError, match="<exposed-surface> is empty"):
            parse_and_validate_fanin(raw)
