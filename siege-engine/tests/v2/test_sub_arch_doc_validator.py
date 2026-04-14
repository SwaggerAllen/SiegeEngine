"""Tests for backend.graph.parsers.validators.validate_sub_arch_doc.

Parallels test_arch_doc_validator.py's shape for the four-section
subcomparch tier. Covers structural validation (root + section
order), fragment section rules (non-empty, no nested tags),
<dependencies> resolution (every target a real comp_* ID drawn
from one of two allowlists), and explicit rejection of forbidden
sections (<policies>, <subcomponents>, <sub-dependencies>).
"""

from __future__ import annotations

import pytest

from backend.graph.parsers.validators import (
    SubArchDep,
    ValidationError,
    validate_sub_arch_doc,
)
from backend.graph.parsers.xml_sections import TagNode, extract_tag_tree


def _parse(raw: str) -> TagNode:
    return extract_tag_tree(raw, "subcomparch")


KNOWN_SIBLING_SUB_IDS = {"comp_session9", "comp_credgt01", "comp_foundsu1"}
KNOWN_PARENT_SIBLINGS = {"comp_audit999", "comp_foundati"}


def _sub_arch_doc(
    *,
    techspec: str = "Narrow slice of the auth stack.",
    pubapi: str = "get(key) -> CachedValue | None.",
    privapi: str = "Internal: _touch(key).",
    dependencies: str = "",
) -> str:
    return (
        "<subcomparch>"
        f"<technical-specification>{techspec}</technical-specification>"
        f"<public-surface>{pubapi}</public-surface>"
        f"<private-surface>{privapi}</private-surface>"
        f"<dependencies>{dependencies}</dependencies>"
        "</subcomparch>"
    )


def _validate(
    raw: str,
    *,
    known_sibling_sub_ids: set[str] | None = None,
    known_parent_sibling_comp_ids: set[str] | None = None,
):
    return validate_sub_arch_doc(
        _parse(raw),
        known_sibling_sub_ids=known_sibling_sub_ids
        if known_sibling_sub_ids is not None
        else KNOWN_SIBLING_SUB_IDS,
        known_parent_sibling_comp_ids=known_parent_sibling_comp_ids
        if known_parent_sibling_comp_ids is not None
        else KNOWN_PARENT_SIBLINGS,
    )


class TestHappyPath:
    def test_minimal_leaf(self):
        """Empty <dependencies> is legal (leaf subcomponent)."""
        doc = _validate(_sub_arch_doc())
        assert doc.techspec == "Narrow slice of the auth stack."
        assert doc.pubapi == "get(key) -> CachedValue | None."
        assert doc.privapi == "Internal: _touch(key)."
        assert doc.deps == ()

    def test_with_sibling_sub_deps(self):
        doc = _validate(
            _sub_arch_doc(
                dependencies='<dep to="comp_session9"/><dep to="comp_foundsu1"/>',
            )
        )
        assert doc.deps == (
            SubArchDep(target="comp_session9"),
            SubArchDep(target="comp_foundsu1"),
        )

    def test_with_parent_sibling_deps(self):
        doc = _validate(
            _sub_arch_doc(
                dependencies='<dep to="comp_audit999"/>',
            )
        )
        assert doc.deps == (SubArchDep(target="comp_audit999"),)

    def test_mixed_sibling_and_parent_sibling_deps(self):
        doc = _validate(
            _sub_arch_doc(
                dependencies=(
                    '<dep to="comp_session9"/>'
                    '<dep to="comp_audit999"/>'
                    '<dep to="comp_foundsu1"/>'
                    '<dep to="comp_foundati"/>'
                ),
            )
        )
        assert len(doc.deps) == 4
        assert {d.target for d in doc.deps} == {
            "comp_session9",
            "comp_audit999",
            "comp_foundsu1",
            "comp_foundati",
        }


class TestRootAndSectionOrder:
    def test_wrong_root_rejected(self):
        tree = TagNode(tag="comparch", text="", children=[])
        with pytest.raises(ValidationError, match="Expected root tag <subcomparch>"):
            validate_sub_arch_doc(
                tree,
                known_sibling_sub_ids=set(),
                known_parent_sibling_comp_ids=set(),
            )

    def test_missing_section_rejected(self):
        raw = (
            "<subcomparch>"
            "<technical-specification>t</technical-specification>"
            "<public-surface>p</public-surface>"
            "<dependencies></dependencies>"
            "</subcomparch>"
        )
        with pytest.raises(ValidationError, match="not in the required order"):
            _validate(raw)

    def test_wrong_section_order_rejected(self):
        raw = (
            "<subcomparch>"
            "<technical-specification>t</technical-specification>"
            "<private-surface>pr</private-surface>"
            "<public-surface>p</public-surface>"
            "<dependencies></dependencies>"
            "</subcomparch>"
        )
        with pytest.raises(ValidationError, match="not in the required order"):
            _validate(raw)

    def test_duplicate_section_rejected(self):
        raw = (
            "<subcomparch>"
            "<technical-specification>t</technical-specification>"
            "<technical-specification>t2</technical-specification>"
            "<public-surface>p</public-surface>"
            "<private-surface>pr</private-surface>"
            "<dependencies></dependencies>"
            "</subcomparch>"
        )
        with pytest.raises(ValidationError, match="more than one <technical-specification>"):
            _validate(raw)

    def test_unknown_section_rejected(self):
        raw = _sub_arch_doc().replace("</subcomparch>", "<widget></widget></subcomparch>")
        with pytest.raises(ValidationError, match="unexpected child <widget>"):
            _validate(raw)


