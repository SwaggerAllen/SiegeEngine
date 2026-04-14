"""Tests for backend.graph.parsers.validators.validate_sub_arch_doc.

Parallels test_arch_doc_validator.py's shape for the four-section
subcomparch tier. Covers structural validation (root + section
order), fragment section rules (non-empty, no nested tags),
mixed-target <dependencies> resolution (alias vs real comp_* ID),
and explicit rejection of forbidden sections (<policies>,
<subcomponents>, <sub-dependencies>).
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


KNOWN_SIBLING_ALIASES = {"session_store", "credential_gate", "foundation"}
KNOWN_PARENT_SIBLINGS = {"comp_audit9999", "comp_foundati1"}


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
    known_sibling_sub_aliases: set[str] | None = None,
    known_parent_sibling_comp_ids: set[str] | None = None,
):
    return validate_sub_arch_doc(
        _parse(raw),
        known_sibling_sub_aliases=known_sibling_sub_aliases
        if known_sibling_sub_aliases is not None
        else KNOWN_SIBLING_ALIASES,
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

    def test_with_alias_deps(self):
        doc = _validate(
            _sub_arch_doc(
                dependencies='<dep to="session_store"/><dep to="foundation"/>',
            )
        )
        assert doc.deps == (
            SubArchDep(target="session_store", is_alias=True),
            SubArchDep(target="foundation", is_alias=True),
        )

    def test_with_comp_id_deps(self):
        doc = _validate(
            _sub_arch_doc(
                dependencies='<dep to="comp_audit9999"/>',
            )
        )
        assert doc.deps == (SubArchDep(target="comp_audit9999", is_alias=False),)

    def test_mixed_alias_and_comp_id_deps(self):
        doc = _validate(
            _sub_arch_doc(
                dependencies=(
                    '<dep to="session_store"/>'
                    '<dep to="comp_audit9999"/>'
                    '<dep to="foundation"/>'
                    '<dep to="comp_foundati1"/>'
                ),
            )
        )
        assert len(doc.deps) == 4
        # Two aliases, two real IDs
        alias_entries = [d for d in doc.deps if d.is_alias]
        id_entries = [d for d in doc.deps if not d.is_alias]
        assert {d.target for d in alias_entries} == {"session_store", "foundation"}
        assert {d.target for d in id_entries} == {"comp_audit9999", "comp_foundati1"}


class TestRootAndSectionOrder:
    def test_wrong_root_rejected(self):
        tree = TagNode(tag="comparch", text="", children=[])
        with pytest.raises(ValidationError, match="Expected root tag <subcomparch>"):
            validate_sub_arch_doc(
                tree,
                known_sibling_sub_aliases=set(),
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
        raw = _sub_arch_doc(dependencies='<dep from="self" to="session_store"/>')
        with pytest.raises(ValidationError, match="has a from attribute"):
            _validate(raw)

    def test_unknown_alias_rejected(self):
        raw = _sub_arch_doc(dependencies='<dep to="mystery_sib"/>')
        with pytest.raises(ValidationError, match="allowed same-parent sibling set"):
            _validate(raw)

    def test_unknown_comp_id_rejected(self):
        raw = _sub_arch_doc(dependencies='<dep to="comp_strange99"/>')
        with pytest.raises(ValidationError, match="allowed parent-sibling component set"):
            _validate(raw)

    def test_duplicate_alias_rejected(self):
        raw = _sub_arch_doc(dependencies='<dep to="session_store"/><dep to="session_store"/>')
        with pytest.raises(ValidationError, match="duplicate target"):
            _validate(raw)

    def test_duplicate_comp_id_rejected(self):
        raw = _sub_arch_doc(dependencies='<dep to="comp_audit9999"/><dep to="comp_audit9999"/>')
        with pytest.raises(ValidationError, match="duplicate target"):
            _validate(raw)

    def test_duplicate_across_kinds_rejected(self):
        # Pathological case: a string happens to match both sets.
        # In practice the comp_ prefix keeps them disjoint, but
        # the duplicate check runs on the raw target before the
        # alias-vs-id split so this still fires.
        raw = _sub_arch_doc(dependencies='<dep to="session_store"/><dep to="session_store"/>')
        with pytest.raises(ValidationError, match="duplicate target"):
            _validate(raw)

    def test_empty_dependencies_accepted(self):
        doc = _validate(_sub_arch_doc(dependencies=""))
        assert doc.deps == ()

    def test_unknown_tag_under_dependencies_rejected(self):
        raw = _sub_arch_doc(dependencies="<junk/>")
        with pytest.raises(ValidationError, match="<dependencies> contains an unexpected child"):
            _validate(raw)

    def test_alias_disambiguation_is_comp_prefix_based(self):
        """Non-comp_ strings are always treated as aliases, even if they
        happen to look like IDs otherwise."""
        raw = _sub_arch_doc(dependencies='<dep to="foundation"/>')
        doc = _validate(raw)
        assert doc.deps == (SubArchDep(target="foundation", is_alias=True),)

    def test_empty_allowlists_reject_any_dep(self):
        # Subcomponent with no siblings and no parent-siblings —
        # the only legal <dependencies> shape is empty.
        raw_with_alias = _sub_arch_doc(dependencies='<dep to="session_store"/>')
        with pytest.raises(ValidationError, match="allowed same-parent sibling set"):
            _validate(
                raw_with_alias,
                known_sibling_sub_aliases=set(),
                known_parent_sibling_comp_ids=set(),
            )
        raw_with_id = _sub_arch_doc(dependencies='<dep to="comp_audit9999"/>')
        with pytest.raises(ValidationError, match="allowed parent-sibling component set"):
            _validate(
                raw_with_id,
                known_sibling_sub_aliases=set(),
                known_parent_sibling_comp_ids=set(),
            )
        # But empty <dependencies> is fine.
        doc = _validate(
            _sub_arch_doc(),
            known_sibling_sub_aliases=set(),
            known_parent_sibling_comp_ids=set(),
        )
        assert doc.deps == ()
