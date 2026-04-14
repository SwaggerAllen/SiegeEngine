"""Tests for backend.graph.parsers.validators.validate_vocabulary.

Covers the structural vocab validator added in Phase 5.5 stage 2:

- Empty vocabulary (no <term> children) is legal, returns empty.
- Single project-level term with just <definition> — happy path.
- Project-level term with all three inner children.
- Single feature-local term with matching feature-name.
- Feature-local term with unknown feature-name — rejected.
- Missing scope attribute / invalid scope value — rejected.
- Duplicate term names within a scope — rejected.
- Same name in project + feature scope — accepted (scope
  disambiguates).
- Inner grammar: missing <vocab-entry>, duplicate <vocab-entry>,
  missing <definition>, empty <definition>, nested XML in
  <definition> / <disambiguation>, out-of-order children.
- <see-also>: missing both name + to, having both name + to,
  duplicate refs within one entry, to= form rejected at
  cold-start (allow_id_refs=False), to= form accepted at
  post-mint time (allow_id_refs=True).
- raw_content round-trips: parse the stored XML back and get
  the same structured dataclass.
"""

from __future__ import annotations

import pytest

from backend.graph.parsers.validators import (
    ValidationError,
    VocabRef,
    validate_vocabulary,
)
from backend.graph.parsers.xml_sections import TagNode, extract_tag_tree

KNOWN_FEATURES = {"Billing", "Auth", "Reporting"}


def _vocab(inner: str) -> TagNode:
    return extract_tag_tree(f"<vocabulary>{inner}</vocabulary>", "vocabulary")


def _validate(inner: str, *, features: set[str] | None = None, allow_ids: bool = False):
    return validate_vocabulary(
        _vocab(inner),
        known_feature_names=features if features is not None else KNOWN_FEATURES,
        allow_id_refs=allow_ids,
    )


# ── Happy paths ──────────────────────────────────────────────────


class TestHappyPath:
    def test_empty_vocabulary(self):
        entries = _validate("")
        assert entries == ()

    def test_project_level_definition_only(self):
        entries = _validate(
            '<term name="boulder" scope="project">'
            "<vocab-entry>"
            "<definition>A unit of structured work with a sub-DAG.</definition>"
            "</vocab-entry>"
            "</term>"
        )
        assert len(entries) == 1
        e = entries[0]
        assert e.name == "boulder"
        assert e.scope == "project"
        assert e.feature_name is None
        assert e.definition == "A unit of structured work with a sub-DAG."
        assert e.disambiguation is None
        assert e.see_also_refs == ()
        assert "<vocab-entry>" in e.raw_content
        assert "boulder" not in e.raw_content  # raw_content is just the inner

    def test_project_level_with_all_children(self):
        entries = _validate(
            '<term name="boulder" scope="project">'
            "<vocab-entry>"
            "<definition>A unit of structured work.</definition>"
            "<disambiguation>Not a leaf node in the graph sense.</disambiguation>"
            '<see-also><ref name="fan-out"/><ref name="leaf"/></see-also>'
            "</vocab-entry>"
            "</term>"
        )
        assert len(entries) == 1
        e = entries[0]
        assert e.disambiguation == "Not a leaf node in the graph sense."
        assert e.see_also_refs == (
            VocabRef(name="fan-out", to=None),
            VocabRef(name="leaf", to=None),
        )

    def test_feature_local_with_matching_feature(self):
        entries = _validate(
            '<term name="tranche" scope="feature" feature-name="Billing">'
            "<vocab-entry>"
            "<definition>A time-bounded batch of invoices.</definition>"
            "</vocab-entry>"
            "</term>"
        )
        assert len(entries) == 1
        assert entries[0].scope == "feature"
        assert entries[0].feature_name == "Billing"

    def test_mixed_scope_happy_path(self):
        entries = _validate(
            '<term name="boulder" scope="project">'
            "<vocab-entry>"
            "<definition>Project term.</definition>"
            "</vocab-entry>"
            "</term>"
            '<term name="tranche" scope="feature" feature-name="Billing">'
            "<vocab-entry>"
            "<definition>Feature term.</definition>"
            "</vocab-entry>"
            "</term>"
        )
        assert len(entries) == 2
        assert entries[0].scope == "project"
        assert entries[1].scope == "feature"

    def test_same_name_across_scopes_allowed(self):
        entries = _validate(
            '<term name="tranche" scope="project">'
            "<vocab-entry>"
            "<definition>Project-wide meaning.</definition>"
            "</vocab-entry>"
            "</term>"
            '<term name="tranche" scope="feature" feature-name="Billing">'
            "<vocab-entry>"
            "<definition>Billing-specific meaning.</definition>"
            "</vocab-entry>"
            "</term>"
        )
        assert len(entries) == 2


