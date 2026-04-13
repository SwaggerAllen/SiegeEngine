"""Tests for backend.graph.parsers.validators.validate_requirements."""

from __future__ import annotations

import pytest

from backend.graph.parsers.validators import (
    Responsibility,
    ValidationError,
    validate_requirements,
)
from backend.graph.parsers.xml_sections import TagNode, extract_tag_tree


def _parse(raw: str) -> TagNode:
    return extract_tag_tree(raw, "requirements")


class TestValidateRequirementsHappyPath:
    def test_single_responsibility(self):
        tree = _parse(
            "<requirements>"
            "<responsibility>"
            "<name>User Authentication</name>"
            "<intent>Establish the identity of a caller and make it "
            "available to downstream logic.</intent>"
            "</responsibility>"
            "</requirements>"
        )
        resps = validate_requirements(tree)
        assert resps == [
            Responsibility(
                name="User Authentication",
                intent=(
                    "Establish the identity of a caller and make it available to downstream logic."
                ),
            )
        ]

    def test_multiple_preserve_order(self):
        tree = _parse(
            "<requirements>"
            "<responsibility><name>Auth</name><intent>Identify callers.</intent></responsibility>"
            "<responsibility><name>Billing</name><intent>Bill accounts.</intent></responsibility>"
            "<responsibility><name>Telemetry</name><intent>Record usage.</intent></responsibility>"
            "</requirements>"
        )
        resps = validate_requirements(tree)
        assert [r.name for r in resps] == ["Auth", "Billing", "Telemetry"]

    def test_multi_sentence_intent_preserved(self):
        tree = _parse(
            "<requirements>"
            "<responsibility>"
            "<name>Telemetry</name>"
            "<intent>Record every LLM call. Flag latency spikes. Retain for 30 days.</intent>"
            "</responsibility>"
            "</requirements>"
        )
        resps = validate_requirements(tree)
        assert resps[0].intent == "Record every LLM call. Flag latency spikes. Retain for 30 days."


class TestValidateRequirementsRootLevel:
    def test_wrong_root_tag_rejected(self):
        # Construct a TagNode directly with the wrong root tag so
        # we test validator behavior in isolation from the parser.
        tree = TagNode(
            tag="features",
            text="",
            children=[],
        )
        with pytest.raises(ValidationError, match="Expected root tag <requirements>"):
            validate_requirements(tree)

    def test_unknown_child_rejected(self):
        tree = _parse(
            "<requirements>"
            "<responsibility><name>Auth</name><intent>Ok.</intent></responsibility>"
            "<widget>nope</widget>"
            "</requirements>"
        )
        with pytest.raises(ValidationError, match="unexpected child <widget>"):
            validate_requirements(tree)

    def test_empty_rejected(self):
        tree = _parse("<requirements></requirements>")
        with pytest.raises(ValidationError, match="no <responsibility>"):
            validate_requirements(tree)


class TestValidateResponsibilityStructure:
    def test_missing_name_rejected(self):
        tree = _parse(
            "<requirements>"
            "<responsibility><intent>No name here.</intent></responsibility>"
            "</requirements>"
        )
        with pytest.raises(ValidationError, match="missing a <name>"):
            validate_requirements(tree)

    def test_missing_intent_rejected(self):
        tree = _parse(
            "<requirements><responsibility><name>Auth</name></responsibility></requirements>"
        )
        with pytest.raises(ValidationError, match="missing an <intent>"):
            validate_requirements(tree)

    def test_multiple_names_rejected(self):
        tree = _parse(
            "<requirements>"
            "<responsibility>"
            "<name>Auth</name><name>Auth2</name>"
            "<intent>Ok.</intent>"
            "</responsibility>"
            "</requirements>"
        )
        with pytest.raises(ValidationError, match="2 <name> children"):
            validate_requirements(tree)

    def test_multiple_intents_rejected(self):
        tree = _parse(
            "<requirements>"
            "<responsibility>"
            "<name>Auth</name>"
            "<intent>First.</intent><intent>Second.</intent>"
            "</responsibility>"
            "</requirements>"
        )
        with pytest.raises(ValidationError, match="2 <intent> children"):
            validate_requirements(tree)

    def test_empty_name_rejected(self):
        tree = _parse(
            "<requirements>"
            "<responsibility><name> </name><intent>Ok.</intent></responsibility>"
            "</requirements>"
        )
        with pytest.raises(ValidationError, match="empty <name>"):
            validate_requirements(tree)

    def test_empty_intent_rejected(self):
        tree = _parse(
            "<requirements>"
            "<responsibility><name>Auth</name><intent> </intent></responsibility>"
            "</requirements>"
        )
        with pytest.raises(ValidationError, match="empty <intent>"):
            validate_requirements(tree)

    def test_unknown_child_in_responsibility_rejected(self):
        tree = _parse(
            "<requirements>"
            "<responsibility>"
            "<name>Auth</name>"
            "<intent>Ok.</intent>"
            "<rationale>should not be here</rationale>"
            "</responsibility>"
            "</requirements>"
        )
        with pytest.raises(ValidationError, match="unexpected child <rationale>"):
            validate_requirements(tree)
