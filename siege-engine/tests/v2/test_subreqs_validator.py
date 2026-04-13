"""Tests for backend.graph.parsers.validators.validate_subrequirements."""

from __future__ import annotations

import pytest

from backend.graph.parsers.validators import (
    ValidationError,
    validate_subrequirements,
)
from backend.graph.parsers.xml_sections import TagNode, extract_tag_tree


def _parse(raw: str) -> TagNode:
    return extract_tag_tree(raw, "subrequirements")


def _derived(*resp_ids: str) -> str:
    return "<derived-from>" + "".join(f'<resp id="{rid}"/>' for rid in resp_ids) + "</derived-from>"


# Known parent resps for the typical happy-path tests. Two top-
# level resps is enough to exercise coverage + leak checks.
KNOWN_PARENTS = {"resp_parent001", "resp_parent002"}


class TestHappyPath:
    def test_single_subresp(self):
        tree = _parse(
            "<subrequirements>"
            "<subresponsibility>"
            "<name>Card Tokenization</name>"
            "<intent>Convert raw cards to opaque tokens at entry.</intent>"
            + _derived("resp_parent001", "resp_parent002")
            + "</subresponsibility>"
            "</subrequirements>"
        )
        subresps = validate_subrequirements(tree, known_parent_resp_ids=KNOWN_PARENTS)
        assert len(subresps) == 1
        assert subresps[0].name == "Card Tokenization"
        assert set(subresps[0].derived_from) == KNOWN_PARENTS

    def test_multiple_preserve_order(self):
        tree = _parse(
            "<subrequirements>"
            "<subresponsibility>"
            "<name>A</name><intent>First.</intent>"
            + _derived("resp_parent001")
            + "</subresponsibility>"
            "<subresponsibility>"
            "<name>B</name><intent>Second.</intent>"
            + _derived("resp_parent002")
            + "</subresponsibility>"
            "</subrequirements>"
        )
        subresps = validate_subrequirements(tree, known_parent_resp_ids=KNOWN_PARENTS)
        assert [s.name for s in subresps] == ["A", "B"]

    def test_many_to_many_parent_shared_across_subresps(self):
        tree = _parse(
            "<subrequirements>"
            "<subresponsibility>"
            "<name>Retry Scheduling</name>"
            "<intent>Retries for payments.</intent>"
            + _derived("resp_parent001", "resp_parent002")
            + "</subresponsibility>"
            "<subresponsibility>"
            "<name>Backoff</name>"
            "<intent>Exponential backoff for retry.</intent>"
            + _derived("resp_parent001")
            + "</subresponsibility>"
            "</subrequirements>"
        )
        subresps = validate_subrequirements(tree, known_parent_resp_ids=KNOWN_PARENTS)
        # parent001 appears in both subresps — fine
        assert "resp_parent001" in subresps[0].derived_from
        assert "resp_parent001" in subresps[1].derived_from


class TestRootLevel:
    def test_wrong_root_rejected(self):
        tree = TagNode(tag="requirements", text="", children=[])
        with pytest.raises(ValidationError, match="Expected root tag <subrequirements>"):
            validate_subrequirements(tree, known_parent_resp_ids=set())

    def test_unknown_child_rejected(self):
        tree = _parse(
            "<subrequirements>"
            "<subresponsibility><name>A</name><intent>Ok.</intent>"
            + _derived("resp_parent001", "resp_parent002")
            + "</subresponsibility>"
            "<widget>nope</widget>"
            "</subrequirements>"
        )
        with pytest.raises(ValidationError, match="unexpected child <widget>"):
            validate_subrequirements(tree, known_parent_resp_ids=KNOWN_PARENTS)

    def test_empty_rejected(self):
        tree = _parse("<subrequirements></subrequirements>")
        with pytest.raises(ValidationError, match="no <subresponsibility>"):
            validate_subrequirements(tree, known_parent_resp_ids=set())