# ── Root + structure ──────────────────────────────────────────


class TestStructure:
    def test_wrong_root_rejected(self):
        tree = TagNode(tag="features", text="", children=[])
        with pytest.raises(ValidationError, match="Expected root tag <vocabulary>"):
            validate_vocabulary(tree, known_feature_names=set(), allow_id_refs=False)

    def test_unknown_child_rejected(self):
        with pytest.raises(ValidationError, match="unexpected child <widget>"):
            _validate("<widget/>")


# ── Term attributes ──────────────────────────────────────────


class TestTermAttributes:
    def test_missing_scope_rejected(self):
        with pytest.raises(ValidationError, match="scope attribute"):
            _validate(
                '<term name="boulder"><vocab-entry><definition>d</definition></vocab-entry></term>'
            )

    def test_invalid_scope_rejected(self):
        with pytest.raises(ValidationError, match="scope attribute"):
            _validate(
                '<term name="boulder" scope="global">'
                "<vocab-entry><definition>d</definition></vocab-entry>"
                "</term>"
            )

    def test_missing_name_rejected(self):
        with pytest.raises(ValidationError, match="missing the name attribute"):
            _validate(
                '<term scope="project"><vocab-entry><definition>d</definition></vocab-entry></term>'
            )

    def test_invalid_name_rejected(self):
        with pytest.raises(ValidationError, match="invalid name"):
            _validate(
                '<term name="has@weird!chars" scope="project">'
                "<vocab-entry><definition>d</definition></vocab-entry>"
                "</term>"
            )

    def test_feature_scope_missing_feature_name_rejected(self):
        with pytest.raises(ValidationError, match="missing the feature-name attribute"):
            _validate(
                '<term name="tranche" scope="feature">'
                "<vocab-entry><definition>d</definition></vocab-entry>"
                "</term>"
            )

    def test_unknown_feature_name_rejected(self):
        with pytest.raises(ValidationError, match="not defined in the sibling"):
            _validate(
                '<term name="tranche" scope="feature" feature-name="Marketing">'
                "<vocab-entry><definition>d</definition></vocab-entry>"
                "</term>"
            )


# ── Uniqueness ──────────────────────────────────────────────


class TestUniqueness:
    def test_duplicate_project_name_rejected(self):
        with pytest.raises(ValidationError, match="project-level terms"):
            _validate(
                '<term name="boulder" scope="project">'
                "<vocab-entry><definition>d1</definition></vocab-entry>"
                "</term>"
                '<term name="boulder" scope="project">'
                "<vocab-entry><definition>d2</definition></vocab-entry>"
                "</term>"
            )

    def test_duplicate_feature_name_same_feature_rejected(self):
        with pytest.raises(ValidationError, match="feature-local terms"):
            _validate(
                '<term name="tranche" scope="feature" feature-name="Billing">'
                "<vocab-entry><definition>d1</definition></vocab-entry>"
                "</term>"
                '<term name="tranche" scope="feature" feature-name="Billing">'
                "<vocab-entry><definition>d2</definition></vocab-entry>"
                "</term>"
            )

    def test_same_name_different_features_allowed(self):
        entries = _validate(
            '<term name="tranche" scope="feature" feature-name="Billing">'
            "<vocab-entry><definition>Billing meaning.</definition></vocab-entry>"
            "</term>"
            '<term name="tranche" scope="feature" feature-name="Auth">'
            "<vocab-entry><definition>Auth meaning.</definition></vocab-entry>"
            "</term>"
        )
        assert len(entries) == 2


