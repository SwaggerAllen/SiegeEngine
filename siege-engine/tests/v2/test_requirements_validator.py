"""Tests for backend.graph.parsers.validators.validate_requirements."""

from __future__ import annotations

import pytest

from backend.graph.parsers.validators import (
    ValidationError,
    validate_requirements,
)
from backend.graph.parsers.xml_sections import TagNode, extract_tag_tree


def _parse(raw: str) -> TagNode:
    return extract_tag_tree(raw, "requirements")


def _covers(*feat_ids: str) -> str:
    return "<covers>" + "".join(f'<feat id="{fid}"/>' for fid in feat_ids) + "</covers>"


# Fixed known-id set used by most happy-path tests. Values are
# stable across tests so test XML can reference them freely.
KNOWN = {"feat_abc12345", "feat_def67890", "feat_xyz00001"}


class TestValidateRequirementsHappyPath:
    def test_single_responsibility(self):
        tree = _parse(
            "<requirements>"
            "<responsibility>"
            "<name>User Authentication</name>"
            "<intent>Establish the identity of a caller and make it "
            "available to downstream logic.</intent>"
            + _covers("feat_abc12345", "feat_def67890", "feat_xyz00001")
            + "</responsibility>"
            "</requirements>"
        )
        resps = validate_requirements(tree, known_feature_ids=KNOWN)
        assert len(resps) == 1
        assert resps[0].name == "User Authentication"
        assert resps[0].intent == (
            "Establish the identity of a caller and make it available to downstream logic."
        )
        assert set(resps[0].covers) == KNOWN

    def test_multiple_preserve_order(self):
        tree = _parse(
            "<requirements>"
            "<responsibility><name>Auth</name><intent>Identify callers.</intent>"
            + _covers("feat_abc12345")
            + "</responsibility>"
            "<responsibility><name>Billing</name><intent>Bill accounts.</intent>"
            + _covers("feat_def67890")
            + "</responsibility>"
            "<responsibility><name>Telemetry</name><intent>Record usage.</intent>"
            + _covers("feat_abc12345", "feat_def67890", "feat_xyz00001")
            + "</responsibility>"
            "</requirements>"
        )
        resps = validate_requirements(tree, known_feature_ids=KNOWN)
        assert [r.name for r in resps] == ["Auth", "Billing", "Telemetry"]

    def test_many_to_many_feature_appears_under_multiple_resps(self):
        # feat_abc12345 is covered by both Auth and Telemetry. That
        # should be fine — the decomposition relationship is
        # many-to-many by design.
        tree = _parse(
            "<requirements>"
            "<responsibility><name>Auth</name><intent>Identify.</intent>"
            + _covers("feat_abc12345", "feat_def67890")
            + "</responsibility>"
            "<responsibility><name>Telemetry</name><intent>Record.</intent>"
            + _covers("feat_abc12345", "feat_def67890", "feat_xyz00001")
            + "</responsibility>"
            "</requirements>"
        )
        resps = validate_requirements(tree, known_feature_ids=KNOWN)
        assert "feat_abc12345" in resps[0].covers
        assert "feat_abc12345" in resps[1].covers

    def test_multi_sentence_intent_preserved(self):
        tree = _parse(
            "<requirements>"
            "<responsibility>"
            "<name>Telemetry</name>"
            "<intent>Record every LLM call. Flag latency spikes. Retain for 30 days.</intent>"
            + _covers("feat_abc12345", "feat_def67890", "feat_xyz00001")
            + "</responsibility>"
            "</requirements>"
        )
        resps = validate_requirements(tree, known_feature_ids=KNOWN)
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
            validate_requirements(tree, known_feature_ids=set())

    def test_unknown_child_rejected(self):
        tree = _parse(
            "<requirements>"
            "<responsibility><name>Auth</name><intent>Ok.</intent>"
            + _covers("feat_abc12345", "feat_def67890", "feat_xyz00001")
            + "</responsibility>"
            "<widget>nope</widget>"
            "</requirements>"
        )
        with pytest.raises(ValidationError, match="unexpected child <widget>"):
            validate_requirements(tree, known_feature_ids=KNOWN)

    def test_empty_rejected(self):
        tree = _parse("<requirements></requirements>")
        with pytest.raises(ValidationError, match="no <responsibility>"):
            validate_requirements(tree, known_feature_ids=set())