class TestSubrespStructure:
    def test_missing_name_rejected(self):
        tree = _parse(
            "<subrequirements>"
            "<subresponsibility><intent>No name.</intent>"
            + _derived("resp_parent001", "resp_parent002")
            + "</subresponsibility>"
            "</subrequirements>"
        )
        with pytest.raises(ValidationError, match="missing a <name>"):
            validate_subrequirements(tree, known_parent_resp_ids=KNOWN_PARENTS)

    def test_missing_intent_rejected(self):
        tree = _parse(
            "<subrequirements>"
            "<subresponsibility><name>A</name>"
            + _derived("resp_parent001", "resp_parent002")
            + "</subresponsibility>"
            "</subrequirements>"
        )
        with pytest.raises(ValidationError, match="missing an <intent>"):
            validate_subrequirements(tree, known_parent_resp_ids=KNOWN_PARENTS)

    def test_missing_derived_from_rejected(self):
        tree = _parse(
            "<subrequirements>"
            "<subresponsibility><name>A</name><intent>Ok.</intent></subresponsibility>"
            "</subrequirements>"
        )
        with pytest.raises(ValidationError, match="missing a <derived-from>"):
            validate_subrequirements(tree, known_parent_resp_ids=KNOWN_PARENTS)

    def test_empty_name_rejected(self):
        tree = _parse(
            "<subrequirements>"
            "<subresponsibility><name> </name><intent>Ok.</intent>"
            + _derived("resp_parent001", "resp_parent002")
            + "</subresponsibility>"
            "</subrequirements>"
        )
        with pytest.raises(ValidationError, match="empty <name>"):
            validate_subrequirements(tree, known_parent_resp_ids=KNOWN_PARENTS)


class TestDerivedFromValidation:
    def test_empty_derived_from_rejected(self):
        tree = _parse(
            "<subrequirements>"
            "<subresponsibility><name>A</name><intent>Ok.</intent>"
            "<derived-from></derived-from>"
            "</subresponsibility>"
            "</subrequirements>"
        )
        with pytest.raises(ValidationError, match="empty <derived-from>"):
            validate_subrequirements(tree, known_parent_resp_ids=KNOWN_PARENTS)

    def test_derived_from_unknown_tag_rejected(self):
        tree = _parse(
            "<subrequirements>"
            "<subresponsibility><name>A</name><intent>Ok.</intent>"
            '<derived-from><resp id="resp_parent001"/><widget/></derived-from>'
            "</subresponsibility>"
            "</subrequirements>"
        )
        with pytest.raises(ValidationError, match="unexpected.*<widget>"):
            validate_subrequirements(tree, known_parent_resp_ids=KNOWN_PARENTS)

    def test_resp_missing_id_rejected(self):
        tree = _parse(
            "<subrequirements>"
            "<subresponsibility><name>A</name><intent>Ok.</intent>"
            "<derived-from><resp/></derived-from>"
            "</subresponsibility>"
            "</subrequirements>"
        )
        with pytest.raises(ValidationError, match="no id attribute"):
            validate_subrequirements(tree, known_parent_resp_ids=KNOWN_PARENTS)

    def test_duplicate_resp_in_same_block_rejected(self):
        tree = _parse(
            "<subrequirements>"
            "<subresponsibility><name>A</name><intent>Ok.</intent>"
            + _derived("resp_parent001", "resp_parent001")
            + "</subresponsibility>"
            "</subrequirements>"
        )
        with pytest.raises(ValidationError, match="duplicate id"):
            validate_subrequirements(tree, known_parent_resp_ids=KNOWN_PARENTS)

    def test_cross_component_leak_rejected(self):
        # Reference a resp that isn't assigned to this component.
        tree = _parse(
            "<subrequirements>"
            "<subresponsibility><name>A</name><intent>Ok.</intent>"
            + _derived("resp_strange01")
            + "</subresponsibility>"
            "</subrequirements>"
        )
        with pytest.raises(ValidationError, match="Cross-component leaks are forbidden"):
            validate_subrequirements(tree, known_parent_resp_ids=KNOWN_PARENTS)


class TestCoverage:
    def test_uncovered_parent_rejected(self):
        # Only covers parent001, parent002 is uncovered.
        tree = _parse(
            "<subrequirements>"
            "<subresponsibility><name>A</name><intent>Ok.</intent>"
            + _derived("resp_parent001")
            + "</subresponsibility>"
            "</subrequirements>"
        )
        with pytest.raises(ValidationError, match="does not cover every parent"):
            validate_subrequirements(tree, known_parent_resp_ids=KNOWN_PARENTS)

    def test_union_coverage_accepted(self):
        # Two subresps together cover both parent resps.
        tree = _parse(
            "<subrequirements>"
            "<subresponsibility><name>A</name><intent>Ok.</intent>"
            + _derived("resp_parent001")
            + "</subresponsibility>"
            "<subresponsibility><name>B</name><intent>Ok.</intent>"
            + _derived("resp_parent002")
            + "</subresponsibility>"
            "</subrequirements>"
        )
        subresps = validate_subrequirements(tree, known_parent_resp_ids=KNOWN_PARENTS)
        assert len(subresps) == 2
