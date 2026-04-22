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


def _scope(*phrases: str) -> str:
    return "<scope>" + "".join(f"<item>{p}</item>" for p in phrases) + "</scope>"


def _failure(text: str) -> str:
    return f"<failure-surface>{text}</failure-surface>"


def _resp(
    name: str,
    scope_phrases: tuple[str, ...],
    owns_ids: tuple[str, ...],
    supports_ids: tuple[str, ...] = (),
    failure_surface: str | None = None,
    does_not_own: tuple[tuple[str, str], ...] = (),
) -> str:
    """Build a single <responsibility> fragment for test fixtures.

    ``does_not_own`` is an iterable of ``(phrase, to_name)`` pairs.
    ``failure_surface`` defaults to a minimal valid sentence.
    """
    parts = [
        "<responsibility>",
        f"<name>{name}</name>",
        _scope(*scope_phrases),
    ]
    if does_not_own:
        parts.append("<does-not-own>")
        for phrase, to in does_not_own:
            parts.append(f'<defers to="{to}">{phrase}</defers>')
        parts.append("</does-not-own>")
    parts.append(_failure(failure_surface or f"{name} failure surface."))
    parts.append(_owns(*owns_ids))
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
                ("session-state lifecycle",),
                ("feat_abc12345", "feat_def67890", "feat_xyz00001"),
            )
            + "</requirements>"
        )
        resps = validate_requirements(tree, known_feature_ids=KNOWN)
        assert len(resps) == 1
        assert resps[0].name == "User Authentication"
        assert set(resps[0].owns) == KNOWN
        assert resps[0].supports == ()
        assert resps[0].scope == ("session-state lifecycle",)
        assert resps[0].failure_surface == "User Authentication failure surface."
        assert resps[0].does_not_own == ()
        # Back-compat property: covers = owns + supports
        assert set(resps[0].covers) == KNOWN

    def test_multiple_preserve_order(self):
        tree = _parse(
            "<requirements>"
            + _resp("Auth", ("auth scope",), ("feat_abc12345",))
            + _resp("Billing", ("billing scope",), ("feat_def67890",))
            + _resp("Telemetry", ("telemetry scope",), ("feat_xyz00001",))
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
            + _resp("Auth", ("auth scope",), ("feat_abc12345",), ())
            + _resp(
                "Telemetry",
                ("telemetry scope",),
                ("feat_def67890",),
                ("feat_abc12345",),
            )
            + _resp(
                "Billing",
                ("billing scope",),
                ("feat_xyz00001",),
                ("feat_abc12345",),
            )
            + "</requirements>"
        )
        resps = validate_requirements(tree, known_feature_ids=KNOWN)
        owners = [r.name for r in resps if "feat_abc12345" in r.owns]
        supporters = [r.name for r in resps if "feat_abc12345" in r.supports]
        assert owners == ["Auth"]
        assert sorted(supporters) == ["Billing", "Telemetry"]

    def test_supports_is_optional(self):
        tree = _parse(
            "<requirements>"
            + _resp("Auth", ("auth scope",), ("feat_abc12345",))
            + _resp("Billing", ("billing scope",), ("feat_def67890", "feat_xyz00001"))
            + "</requirements>"
        )
        resps = validate_requirements(tree, known_feature_ids=KNOWN)
        assert all(r.supports == () for r in resps)

    def test_supports_may_be_empty_block(self):
        tree = _parse(
            "<requirements>"
            "<responsibility>"
            "<name>Auth</name>"
            + _scope("auth scope")
            + _failure("Auth fails.")
            + _owns("feat_abc12345", "feat_def67890", "feat_xyz00001")
            + "<supports></supports>"
            "</responsibility>"
            "</requirements>"
        )
        resps = validate_requirements(tree, known_feature_ids=KNOWN)
        assert resps[0].supports == ()

    def test_multiple_scope_items(self):
        tree = _parse(
            "<requirements>"
            + _resp(
                "Telemetry",
                ("record every LLM call", "latency spikes flagged", "30-day retention"),
                ("feat_abc12345", "feat_def67890", "feat_xyz00001"),
            )
            + "</requirements>"
        )
        resps = validate_requirements(tree, known_feature_ids=KNOWN)
        assert resps[0].scope == (
            "record every LLM call",
            "latency spikes flagged",
            "30-day retention",
        )


