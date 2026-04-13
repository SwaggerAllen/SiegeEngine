"""Tests for backend.graph.parsers.xml_sections."""

from __future__ import annotations

import pytest

from backend.graph.parsers.xml_sections import (
    ParseError,
    TagNode,
    extract_tag_tree,
)


class TestExtractTagTreeHappyPath:
    def test_simple_root(self):
        tree = extract_tag_tree("<features></features>", "features")
        assert tree.tag == "features"
        assert tree.text == ""
        assert tree.children == []

    def test_root_with_text_content(self):
        tree = extract_tag_tree(
            "<name>Billing</name>",
            "name",
        )
        assert tree.tag == "name"
        assert tree.text == "Billing"
        assert tree.children == []

    def test_root_with_nested_children(self):
        raw = (
            "<features>"
            "<feature><name>Billing</name><intent>Pay for tiers.</intent></feature>"
            "<feature><name>Auth</name><intent>Sign in securely.</intent></feature>"
            "</features>"
        )
        tree = extract_tag_tree(raw, "features")
        assert tree.tag == "features"
        assert len(tree.children) == 2
        assert [c.tag for c in tree.children] == ["feature", "feature"]
        assert tree.children[0].find("name").text == "Billing"  # type: ignore[union-attr]
        assert tree.children[0].find("intent").text == "Pay for tiers."  # type: ignore[union-attr]
        assert tree.children[1].find("name").text == "Auth"  # type: ignore[union-attr]

    def test_text_is_stripped_at_outer_edges(self):
        tree = extract_tag_tree("<name>  Billing  </name>", "name")
        assert tree.text == "Billing"

    def test_paragraph_whitespace_preserved_interior(self):
        # Internal newlines inside a paragraph-length intent are
        # preserved (only outer edges get stripped).
        raw = "<intent>First sentence.\n\nSecond sentence.</intent>"
        tree = extract_tag_tree(raw, "intent")
        assert "First sentence." in tree.text
        assert "Second sentence." in tree.text


class TestExtractTagTreeLeniency:
    def test_tolerates_preamble_prose(self):
        raw = (
            "Here is the feature expansion you asked for:\n\n"
            "<features><feature><name>Billing</name><intent>Pay.</intent></feature></features>"
        )
        tree = extract_tag_tree(raw, "features")
        assert tree.tag == "features"
        assert len(tree.children) == 1

    def test_tolerates_postamble_prose(self):
        raw = (
            "<features><feature><name>Billing</name><intent>Pay.</intent></feature></features>"
            "\n\nLet me know if you'd like adjustments!"
        )
        tree = extract_tag_tree(raw, "features")
        assert len(tree.children) == 1

    def test_tolerates_unescaped_ampersand_in_content(self):
        raw = "<intent>Support dogs & cats in the pet field.</intent>"
        tree = extract_tag_tree(raw, "intent")
        assert "dogs" in tree.text
        assert "cats" in tree.text

    def test_tolerates_whitespace_noise(self):
        raw = """
            <features>
                <feature>
                    <name>Billing</name>
                    <intent>Pay for tiered plans.</intent>
                </feature>
            </features>
        """
        tree = extract_tag_tree(raw, "features")
        assert len(tree.children) == 1
        feature = tree.children[0]
        assert feature.find("name").text == "Billing"  # type: ignore[union-attr]
        assert feature.find("intent").text == "Pay for tiered plans."  # type: ignore[union-attr]

    def test_unicode_content(self):
        raw = (
            "<features>"
            "<feature>"
            "<name>Billing</name>"
            "<intent>Users pay via credit card — monthly or annual plans.</intent>"
            "</feature>"
            "</features>"
        )
        tree = extract_tag_tree(raw, "features")
        intent = tree.children[0].find("intent")
        assert intent is not None
        assert "—" in intent.text


class TestExtractTagTreeFailures:
    def test_missing_root_tag_raises(self):
        raw = "Here are some features for your project, but I forgot the tags."
        with pytest.raises(ParseError, match="Expected a <features> block"):
            extract_tag_tree(raw, "features")

    def test_empty_string_raises(self):
        with pytest.raises(ParseError, match="Expected a <features> block"):
            extract_tag_tree("", "features")

    def test_non_string_input_raises(self):
        with pytest.raises(ParseError, match="must be a string"):
            extract_tag_tree(42, "features")  # type: ignore[arg-type]

    def test_wrong_root_tag_raises(self):
        raw = "<policies></policies>"
        with pytest.raises(ParseError, match="Expected a <features> block"):
            extract_tag_tree(raw, "features")


class TestTagNodeHelpers:
    def test_find_all_filters_by_tag(self):
        node = TagNode(
            tag="features",
            children=[
                TagNode(tag="feature"),
                TagNode(tag="feature"),
                TagNode(tag="other"),
            ],
        )
        assert len(node.find_all("feature")) == 2
        assert len(node.find_all("other")) == 1
        assert len(node.find_all("missing")) == 0

    def test_find_returns_first_or_none(self):
        node = TagNode(
            tag="feature",
            children=[
                TagNode(tag="name", text="Billing"),
                TagNode(tag="intent", text="Pay."),
            ],
        )
        assert node.find("name") is not None
        assert node.find("name").text == "Billing"  # type: ignore[union-attr]
        assert node.find("missing") is None
