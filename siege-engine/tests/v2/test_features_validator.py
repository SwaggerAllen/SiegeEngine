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


class TestValidateFeaturesImplicit:
    def test_implicit_marker_sets_flag(self):
        tree = _parse(
            "<features>"
            "<feature>"
            "<name>Password Reset</name>"
            "<intent>Users can reset their password via email.</intent>"
            "<implicit/>"
            "</feature>"
            "</features>"
        )
        features = validate_features(tree)
        assert len(features) == 1
        assert features[0].is_implicit is True

    def test_no_implicit_marker_defaults_to_false(self):
        tree = _parse(
            "<features><feature><name>Billing</name><intent>Pay.</intent></feature></features>"
        )
        features = validate_features(tree)
        assert features[0].is_implicit is False

    def test_duplicate_implicit_marker_rejected(self):
        tree = _parse(
            "<features>"
            "<feature>"
            "<name>Billing</name>"
            "<intent>Pay.</intent>"
            "<implicit/>"
            "<implicit/>"
            "</feature>"
            "</features>"
        )
        with pytest.raises(ValidationError, match="2 <implicit/> markers"):
            validate_features(tree)

    def test_mixed_explicit_and_implicit_in_same_list(self):
        tree = _parse(
            "<features>"
            "<feature>"
            "<name>Billing</name>"
            "<intent>Users pay.</intent>"
            "</feature>"
            "<feature>"
            "<name>Password Reset</name>"
            "<intent>Inferred need.</intent>"
            "<implicit/>"
            "</feature>"
            "</features>"
        )
        features = validate_features(tree)
        assert [f.name for f in features] == ["Billing", "Password Reset"]
        assert [f.is_implicit for f in features] == [False, True]


class TestValidateFeaturesGroups:
    def test_grouped_features(self):
        tree = _parse(
            "<features>"
            "<group>"
            "<name>User Management</name>"
            "<feature><name>Login</name><intent>Sign in.</intent></feature>"
            "<feature>"
            "<name>Password Reset</name>"
            "<intent>Reset via email.</intent>"
            "<implicit/>"
            "</feature>"
            "</group>"
            "</features>"
        )
        features = validate_features(tree)
        assert len(features) == 2
        assert features[0].name == "Login"
        assert features[0].group_label == "User Management"
        assert features[0].is_implicit is False
        assert features[1].name == "Password Reset"
        assert features[1].group_label == "User Management"
        assert features[1].is_implicit is True

    def test_mixed_grouped_and_ungrouped_in_document_order(self):
        tree = _parse(
            "<features>"
            "<group>"
            "<name>User Management</name>"
            "<feature><name>Login</name><intent>Sign in.</intent></feature>"
            "</group>"
            "<feature><name>Search</name><intent>Global search.</intent></feature>"
            "<group>"
            "<name>Content</name>"
            "<feature><name>Posting</name><intent>Create posts.</intent></feature>"
            "</group>"
            "</features>"
        )
        features = validate_features(tree)
        assert [f.name for f in features] == ["Login", "Search", "Posting"]
        assert [f.group_label for f in features] == [
            "User Management",
            None,
            "Content",
        ]

    def test_multiple_groups(self):
        tree = _parse(
            "<features>"
            "<group>"
            "<name>A</name>"
            "<feature><name>One</name><intent>alpha one.</intent></feature>"
            "<feature><name>Two</name><intent>alpha two.</intent></feature>"
            "</group>"
            "<group>"
            "<name>B</name>"
            "<feature><name>Three</name><intent>beta three.</intent></feature>"
            "</group>"
            "</features>"
        )
        features = validate_features(tree)
        assert len(features) == 3
        assert [f.group_label for f in features] == ["A", "A", "B"]

    def test_group_without_name_rejected(self):
        tree = _parse(
            "<features>"
            "<group>"
            "<feature><name>X</name><intent>x.</intent></feature>"
            "</group>"
            "</features>"
        )
        with pytest.raises(ValidationError, match="<group> is missing a <name>"):
            validate_features(tree)

    def test_group_with_empty_name_rejected(self):
        tree = _parse(
            "<features>"
            "<group>"
            "<name>   </name>"
            "<feature><name>X</name><intent>x.</intent></feature>"
            "</group>"
            "</features>"
        )
        with pytest.raises(ValidationError, match="empty <name>"):
            validate_features(tree)

    def test_group_without_features_rejected(self):
        tree = _parse("<features><group><name>Empty Group</name></group></features>")
        with pytest.raises(ValidationError, match='"Empty Group" contains no <feature>'):
            validate_features(tree)

    def test_nested_groups_rejected(self):
        tree = _parse(
            "<features>"
            "<group>"
            "<name>Outer</name>"
            "<group>"
            "<name>Inner</name>"
            "<feature><name>X</name><intent>x.</intent></feature>"
            "</group>"
            "</group>"
            "</features>"
        )
        with pytest.raises(ValidationError, match="Groups do not nest"):
            validate_features(tree)

    def test_unknown_tag_inside_group_rejected(self):
        tree = _parse(
            "<features>"
            "<group>"
            "<name>A</name>"
            "<rationale>extra</rationale>"
            "<feature><name>X</name><intent>x.</intent></feature>"
            "</group>"
            "</features>"
        )
        with pytest.raises(ValidationError, match="unexpected child <rationale>"):
            validate_features(tree)

    def test_ungrouped_only_still_works(self):
        # Backward compat: a flat <features> block with no <group>
        # tags must still validate successfully (all features get
        # group_label=None).
        tree = _parse(
            "<features>"
            "<feature><name>Billing</name><intent>Pay.</intent></feature>"
            "<feature><name>Auth</name><intent>Sign in.</intent></feature>"
            "</features>"
        )
        features = validate_features(tree)
        assert len(features) == 2
        assert all(f.group_label is None for f in features)
        assert all(f.is_implicit is False for f in features)