# ── Inner <vocab-entry> grammar ─────────────────────────────


class TestVocabEntryGrammar:
    def test_missing_vocab_entry_rejected(self):
        with pytest.raises(ValidationError, match="missing a <vocab-entry>"):
            _validate('<term name="boulder" scope="project"></term>')

    def test_duplicate_vocab_entry_rejected(self):
        with pytest.raises(ValidationError, match="2 <vocab-entry> children"):
            _validate(
                '<term name="boulder" scope="project">'
                "<vocab-entry><definition>d1</definition></vocab-entry>"
                "<vocab-entry><definition>d2</definition></vocab-entry>"
                "</term>"
            )

    def test_missing_definition_rejected(self):
        with pytest.raises(ValidationError, match="missing the required <definition>"):
            _validate(
                '<term name="boulder" scope="project">'
                "<vocab-entry>"
                "<disambiguation>no def here</disambiguation>"
                "</vocab-entry>"
                "</term>"
            )

    def test_empty_definition_rejected(self):
        with pytest.raises(ValidationError, match="<definition> is"):
            _validate(
                '<term name="boulder" scope="project">'
                "<vocab-entry><definition>   </definition></vocab-entry>"
                "</term>"
            )

    def test_nested_tags_in_definition_rejected(self):
        with pytest.raises(ValidationError, match="plain text only"):
            _validate(
                '<term name="boulder" scope="project">'
                "<vocab-entry>"
                "<definition>Has <nested>inside</nested></definition>"
                "</vocab-entry>"
                "</term>"
            )

    def test_empty_disambiguation_rejected(self):
        with pytest.raises(ValidationError, match="<disambiguation>"):
            _validate(
                '<term name="boulder" scope="project">'
                "<vocab-entry>"
                "<definition>real def</definition>"
                "<disambiguation>   </disambiguation>"
                "</vocab-entry>"
                "</term>"
            )

    def test_disambiguation_optional(self):
        # No disambiguation at all is fine.
        entries = _validate(
            '<term name="boulder" scope="project">'
            "<vocab-entry>"
            "<definition>real def</definition>"
            "</vocab-entry>"
            "</term>"
        )
        assert entries[0].disambiguation is None

    def test_out_of_order_children_rejected(self):
        # disambiguation before definition is a grammar violation.
        with pytest.raises(ValidationError, match="required order"):
            _validate(
                '<term name="boulder" scope="project">'
                "<vocab-entry>"
                "<disambiguation>dis</disambiguation>"
                "<definition>def</definition>"
                "</vocab-entry>"
                "</term>"
            )

    def test_unknown_child_in_vocab_entry_rejected(self):
        with pytest.raises(ValidationError, match="unexpected child <example>"):
            _validate(
                '<term name="boulder" scope="project">'
                "<vocab-entry>"
                "<definition>def</definition>"
                "<example>bad</example>"
                "</vocab-entry>"
                "</term>"
            )


# ── <see-also> refs ────────────────────────────────────────