class TestValidateResponsibilityStructure:
    def test_missing_name_rejected(self):
        tree = _parse(
            "<requirements>"
            "<responsibility><intent>No name here.</intent>"
            + _covers("feat_abc12345")
            + "</responsibility>"
            "</requirements>"
        )
        with pytest.raises(ValidationError, match="missing a <name>"):
            validate_requirements(tree, known_feature_ids={"feat_abc12345"})

    def test_missing_intent_rejected(self):
        tree = _parse(
            "<requirements>"
            "<responsibility><name>Auth</name>" + _covers("feat_abc12345") + "</responsibility>"
            "</requirements>"
        )
        with pytest.raises(ValidationError, match="missing an <intent>"):
            validate_requirements(tree, known_feature_ids={"feat_abc12345"})

    def test_missing_covers_rejected(self):
        tree = _parse(
            "<requirements>"
            "<responsibility><name>Auth</name><intent>Ok.</intent></responsibility>"
            "</requirements>"
        )
        with pytest.raises(ValidationError, match="missing a <covers>"):
            validate_requirements(tree, known_feature_ids={"feat_abc12345"})

    def test_multiple_names_rejected(self):
        tree = _parse(
            "<requirements>"
            "<responsibility>"
            "<name>Auth</name><name>Auth2</name>"
            "<intent>Ok.</intent>" + _covers("feat_abc12345") + "</responsibility>"
            "</requirements>"
        )
        with pytest.raises(ValidationError, match="2 <name> children"):
            validate_requirements(tree, known_feature_ids={"feat_abc12345"})

    def test_multiple_intents_rejected(self):
        tree = _parse(
            "<requirements>"
            "<responsibility>"
            "<name>Auth</name>"
            "<intent>First.</intent><intent>Second.</intent>"
            + _covers("feat_abc12345")
            + "</responsibility>"
            "</requirements>"
        )
        with pytest.raises(ValidationError, match="2 <intent> children"):
            validate_requirements(tree, known_feature_ids={"feat_abc12345"})

    def test_multiple_covers_rejected(self):
        tree = _parse(
            "<requirements>"
            "<responsibility>"
            "<name>Auth</name><intent>Ok.</intent>"
            + _covers("feat_abc12345")
            + _covers("feat_def67890")
            + "</responsibility>"
            "</requirements>"
        )
        with pytest.raises(ValidationError, match="2 <covers> children"):
            validate_requirements(tree, known_feature_ids={"feat_abc12345", "feat_def67890"})

    def test_empty_name_rejected(self):
        tree = _parse(
            "<requirements>"
            "<responsibility><name> </name><intent>Ok.</intent>"
            + _covers("feat_abc12345")
            + "</responsibility>"
            "</requirements>"
        )
        with pytest.raises(ValidationError, match="empty <name>"):
            validate_requirements(tree, known_feature_ids={"feat_abc12345"})

    def test_empty_intent_rejected(self):
        tree = _parse(
            "<requirements>"
            "<responsibility><name>Auth</name><intent> </intent>"
            + _covers("feat_abc12345")
            + "</responsibility>"
            "</requirements>"
        )
        with pytest.raises(ValidationError, match="empty <intent>"):
            validate_requirements(tree, known_feature_ids={"feat_abc12345"})

    def test_unknown_child_in_responsibility_rejected(self):
        tree = _parse(
            "<requirements>"
            "<responsibility>"
            "<name>Auth</name>"
            "<intent>Ok.</intent>"
            "<rationale>should not be here</rationale>"
            + _covers("feat_abc12345")
            + "</responsibility>"
            "</requirements>"
        )
        with pytest.raises(ValidationError, match="unexpected child <rationale>"):
            validate_requirements(tree, known_feature_ids={"feat_abc12345"})


class TestValidateCovers:
    def test_empty_covers_rejected(self):
        tree = _parse(
            "<requirements>"
            "<responsibility><name>Auth</name><intent>Ok.</intent><covers></covers>"
            "</responsibility>"
            "</requirements>"
        )
        with pytest.raises(ValidationError, match="empty <covers>"):
            validate_requirements(tree, known_feature_ids={"feat_abc12345"})

    def test_covers_with_unknown_tag_rejected(self):
        tree = _parse(
            "<requirements>"
            "<responsibility><name>Auth</name><intent>Ok.</intent>"
            '<covers><feat id="feat_abc12345"/><widget/></covers>'
            "</responsibility>"
            "</requirements>"
        )
        with pytest.raises(ValidationError, match="unexpected.*<widget>"):
            validate_requirements(tree, known_feature_ids={"feat_abc12345"})

    def test_feat_missing_id_rejected(self):
        tree = _parse(
            "<requirements>"
            "<responsibility><name>Auth</name><intent>Ok.</intent>"
            "<covers><feat/></covers>"
            "</responsibility>"
            "</requirements>"
        )
        with pytest.raises(ValidationError, match="no id attribute"):
            validate_requirements(tree, known_feature_ids={"feat_abc12345"})

    def test_unknown_feature_id_rejected(self):
        tree = _parse(
            "<requirements>"
            "<responsibility><name>Auth</name><intent>Ok.</intent>"
            + _covers("feat_unknown1")
            + "</responsibility>"
            "</requirements>"
        )
        with pytest.raises(ValidationError, match="unknown feature id"):
            validate_requirements(tree, known_feature_ids={"feat_abc12345"})

    def test_duplicate_feature_in_same_covers_rejected(self):
        tree = _parse(
            "<requirements>"
            "<responsibility><name>Auth</name><intent>Ok.</intent>"
            + _covers("feat_abc12345", "feat_abc12345")
            + "</responsibility>"
            "</requirements>"
        )
        with pytest.raises(ValidationError, match="duplicate feature id"):
            validate_requirements(tree, known_feature_ids={"feat_abc12345"})

    def test_feature_not_covered_anywhere_rejected(self):
        # feat_def67890 exists but no responsibility covers it.
        tree = _parse(
            "<requirements>"
            "<responsibility><name>Auth</name><intent>Ok.</intent>"
            + _covers("feat_abc12345")
            + "</responsibility>"
            "</requirements>"
        )
        with pytest.raises(ValidationError, match="does not cover every feature"):
            validate_requirements(tree, known_feature_ids={"feat_abc12345", "feat_def67890"})

    def test_coverage_check_passes_when_union_covers_all(self):
        # Two resps together cover two features; validator accepts.
        tree = _parse(
            "<requirements>"
            "<responsibility><name>Auth</name><intent>Ok.</intent>"
            + _covers("feat_abc12345")
            + "</responsibility>"
            "<responsibility><name>Billing</name><intent>Ok.</intent>"
            + _covers("feat_def67890")
            + "</responsibility>"
            "</requirements>"
        )
        resps = validate_requirements(tree, known_feature_ids={"feat_abc12345", "feat_def67890"})
        assert len(resps) == 2


