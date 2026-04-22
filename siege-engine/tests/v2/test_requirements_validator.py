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


def _owns(*feat_ids: str) -> str:
    return "<owns>" + "".join(f'<feat id="{fid}"/>' for fid in feat_ids) + "</owns>"


def _supports(*feat_ids: str) -> str:
    return "<supports>" + "".join(f'<feat id="{fid}"/>' for fid in feat_ids) + "</supports>"


def _resp(
    name: str,
    intent: str,
    owns_ids: tuple[str, ...],
    supports_ids: tuple[str, ...] = (),
) -> str:
    """Build a single <responsibility> fragment for test fixtures."""
    parts = [
        "<responsibility>",
        f"<name>{name}</name>",
        f"<intent>{intent}</intent>",
        _owns(*owns_ids),
    ]
    if supports_ids:
        parts.append(_supports(*supports_ids))
    parts.append("</responsibility>")
    return "".join(parts)


# Fixed known-id set used by most happy-path tests.
KNOWN = {"feat_abc12345", "feat_def67890", "feat_xyz00001"}


class TestValidateRequirementsHappyPath:
    def test_single_responsibility(self):
        tree = _parse(
            "<requirements>"
            + _resp(
                "User Authentication",
                "Establish the identity of a caller and make it available to downstream logic.",
                ("feat_abc12345", "feat_def67890", "feat_xyz00001"),
            )
            + "</requirements>"
        )
        resps = validate_requirements(tree, known_feature_ids=KNOWN)
        assert len(resps) == 1
        assert resps[0].name == "User Authentication"
        assert set(resps[0].owns) == KNOWN
        assert resps[0].supports == ()
        # Back-compat property: covers = owns + supports
        assert set(resps[0].covers) == KNOWN

    def test_multiple_preserve_order(self):
        tree = _parse(
            "<requirements>"
            + _resp("Auth", "Identify callers.", ("feat_abc12345",))
            + _resp("Billing", "Bill accounts.", ("feat_def67890",))
            + _resp("Telemetry", "Record usage.", ("feat_xyz00001",))
            + "</requirements>"
        )
        resps = validate_requirements(tree, known_feature_ids=KNOWN)
        assert [r.name for r in resps] == ["Auth", "Billing", "Telemetry"]

    def test_feature_owned_by_one_supported_by_many(self):
        # Legitimate many-to-many: feat_abc12345 is owned by Auth
        # exclusively, but Telemetry and Billing both support it
        # (they run alongside authenticated flows).
        tree = _parse(
            "<requirements>"
            + _resp("Auth", "Identify.", ("feat_abc12345",), ())
            + _resp(
                "Telemetry",
                "Record.",
                ("feat_def67890",),
                ("feat_abc12345",),
            )
            + _resp(
                "Billing",
                "Bill.",
                ("feat_xyz00001",),
                ("feat_abc12345",),
            )
            + "</requirements>"
        )
        resps = validate_requirements(tree, known_feature_ids=KNOWN)
        # One owner, two supporters, no error.
        owners = [r.name for r in resps if "feat_abc12345" in r.owns]
        supporters = [r.name for r in resps if "feat_abc12345" in r.supports]
        assert owners == ["Auth"]
        assert sorted(supporters) == ["Billing", "Telemetry"]

    def test_supports_is_optional(self):
        # A responsibility may omit <supports> entirely.
        tree = _parse(
            "<requirements>"
            + _resp("Auth", "Identify.", ("feat_abc12345",))
            + _resp("Billing", "Bill.", ("feat_def67890", "feat_xyz00001"))
            + "</requirements>"
        )
        resps = validate_requirements(tree, known_feature_ids=KNOWN)
        assert all(r.supports == () for r in resps)

    def test_supports_may_be_empty_block(self):
        # An explicit empty <supports/> block is also fine — the
        # generator may emit one when the prompt instructs it to
        # always include the element.
        tree = _parse(
            "<requirements>"
            "<responsibility>"
            "<name>Auth</name><intent>Identify.</intent>"
            + _owns("feat_abc12345", "feat_def67890", "feat_xyz00001")
            + "<supports></supports>"
            "</responsibility>"
            "</requirements>"
        )
        resps = validate_requirements(tree, known_feature_ids=KNOWN)
        assert resps[0].supports == ()

    def test_multi_sentence_intent_preserved(self):
        tree = _parse(
            "<requirements>"
            + _resp(
                "Telemetry",
                "Record every LLM call. Flag latency spikes. Retain for 30 days.",
                ("feat_abc12345", "feat_def67890", "feat_xyz00001"),
            )
            + "</requirements>"
        )
        resps = validate_requirements(tree, known_feature_ids=KNOWN)
        assert resps[0].intent == "Record every LLM call. Flag latency spikes. Retain for 30 days."


