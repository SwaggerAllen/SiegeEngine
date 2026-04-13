"""Tests for backend.graph.parsers.validators.validate_features."""

from __future__ import annotations

import pytest

from backend.graph.parsers.validators import (
    Feature,
    ValidationError,
    validate_features,
)
from backend.graph.parsers.xml_sections import TagNode, extract_tag_tree


def _parse(raw: str) -> TagNode:
    return extract_tag_tree(raw, "features")


class TestValidateFeaturesHappyPath:
    def test_single_feature(self):
        tree = _parse(
            "<features>"
            "<feature><name>Billing</name>"
            "<intent>Users pay for service tiers via credit card.</intent>"
            "</feature>"
            "</features>"
        )
        features = validate_features(tree)
        assert features == [
            Feature(name="Billing", intent="Users pay for service tiers via credit card.")
        ]

    def test_multiple_features_preserve_order(self):
        tree = _parse(
            "<features>"
            "<feature><name>Billing</name><intent>Pay.</intent></feature>"
            "<feature><name>Auth</name><intent>Sign in.</intent></feature>"
            "<feature><name>Reporting</name><intent>See stats.</intent></feature>"
            "</features>"
        )
        features = validate_features(tree)
        assert [f.name for f in features] == ["Billing", "Auth", "Reporting"]
        assert [f.intent for f in features] == ["Pay.", "Sign in.", "See stats."]

    def test_paragraph_intent_preserved(self):
        tree = _parse(
            "<features>"
            "<feature>"
            "<name>Billing</name>"
            "<intent>First sentence. Second sentence. Third sentence.</intent>"
            "</feature>"
            "</features>"
        )
        features = validate_features(tree)
        assert features[0].intent == "First sentence. Second sentence. Third sentence."


class TestValidateFeaturesRootLevel:
    def test_wrong_root_tag_rejected(self):
        # Construct a TagNode directly with the wrong root tag.
        tree = TagNode(tag="policies", children=[])
        with pytest.raises(ValidationError, match="Expected root tag <features>"):
            validate_features(tree)

    def test_empty_features_block_rejected(self):
        tree = _parse("<features></features>")
        with pytest.raises(ValidationError, match="contains no <feature> entries"):
            validate_features(tree)

    def test_unknown_child_at_features_level_rejected(self):
        tree = _parse(
            "<features>"
            "<feature><name>A</name><intent>a.</intent></feature>"
            "<policy>must apply everywhere</policy>"
            "</features>"
        )
        with pytest.raises(ValidationError, match="unexpected child <policy>"):
            validate_features(tree)


class TestValidateFeaturesChildLevel:
    def test_missing_name_rejected(self):
        tree = _parse("<features><feature><intent>No name here.</intent></feature></features>")
        with pytest.raises(ValidationError, match="position 0 is missing a <name>"):
            validate_features(tree)

    def test_missing_intent_rejected(self):
        tree = _parse("<features><feature><name>OnlyName</name></feature></features>")
        with pytest.raises(ValidationError, match="position 0 is missing an <intent>"):
            validate_features(tree)

    def test_duplicate_name_rejected(self):
        tree = _parse(
            "<features>"
            "<feature>"
            "<name>First</name>"
            "<name>Second</name>"
            "<intent>body</intent>"
            "</feature>"
            "</features>"
        )
        with pytest.raises(ValidationError, match="2 <name> children"):
            validate_features(tree)

    def test_duplicate_intent_rejected(self):
        tree = _parse(
            "<features>"
            "<feature>"
            "<name>Billing</name>"
            "<intent>one</intent>"
            "<intent>two</intent>"
            "</feature>"
            "</features>"
        )
        with pytest.raises(ValidationError, match="2 <intent> children"):
            validate_features(tree)

    def test_unknown_child_inside_feature_rejected(self):
        tree = _parse(
            "<features>"
            "<feature>"
            "<name>Billing</name>"
            "<intent>body</intent>"
            "<rationale>extra</rationale>"
            "</feature>"
            "</features>"
        )
        with pytest.raises(ValidationError, match="unexpected child <rationale>"):
            validate_features(tree)

    def test_empty_name_rejected(self):
        tree = _parse(
            "<features><feature><name>   </name><intent>body</intent></feature></features>"
        )
        with pytest.raises(ValidationError, match="empty <name>"):
            validate_features(tree)

    def test_empty_intent_rejected(self):
        tree = _parse(
            "<features><feature><name>Billing</name><intent>   </intent></feature></features>"
        )
        with pytest.raises(ValidationError, match="empty <intent>"):
            validate_features(tree)

    def test_error_identifies_feature_index(self):
        tree = _parse(
            "<features>"
            "<feature><name>First</name><intent>ok</intent></feature>"
            "<feature><name>Second</name></feature>"
            "</features>"
        )
        with pytest.raises(ValidationError, match="position 1"):
            validate_features(tree)