class TestImplicitResponsibilities:
    """Implicit responsibilities use <implicit/> in place of <covers>.

    They capture system-facing architectural concerns (central
    registries, error-code vocab, pubsub event-name bus) that no
    feature sources but the system still needs. The validator
    distinguishes them via the <implicit/> marker and accepts an
    empty covers tuple only for implicit resps.
    """

    def test_accepts_implicit_marker_in_place_of_covers(self):
        tree = _parse(
            "<requirements>"
            "<responsibility>"
            "<name>Auth</name><intent>Identify callers.</intent>"
            + _covers("feat_abc12345", "feat_def67890", "feat_xyz00001")
            + "</responsibility>"
            "<responsibility>"
            "<name>Central Metric Registry</name>"
            "<intent>Own the vocabulary of metric names.</intent>"
            "<implicit/>"
            "</responsibility>"
            "</requirements>"
        )
        resps = validate_requirements(tree, known_feature_ids=KNOWN)
        assert len(resps) == 2
        assert resps[0].is_implicit is False
        assert resps[0].covers  # has covers
        assert resps[1].is_implicit is True
        assert resps[1].covers == ()

    def test_rejects_implicit_alongside_covers(self):
        tree = _parse(
            "<requirements>"
            "<responsibility>"
            "<name>Mixed</name><intent>Intent.</intent>"
            "<implicit/>"
            + _covers("feat_abc12345", "feat_def67890", "feat_xyz00001")
            + "</responsibility>"
            "</requirements>"
        )
        with pytest.raises(ValidationError, match="implicit.*also carries a <covers>"):
            validate_requirements(tree, known_feature_ids=KNOWN)

    def test_rejects_multiple_implicit_markers(self):
        tree = _parse(
            "<requirements>"
            "<responsibility>"
            "<name>Registry</name><intent>Own registry.</intent>"
            "<implicit/>"
            "<implicit/>"
            "</responsibility>"
            "</requirements>"
        )
        with pytest.raises(ValidationError, match="2 <implicit/> markers"):
            validate_requirements(tree, known_feature_ids=set())

    def test_implicit_resps_dont_contribute_to_coverage(self):
        # Feature coverage still requires an explicit resp to cover
        # every feature; an implicit resp alone can't satisfy the
        # coverage rule.
        tree = _parse(
            "<requirements>"
            "<responsibility>"
            "<name>Registry</name><intent>Own registry.</intent>"
            "<implicit/>"
            "</responsibility>"
            "</requirements>"
        )
        with pytest.raises(ValidationError, match="does not cover every feature"):
            validate_requirements(tree, known_feature_ids={"feat_abc12345"})

    def test_explicit_resp_still_requires_covers(self):
        # Absent both <implicit/> and <covers>, the resp is invalid.
        tree = _parse(
            "<requirements>"
            "<responsibility><name>Orphan</name><intent>No source.</intent></responsibility>"
            "</requirements>"
        )
        with pytest.raises(ValidationError, match="missing a <covers> child"):
            validate_requirements(tree, known_feature_ids=set())

    def test_implicit_only_allowed_when_no_features_exist(self):
        # A project with no features can legitimately consist of
        # only implicit resps — the coverage rule is trivially
        # satisfied because there are no features to cover.
        tree = _parse(
            "<requirements>"
            "<responsibility>"
            "<name>Registry</name><intent>Own registry.</intent>"
            "<implicit/>"
            "</responsibility>"
            "</requirements>"
        )
        resps = validate_requirements(tree, known_feature_ids=set())
        assert len(resps) == 1
        assert resps[0].is_implicit is True