class TestForbiddenSections:
    def test_policies_section_rejected(self):
        raw = _sub_arch_doc().replace(
            "<dependencies></dependencies>",
            "<dependencies></dependencies><policies></policies>",
        )
        with pytest.raises(ValidationError, match="subcomponents don't have policies"):
            _validate(raw)

    def test_subcomponents_section_rejected(self):
        raw = _sub_arch_doc().replace(
            "<dependencies></dependencies>",
            "<dependencies></dependencies><subcomponents></subcomponents>",
        )
        with pytest.raises(ValidationError, match="can't decompose further"):
            _validate(raw)

    def test_sub_dependencies_section_rejected(self):
        raw = _sub_arch_doc().replace(
            "<dependencies></dependencies>",
            "<dependencies></dependencies><sub-dependencies></sub-dependencies>",
        )
        with pytest.raises(ValidationError, match="can't decompose further"):
            _validate(raw)


class TestFragmentSections:
    def test_empty_techspec_rejected(self):
        raw = _sub_arch_doc(techspec="")
        with pytest.raises(ValidationError, match="<technical-specification> is empty"):
            _validate(raw)

    def test_empty_pubapi_rejected(self):
        raw = _sub_arch_doc(pubapi="")
        with pytest.raises(ValidationError, match="<public-surface> is empty"):
            _validate(raw)

    def test_empty_privapi_rejected(self):
        raw = _sub_arch_doc(privapi="")
        with pytest.raises(ValidationError, match="<private-surface> is empty"):
            _validate(raw)

    def test_nested_tags_in_fragment_rejected(self):
        raw = (
            "<subcomparch>"
            "<technical-specification>t <nested>no</nested></technical-specification>"
            "<public-surface>p</public-surface>"
            "<private-surface>pr</private-surface>"
            "<dependencies></dependencies>"
            "</subcomparch>"
        )
        with pytest.raises(ValidationError, match="must contain plain text"):
            _validate(raw)


class TestDependencies:
    def test_missing_to_attribute_rejected(self):
        raw = _sub_arch_doc(dependencies="<dep/>")
        with pytest.raises(ValidationError, match="missing the to attribute"):
            _validate(raw)

    def test_from_attribute_rejected(self):
        raw = _sub_arch_doc(dependencies='<dep from="self" to="comp_session9"/>')
        with pytest.raises(ValidationError, match="has a from attribute"):
            _validate(raw)

    def test_non_comp_prefix_rejected(self):
        """Legacy alias scheme is gone — any target without comp_ is rejected."""
        raw = _sub_arch_doc(dependencies='<dep to="session_store"/>')
        with pytest.raises(ValidationError, match="not a comp_\\* ID"):
            _validate(raw)

    def test_unknown_sibling_sub_id_rejected(self):
        raw = _sub_arch_doc(dependencies='<dep to="comp_unknown1"/>')
        with pytest.raises(ValidationError, match="not in the allowed set"):
            _validate(raw)

    def test_unknown_parent_sibling_comp_id_rejected(self):
        raw = _sub_arch_doc(dependencies='<dep to="comp_strange9"/>')
        with pytest.raises(ValidationError, match="not in the allowed set"):
            _validate(raw)

    def test_duplicate_dep_rejected(self):
        raw = _sub_arch_doc(dependencies='<dep to="comp_session9"/><dep to="comp_session9"/>')
        with pytest.raises(ValidationError, match="duplicate target"):
            _validate(raw)

    def test_duplicate_parent_sibling_rejected(self):
        raw = _sub_arch_doc(dependencies='<dep to="comp_audit999"/><dep to="comp_audit999"/>')
        with pytest.raises(ValidationError, match="duplicate target"):
            _validate(raw)

    def test_empty_dependencies_accepted(self):
        doc = _validate(_sub_arch_doc(dependencies=""))
        assert doc.deps == ()

    def test_unknown_tag_under_dependencies_rejected(self):
        raw = _sub_arch_doc(dependencies="<junk/>")
        with pytest.raises(ValidationError, match="<dependencies> contains an unexpected child"):
            _validate(raw)

    def test_empty_allowlists_reject_any_dep(self):
        # Subcomponent with no siblings and no parent-siblings —
        # the only legal <dependencies> shape is empty.
        raw_with_sibling = _sub_arch_doc(dependencies='<dep to="comp_session9"/>')
        with pytest.raises(ValidationError, match="not in the allowed set"):
            _validate(
                raw_with_sibling,
                known_sibling_sub_ids=set(),
                known_parent_sibling_comp_ids=set(),
            )
        raw_with_parent_sibling = _sub_arch_doc(dependencies='<dep to="comp_audit999"/>')
        with pytest.raises(ValidationError, match="not in the allowed set"):
            _validate(
                raw_with_parent_sibling,
                known_sibling_sub_ids=set(),
                known_parent_sibling_comp_ids=set(),
            )
        # But empty <dependencies> is fine.
        doc = _validate(
            _sub_arch_doc(),
            known_sibling_sub_ids=set(),
            known_parent_sibling_comp_ids=set(),
        )
        assert doc.deps == ()