class TestSeeAlsoRefs:
    def _term(self, see_also_body: str) -> str:
        return (
            '<term name="boulder" scope="project">'
            "<vocab-entry>"
            "<definition>def</definition>"
            f"<see-also>{see_also_body}</see-also>"
            "</vocab-entry>"
            "</term>"
        )

    def test_name_form_accepted(self):
        entries = _validate(self._term('<ref name="leaf"/>'))
        assert entries[0].see_also_refs == (VocabRef(name="leaf", to=None),)

    def test_multiple_refs_accepted(self):
        entries = _validate(
            self._term('<ref name="leaf"/><ref name="fan-out"/><ref name="foundation"/>')
        )
        names = [r.name for r in entries[0].see_also_refs]
        assert names == ["leaf", "fan-out", "foundation"]

    def test_empty_see_also_accepted(self):
        entries = _validate(self._term(""))
        assert entries[0].see_also_refs == ()

    def test_ref_missing_both_attrs_rejected(self):
        with pytest.raises(ValidationError, match="neither name"):
            _validate(self._term("<ref/>"))

    def test_ref_with_both_attrs_rejected(self):
        with pytest.raises(ValidationError, match="both name and to"):
            _validate(self._term('<ref name="leaf" to="vocab_12345678"/>'))

    def test_duplicate_refs_rejected(self):
        with pytest.raises(ValidationError, match="duplicate reference"):
            _validate(self._term('<ref name="leaf"/><ref name="leaf"/>'))

    def test_to_form_at_cold_start_rejected(self):
        with pytest.raises(ValidationError, match="id form"):
            _validate(self._term('<ref to="vocab_12345678"/>'), allow_ids=False)

    def test_to_form_with_allow_id_refs_accepted(self):
        entries = _validate(
            self._term('<ref to="vocab_12345678"/>'),
            allow_ids=True,
        )
        assert entries[0].see_also_refs == (VocabRef(name=None, to="vocab_12345678"),)

    def test_unknown_child_in_see_also_rejected(self):
        with pytest.raises(ValidationError, match="<see-also>"):
            _validate(self._term("<junk/>"))


# ── raw_content round-trip ─────────────────────────────────


class TestRawContentRoundTrip:
    def test_raw_content_is_vocab_entry_only(self):
        entries = _validate(
            '<term name="boulder" scope="project">'
            "<vocab-entry>"
            "<definition>def</definition>"
            "</vocab-entry>"
            "</term>"
        )
        raw = entries[0].raw_content
        # Starts with <vocab-entry> and ends with </vocab-entry>
        assert raw.startswith("<vocab-entry>")
        assert raw.endswith("</vocab-entry>")
        assert "<definition>def</definition>" in raw
        # No <term> wrapper, no term name — just the inner block
        assert "boulder" not in raw
        assert "<term" not in raw

    def test_raw_content_parses_back(self):
        entries = _validate(
            '<term name="boulder" scope="project">'
            "<vocab-entry>"
            "<definition>The definition text.</definition>"
            "<disambiguation>Not the other thing.</disambiguation>"
            '<see-also><ref name="leaf"/><ref name="fan-out"/></see-also>'
            "</vocab-entry>"
            "</term>"
        )
        raw = entries[0].raw_content
        # Parse the stored XML back and verify we get the same structure.
        reparsed = extract_tag_tree(raw, "vocab-entry")
        assert reparsed.tag == "vocab-entry"
        child_tags = [c.tag for c in reparsed.children]
        assert child_tags == ["definition", "disambiguation", "see-also"]

    def test_raw_content_preserves_see_also_refs(self):
        entries = _validate(
            '<term name="boulder" scope="project">'
            "<vocab-entry>"
            "<definition>d</definition>"
            '<see-also><ref name="leaf"/><ref name="fan-out"/></see-also>'
            "</vocab-entry>"
            "</term>"
        )
        raw = entries[0].raw_content
        assert 'name="leaf"' in raw
        assert 'name="fan-out"' in raw


# ── Features name uniqueness regression ────────────────────


class TestFeaturesNameUniqueness:
    """Regression test for the feature-name uniqueness check
    added to validate_features as part of this stage."""

    def test_duplicate_feature_names_rejected(self):
        from backend.graph.parsers.validators import validate_features

        raw = (
            "<features>"
            "<feature><name>Billing</name><intent>First.</intent></feature>"
            "<feature><name>Billing</name><intent>Second.</intent></feature>"
            "</features>"
        )
        tree = extract_tag_tree(raw, "features")
        with pytest.raises(ValidationError, match="two features with the same name"):
            validate_features(tree)

    def test_unique_feature_names_accepted(self):
        from backend.graph.parsers.validators import validate_features

        raw = (
            "<features>"
            "<feature><name>Billing</name><intent>Pay.</intent></feature>"
            "<feature><name>Auth</name><intent>Sign in.</intent></feature>"
            "</features>"
        )
        tree = extract_tag_tree(raw, "features")
        features = validate_features(tree)
        assert {f.name for f in features} == {"Billing", "Auth"}