class TestValidateRequirementsRootLevel:
    def test_wrong_root_tag_rejected(self):
        tree = TagNode(tag="features", text="", children=[])
        with pytest.raises(ValidationError, match="Expected root tag <requirements>"):
            validate_requirements(tree, known_feature_ids=set())

    def test_unknown_child_rejected(self):
        tree = _parse(
            "<requirements>"
            + _resp("Auth", ("scope",), ("feat_abc12345", "feat_def67890", "feat_xyz00001"))
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
            "<responsibility>"
            + _scope("scope")
            + _failure("fails")
            + _owns("feat_abc12345")
            + "</responsibility>"
            "</requirements>"
        )
        with pytest.raises(ValidationError, match="missing a <name>"):
            validate_requirements(tree, known_feature_ids={"feat_abc12345"})

    def test_missing_scope_rejected(self):
        tree = _parse(
            "<requirements>"
            "<responsibility><name>Auth</name>"
            + _failure("fails")
            + _owns("feat_abc12345")
            + "</responsibility>"
            "</requirements>"
        )
        with pytest.raises(ValidationError, match="missing a <scope>"):
            validate_requirements(tree, known_feature_ids={"feat_abc12345"})

    def test_missing_failure_surface_rejected(self):
        tree = _parse(
            "<requirements>"
            "<responsibility><name>Auth</name>"
            + _scope("scope")
            + _owns("feat_abc12345")
            + "</responsibility>"
            "</requirements>"
        )
        with pytest.raises(ValidationError, match="missing a <failure-surface>"):
            validate_requirements(tree, known_feature_ids={"feat_abc12345"})

    def test_missing_owns_rejected(self):
        tree = _parse(
            "<requirements>"
            "<responsibility><name>Auth</name>"
            + _scope("scope")
            + _failure("fails")
            + "</responsibility>"
            "</requirements>"
        )
        with pytest.raises(ValidationError, match="missing an <owns>"):
            validate_requirements(tree, known_feature_ids={"feat_abc12345"})

    def test_multiple_names_rejected(self):
        tree = _parse(
            "<requirements>"
            "<responsibility>"
            "<name>Auth</name><name>Auth2</name>"
            + _scope("scope")
            + _failure("fails")
            + _owns("feat_abc12345")
            + "</responsibility>"
            "</requirements>"
        )
        with pytest.raises(ValidationError, match="2 <name> children"):
            validate_requirements(tree, known_feature_ids={"feat_abc12345"})

    def test_multiple_scope_blocks_rejected(self):
        tree = _parse(
            "<requirements>"
            "<responsibility><name>Auth</name>"
            + _scope("a")
            + _scope("b")
            + _failure("fails")
            + _owns("feat_abc12345")
            + "</responsibility>"
            "</requirements>"
        )
        with pytest.raises(ValidationError, match="2 <scope> children"):
            validate_requirements(tree, known_feature_ids={"feat_abc12345"})

    def test_multiple_owns_rejected(self):
        tree = _parse(
            "<requirements>"
            "<responsibility><name>Auth</name>"
            + _scope("scope")
            + _failure("fails")
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
            "<responsibility><name>Auth</name>"
            + _scope("scope")
            + _failure("fails")
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
            "<responsibility><name> </name>"
            + _scope("scope")
            + _failure("fails")
            + _owns("feat_abc12345")
            + "</responsibility>"
            "</requirements>"
        )
        with pytest.raises(ValidationError, match="empty <name>"):
            validate_requirements(tree, known_feature_ids={"feat_abc12345"})

    def test_empty_scope_rejected(self):
        tree = _parse(
            "<requirements>"
            "<responsibility><name>Auth</name>"
            "<scope></scope>" + _failure("fails") + _owns("feat_abc12345") + "</responsibility>"
            "</requirements>"
        )
        with pytest.raises(ValidationError, match="empty <scope>"):
            validate_requirements(tree, known_feature_ids={"feat_abc12345"})

    def test_empty_scope_item_rejected(self):
        tree = _parse(
            "<requirements>"
            "<responsibility><name>Auth</name>"
            "<scope><item> </item></scope>"
            + _failure("fails")
            + _owns("feat_abc12345")
            + "</responsibility>"
            "</requirements>"
        )
        with pytest.raises(ValidationError, match="empty <item>"):
            validate_requirements(tree, known_feature_ids={"feat_abc12345"})

    def test_empty_failure_surface_rejected(self):
        tree = _parse(
            "<requirements>"
            "<responsibility><name>Auth</name>"
            + _scope("scope")
            + "<failure-surface> </failure-surface>"
            + _owns("feat_abc12345")
            + "</responsibility>"
            "</requirements>"
        )
        with pytest.raises(ValidationError, match="empty <failure-surface>"):
            validate_requirements(tree, known_feature_ids={"feat_abc12345"})

    def test_unknown_child_in_responsibility_rejected(self):
        tree = _parse(
            "<requirements>"
            "<responsibility>"
            "<name>Auth</name>"
            + _scope("scope")
            + _failure("fails")
            + "<rationale>should not be here</rationale>"
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
            "<responsibility><name>Auth</name>"
            + _scope("scope")
            + _failure("fails")
            + "<owns></owns>"
            "</responsibility>"
            "</requirements>"
        )
        with pytest.raises(ValidationError, match="empty <owns>"):
            validate_requirements(tree, known_feature_ids={"feat_abc12345"})

    def test_owns_with_unknown_tag_rejected(self):
        tree = _parse(
            "<requirements>"
            "<responsibility><name>Auth</name>"
            + _scope("scope")
            + _failure("fails")
            + '<owns><feat id="feat_abc12345"/><widget/></owns>'
            "</responsibility>"
            "</requirements>"
        )
        with pytest.raises(ValidationError, match="unexpected.*<widget>"):
            validate_requirements(tree, known_feature_ids={"feat_abc12345"})

    def test_feat_missing_id_rejected(self):
        tree = _parse(
            "<requirements>"
            "<responsibility><name>Auth</name>"
            + _scope("scope")
            + _failure("fails")
            + "<owns><feat/></owns>"
            "</responsibility>"
            "</requirements>"
        )
        with pytest.raises(ValidationError, match="no id attribute"):
            validate_requirements(tree, known_feature_ids={"feat_abc12345"})

    def test_unknown_feature_id_rejected(self):
        tree = _parse(
            "<requirements>"
            "<responsibility><name>Auth</name>"
            + _scope("scope")
            + _failure("fails")
            + _owns("feat_unknown1")
            + "</responsibility>"
            "</requirements>"
        )
        with pytest.raises(ValidationError, match="unknown feature id"):
            validate_requirements(tree, known_feature_ids={"feat_abc12345"})

    def test_duplicate_feature_in_same_owns_rejected(self):
        tree = _parse(
            "<requirements>"
            "<responsibility><name>Auth</name>"
            + _scope("scope")
            + _failure("fails")
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
            + _resp("Auth", ("auth scope",), ("feat_abc12345",))
            + _resp("Telemetry", ("telemetry scope",), ("feat_abc12345",))
            + _resp(
                "Billing",
                ("billing scope",),
                ("feat_def67890", "feat_xyz00001"),
            )
            + "</requirements>"
        )
        with pytest.raises(ValidationError, match="multiple owners"):
            validate_requirements(tree, known_feature_ids=KNOWN)

    def test_feature_listed_only_in_supports_is_missing_owner(self):
        tree = _parse(
            "<requirements>"
            + _resp(
                "Auth",
                ("auth scope",),
                ("feat_abc12345", "feat_xyz00001"),
                ("feat_def67890",),
            )
            + "</requirements>"
        )
        with pytest.raises(ValidationError, match="features with no owner"):
            validate_requirements(tree, known_feature_ids=KNOWN)

    def test_feature_in_both_owns_and_supports_of_same_resp_rejected(self):
        tree = _parse(
            "<requirements>"
            + _resp(
                "Auth",
                ("auth scope",),
                ("feat_abc12345", "feat_def67890", "feat_xyz00001"),
                ("feat_abc12345",),
            )
            + "</requirements>"
        )
        with pytest.raises(ValidationError, match="in both <owns> and <supports>"):
            validate_requirements(tree, known_feature_ids=KNOWN)

    def test_feature_not_in_any_block_is_missing_owner(self):
        tree = _parse(
            "<requirements>"
            + _resp("Auth", ("auth scope",), ("feat_abc12345",))
            + "</requirements>"
        )
        with pytest.raises(ValidationError, match="features with no owner"):
            validate_requirements(tree, known_feature_ids={"feat_abc12345", "feat_def67890"})

    def test_valid_distribution_passes(self):
        tree = _parse(
            "<requirements>"
            + _resp("Auth", ("auth scope",), ("feat_abc12345",))
            + _resp("Billing", ("billing scope",), ("feat_def67890",))
            + _resp(
                "Telemetry",
                ("telemetry scope",),
                ("feat_xyz00001",),
                ("feat_abc12345", "feat_def67890"),
            )
            + "</requirements>"
        )
        resps = validate_requirements(tree, known_feature_ids=KNOWN)
        assert len(resps) == 3