class TestValidateRequirementsRootLevel:
    def test_wrong_root_tag_rejected(self):
        tree = TagNode(tag="features", text="", children=[])
        with pytest.raises(ValidationError, match="Expected root tag <requirements>"):
            validate_requirements(tree, known_feature_ids=set())

    def test_unknown_child_rejected(self):
        tree = _parse(
            "<requirements>"
            + _resp("Auth", "Ok.", ("feat_abc12345", "feat_def67890", "feat_xyz00001"))
            + "<widget>nope</widget>"
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
            + _owns("feat_abc12345")
            + "</responsibility>"
            "</requirements>"
        )
        with pytest.raises(ValidationError, match="missing a <name>"):
            validate_requirements(tree, known_feature_ids={"feat_abc12345"})

    def test_missing_intent_rejected(self):
        tree = _parse(
            "<requirements>"
            "<responsibility><name>Auth</name>" + _owns("feat_abc12345") + "</responsibility>"
            "</requirements>"
        )
        with pytest.raises(ValidationError, match="missing an <intent>"):
            validate_requirements(tree, known_feature_ids={"feat_abc12345"})

    def test_missing_owns_rejected(self):
        tree = _parse(
            "<requirements>"
            "<responsibility><name>Auth</name><intent>Ok.</intent></responsibility>"
            "</requirements>"
        )
        with pytest.raises(ValidationError, match="missing an <owns>"):
            validate_requirements(tree, known_feature_ids={"feat_abc12345"})

    def test_multiple_names_rejected(self):
        tree = _parse(
            "<requirements>"
            "<responsibility>"
            "<name>Auth</name><name>Auth2</name>"
            "<intent>Ok.</intent>" + _owns("feat_abc12345") + "</responsibility>"
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
            + _owns("feat_abc12345")
            + "</responsibility>"
            "</requirements>"
        )
        with pytest.raises(ValidationError, match="2 <intent> children"):
            validate_requirements(tree, known_feature_ids={"feat_abc12345"})

    def test_multiple_owns_rejected(self):
        tree = _parse(
            "<requirements>"
            "<responsibility>"
            "<name>Auth</name><intent>Ok.</intent>"
            + _owns("feat_abc12345")
            + _owns("feat_def67890")
            + "</responsibility>"
            "</requirements>"
        )
        with pytest.raises(ValidationError, match="2 <owns> children"):
            validate_requirements(tree, known_feature_ids={"feat_abc12345", "feat_def67890"})

    def test_multiple_supports_rejected(self):
        tree = _parse(
            "<requirements>"
            "<responsibility>"
            "<name>Auth</name><intent>Ok.</intent>"
            + _owns("feat_abc12345")
            + _supports("feat_def67890")
            + _supports("feat_xyz00001")
            + "</responsibility>"
            "</requirements>"
        )
        with pytest.raises(ValidationError, match="2 <supports> children"):
            validate_requirements(tree, known_feature_ids=KNOWN)

    def test_empty_name_rejected(self):
        tree = _parse(
            "<requirements>"
            "<responsibility><name> </name><intent>Ok.</intent>"
            + _owns("feat_abc12345")
            + "</responsibility>"
            "</requirements>"
        )
        with pytest.raises(ValidationError, match="empty <name>"):
            validate_requirements(tree, known_feature_ids={"feat_abc12345"})

    def test_empty_intent_rejected(self):
        tree = _parse(
            "<requirements>"
            "<responsibility><name>Auth</name><intent> </intent>"
            + _owns("feat_abc12345")
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
            + _owns("feat_abc12345")
            + "</responsibility>"
            "</requirements>"
        )
        with pytest.raises(ValidationError, match="unexpected child <rationale>"):
            validate_requirements(tree, known_feature_ids={"feat_abc12345"})


class TestValidateOwnsBlock:
    def test_empty_owns_rejected(self):
        tree = _parse(
            "<requirements>"
            "<responsibility><name>Auth</name><intent>Ok.</intent><owns></owns>"
            "</responsibility>"
            "</requirements>"
        )
        with pytest.raises(ValidationError, match="empty <owns>"):
            validate_requirements(tree, known_feature_ids={"feat_abc12345"})

    def test_owns_with_unknown_tag_rejected(self):
        tree = _parse(
            "<requirements>"
            "<responsibility><name>Auth</name><intent>Ok.</intent>"
            '<owns><feat id="feat_abc12345"/><widget/></owns>'
            "</responsibility>"
            "</requirements>"
        )
        with pytest.raises(ValidationError, match="unexpected.*<widget>"):
            validate_requirements(tree, known_feature_ids={"feat_abc12345"})

    def test_feat_missing_id_rejected(self):
        tree = _parse(
            "<requirements>"
            "<responsibility><name>Auth</name><intent>Ok.</intent>"
            "<owns><feat/></owns>"
            "</responsibility>"
            "</requirements>"
        )
        with pytest.raises(ValidationError, match="no id attribute"):
            validate_requirements(tree, known_feature_ids={"feat_abc12345"})

    def test_unknown_feature_id_rejected(self):
        tree = _parse(
            "<requirements>"
            "<responsibility><name>Auth</name><intent>Ok.</intent>"
            + _owns("feat_unknown1")
            + "</responsibility>"
            "</requirements>"
        )
        with pytest.raises(ValidationError, match="unknown feature id"):
            validate_requirements(tree, known_feature_ids={"feat_abc12345"})

    def test_duplicate_feature_in_same_owns_rejected(self):
        tree = _parse(
            "<requirements>"
            "<responsibility><name>Auth</name><intent>Ok.</intent>"
            + _owns("feat_abc12345", "feat_abc12345")
            + "</responsibility>"
            "</requirements>"
        )
        with pytest.raises(ValidationError, match="duplicate feature id"):
            validate_requirements(tree, known_feature_ids={"feat_abc12345"})


class TestSingleOwnerRule:
    """The single-owner rule — every feature has exactly one <owns> home."""

    def test_two_owners_for_one_feature_rejected(self):
        tree = _parse(
            "<requirements>"
            + _resp("Auth", "Identify.", ("feat_abc12345",))
            + _resp("Telemetry", "Record.", ("feat_abc12345",))
            + _resp("Billing", "Bill.", ("feat_def67890", "feat_xyz00001"))
            + "</requirements>"
        )
        with pytest.raises(ValidationError, match="multiple owners"):
            validate_requirements(tree, known_feature_ids=KNOWN)

    def test_feature_listed_only_in_supports_is_missing_owner(self):
        # feat_def67890 appears only in a supports block, never in
        # an owns block — counts as no owner.
        tree = _parse(
            "<requirements>"
            + _resp("Auth", "Identify.", ("feat_abc12345", "feat_xyz00001"), ("feat_def67890",))
            + "</requirements>"
        )
        with pytest.raises(ValidationError, match="features with no owner"):
            validate_requirements(tree, known_feature_ids=KNOWN)

    def test_feature_in_both_owns_and_supports_of_same_resp_rejected(self):
        tree = _parse(
            "<requirements>"
            + _resp(
                "Auth",
                "Identify.",
                ("feat_abc12345", "feat_def67890", "feat_xyz00001"),
                ("feat_abc12345",),
            )
            + "</requirements>"
        )
        with pytest.raises(ValidationError, match="in both <owns> and <supports>"):
            validate_requirements(tree, known_feature_ids=KNOWN)

    def test_feature_not_in_any_block_is_missing_owner(self):
        # feat_def67890 is declared known but appears nowhere.
        tree = _parse(
            "<requirements>" + _resp("Auth", "Identify.", ("feat_abc12345",)) + "</requirements>"
        )
        with pytest.raises(ValidationError, match="features with no owner"):
            validate_requirements(tree, known_feature_ids={"feat_abc12345", "feat_def67890"})

    def test_valid_distribution_passes(self):
        # feat_abc12345 owned by Auth, feat_def67890 owned by Billing;
        # Telemetry supports both without claiming ownership of either.
        tree = _parse(
            "<requirements>"
            + _resp("Auth", "Identify.", ("feat_abc12345",))
            + _resp("Billing", "Bill.", ("feat_def67890", "feat_xyz00001"))
            + _resp(
                "Telemetry",
                "Record.",
                ("feat_xyz00001",),  # can't own xyz if Billing does
            )
            + "</requirements>"
        )
        # Telemetry owning xyz would collide with Billing — adjust.
        tree = _parse(
            "<requirements>"
            + _resp("Auth", "Identify.", ("feat_abc12345",))
            + _resp("Billing", "Bill.", ("feat_def67890",))
            + _resp(
                "Telemetry",
                "Record.",
                ("feat_xyz00001",),
                ("feat_abc12345", "feat_def67890"),
            )
            + "</requirements>"
        )
        resps = validate_requirements(tree, known_feature_ids=KNOWN)
        assert len(resps) == 3