class TestScopeDedup:
    """Scope phrases must be unique across responsibilities."""

    def test_literal_duplicate_rejected(self):
        tree = _parse(
            "<requirements>"
            + _resp("Auth", ("session-state lifecycle",), ("feat_abc12345",))
            + _resp("Billing", ("session-state lifecycle",), ("feat_def67890",))
            + _resp("Telemetry", ("unique",), ("feat_xyz00001",))
            + "</requirements>"
        )
        with pytest.raises(ValidationError, match="claimed by multiple"):
            validate_requirements(tree, known_feature_ids=KNOWN)

    def test_whitespace_and_case_normalized(self):
        # "Session State Lifecycle" vs "session state lifecycle " — same
        # phrase under normalize, so should collide.
        tree = _parse(
            "<requirements>"
            + _resp("Auth", ("Session State Lifecycle",), ("feat_abc12345",))
            + _resp(
                "Billing",
                ("session state  lifecycle ",),
                ("feat_def67890",),
            )
            + _resp("Telemetry", ("unique",), ("feat_xyz00001",))
            + "</requirements>"
        )
        with pytest.raises(ValidationError, match="claimed by multiple"):
            validate_requirements(tree, known_feature_ids=KNOWN)

    def test_intra_responsibility_duplicate_rejected(self):
        tree = _parse(
            "<requirements>"
            "<responsibility><name>Auth</name>"
            + _scope("session lifecycle", "session lifecycle")
            + _failure("fails")
            + _owns("feat_abc12345", "feat_def67890", "feat_xyz00001")
            + "</responsibility>"
            "</requirements>"
        )
        with pytest.raises(ValidationError, match="duplicate <item>"):
            validate_requirements(tree, known_feature_ids=KNOWN)


class TestDoesNotOwnCrossReference:
    """<defers to="X"> must resolve to another resp's name."""

    def test_valid_cross_reference_passes(self):
        tree = _parse(
            "<requirements>"
            + _resp(
                "Auth",
                ("auth scope",),
                ("feat_abc12345",),
                does_not_own=(("permission checks", "Authorization"),),
            )
            + _resp(
                "Authorization",
                ("permission mapping",),
                ("feat_def67890", "feat_xyz00001"),
            )
            + "</requirements>"
        )
        resps = validate_requirements(tree, known_feature_ids=KNOWN)
        assert resps[0].does_not_own[0].scope == "permission checks"
        assert resps[0].does_not_own[0].to == "Authorization"

    def test_unresolved_reference_rejected(self):
        tree = _parse(
            "<requirements>"
            + _resp(
                "Auth",
                ("auth scope",),
                ("feat_abc12345",),
                does_not_own=(("permission checks", "NonexistentResp"),),
            )
            + _resp(
                "Billing",
                ("billing scope",),
                ("feat_def67890", "feat_xyz00001"),
            )
            + "</requirements>"
        )
        with pytest.raises(ValidationError, match="unknown responsibilities"):
            validate_requirements(tree, known_feature_ids=KNOWN)

    def test_empty_defers_body_rejected(self):
        tree = _parse(
            "<requirements>"
            "<responsibility><name>Auth</name>"
            + _scope("scope")
            + '<does-not-own><defers to="Other"></defers></does-not-own>'
            + _failure("fails")
            + _owns("feat_abc12345", "feat_def67890", "feat_xyz00001")
            + "</responsibility>"
            "</requirements>"
        )
        with pytest.raises(ValidationError, match="empty <defers> body"):
            validate_requirements(tree, known_feature_ids=KNOWN)

    def test_defers_missing_to_rejected(self):
        tree = _parse(
            "<requirements>"
            "<responsibility><name>Auth</name>"
            + _scope("scope")
            + "<does-not-own><defers>something</defers></does-not-own>"
            + _failure("fails")
            + _owns("feat_abc12345", "feat_def67890", "feat_xyz00001")
            + "</responsibility>"
            "</requirements>"
        )
        with pytest.raises(ValidationError, match="no ``to`` attribute"):
            validate_requirements(tree, known_feature_ids=KNOWN)
