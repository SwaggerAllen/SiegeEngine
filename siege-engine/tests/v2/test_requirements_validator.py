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


def _resp(name: str, feats: tuple[str, ...] = ()) -> str:
    """Build a single atomic <responsibility> fragment."""
    parts = ["<responsibility>", f"<name>{name}</name>", "<feats>"]
    parts.extend(f'<feat id="{fid}"/>' for fid in feats)
    parts.append("</feats></responsibility>")
    return "".join(parts)


# Fixed known-id set used by most happy-path tests.
KNOWN = {"feat_abc12345", "feat_def67890", "feat_xyz00001"}


class TestValidateRequirementsHappyPath:
    def test_single_responsibility(self):
        tree = _parse(
            "<requirements>"
            + _resp(
                "session-state lifecycle",
                ("feat_abc12345", "feat_def67890", "feat_xyz00001"),
            )
            + "</requirements>"
        )
        resps = validate_requirements(tree, known_feature_ids=KNOWN)
        assert len(resps) == 1
        assert resps[0].name == "session-state lifecycle"
        assert set(resps[0].feats) == KNOWN

    def test_multiple_preserve_order(self):
        tree = _parse(
            "<requirements>"
            + _resp("session token minting", ("feat_abc12345",))
            + _resp("invoice emission", ("feat_def67890",))
            + _resp("event log append", ("feat_xyz00001",))
            + "</requirements>"
        )
        resps = validate_requirements(tree, known_feature_ids=KNOWN)
        assert [r.name for r in resps] == [
            "session token minting",
            "invoice emission",
            "event log append",
        ]

    def test_feat_on_multiple_atoms_is_legal(self):
        # Many-to-many: feat_abc12345 tags three atoms legitimately
        # (login implicates session lifecycle, rate limit, and
        # password hash — all are real system-side concerns).
        tree = _parse(
            "<requirements>"
            + _resp("session lifecycle", ("feat_abc12345",))
            + _resp("rate limit buckets", ("feat_abc12345",))
            + _resp("password hash", ("feat_abc12345",))
            + _resp("invoice emission", ("feat_def67890",))
            + _resp("event log", ("feat_xyz00001",))
            + "</requirements>"
        )
        resps = validate_requirements(tree, known_feature_ids=KNOWN)
        taggers = [r.name for r in resps if "feat_abc12345" in r.feats]
        assert sorted(taggers) == [
            "password hash",
            "rate limit buckets",
            "session lifecycle",
        ]

    def test_empty_feats_legal_when_other_atoms_cover(self):
        # An atom may have <feats/> empty (system-emergent) as long
        # as every known feat is covered by *some* atom.
        tree = _parse(
            "<requirements>"
            + _resp(
                "ambient event log",  # no direct feature cause
                (),
            )
            + _resp(
                "the rest",
                ("feat_abc12345", "feat_def67890", "feat_xyz00001"),
            )
            + "</requirements>"
        )
        resps = validate_requirements(tree, known_feature_ids=KNOWN)
        assert resps[0].feats == ()
        assert set(resps[1].feats) == KNOWN


class TestValidateRequirementsRootLevel:
    def test_wrong_root_tag_rejected(self):
        tree = TagNode(tag="features", text="", children=[])
        with pytest.raises(ValidationError, match="Expected root tag <requirements>"):
            validate_requirements(tree, known_feature_ids=set())

    def test_unknown_child_rejected(self):
        tree = _parse(
            "<requirements>"
            + _resp("session lifecycle", ("feat_abc12345", "feat_def67890", "feat_xyz00001"))
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
            '<responsibility><feats><feat id="feat_abc12345"/></feats></responsibility>'
            "</requirements>"
        )
        with pytest.raises(ValidationError, match="missing a <name>"):
            validate_requirements(tree, known_feature_ids={"feat_abc12345"})

    def test_missing_feats_rejected(self):
        tree = _parse(
            "<requirements>"
            "<responsibility><name>session lifecycle</name></responsibility>"
            "</requirements>"
        )
        with pytest.raises(ValidationError, match="missing a <feats>"):
            validate_requirements(tree, known_feature_ids={"feat_abc12345"})

    def test_multiple_names_rejected(self):
        tree = _parse(
            "<requirements>"
            "<responsibility>"
            "<name>session lifecycle</name><name>session mgr</name>"
            '<feats><feat id="feat_abc12345"/></feats>'
            "</responsibility>"
            "</requirements>"
        )
        with pytest.raises(ValidationError, match="2 <name> children"):
            validate_requirements(tree, known_feature_ids={"feat_abc12345"})

    def test_multiple_feats_blocks_rejected(self):
        tree = _parse(
            "<requirements>"
            "<responsibility><name>session lifecycle</name>"
            '<feats><feat id="feat_abc12345"/></feats>'
            '<feats><feat id="feat_def67890"/></feats>'
            "</responsibility>"
            "</requirements>"
        )
        with pytest.raises(ValidationError, match="2 <feats> children"):
            validate_requirements(tree, known_feature_ids={"feat_abc12345", "feat_def67890"})

    def test_empty_name_rejected(self):
        tree = _parse(
            "<requirements>"
            "<responsibility><name> </name>"
            '<feats><feat id="feat_abc12345"/></feats>'
            "</responsibility>"
            "</requirements>"
        )
        with pytest.raises(ValidationError, match="empty <name>"):
            validate_requirements(tree, known_feature_ids={"feat_abc12345"})

    def test_unknown_child_in_responsibility_rejected(self):
        tree = _parse(
            "<requirements>"
            "<responsibility>"
            "<name>session lifecycle</name>"
            "<rationale>should not be here</rationale>"
            '<feats><feat id="feat_abc12345"/></feats>'
            "</responsibility>"
            "</requirements>"
        )
        with pytest.raises(ValidationError, match="unexpected child <rationale>"):
            validate_requirements(tree, known_feature_ids={"feat_abc12345"})


class TestValidateFeatsBlock:
    def test_empty_feats_legal(self):
        # An atom may legitimately have <feats/> empty — system-
        # emergent concern with no direct feature cause. Coverage
        # is enforced at the document level, so this only passes
        # when all known feats appear on other atoms.
        tree = _parse(
            "<requirements>"
            "<responsibility><name>ambient event log</name><feats></feats></responsibility>"
            + _resp("the rest", ("feat_abc12345",))
            + "</requirements>"
        )
        resps = validate_requirements(tree, known_feature_ids={"feat_abc12345"})
        assert resps[0].feats == ()

    def test_feats_with_unknown_tag_rejected(self):
        tree = _parse(
            "<requirements>"
            "<responsibility><name>session lifecycle</name>"
            '<feats><feat id="feat_abc12345"/><widget/></feats>'
            "</responsibility>"
            "</requirements>"
        )
        with pytest.raises(ValidationError, match="unexpected.*<widget>"):
            validate_requirements(tree, known_feature_ids={"feat_abc12345"})

    def test_feat_missing_id_rejected(self):
        tree = _parse(
            "<requirements>"
            "<responsibility><name>session lifecycle</name>"
            "<feats><feat/></feats>"
            "</responsibility>"
            "</requirements>"
        )
        with pytest.raises(ValidationError, match="no id attribute"):
            validate_requirements(tree, known_feature_ids={"feat_abc12345"})

    def test_unknown_feature_id_rejected(self):
        tree = _parse(
            "<requirements>"
            "<responsibility><name>session lifecycle</name>"
            '<feats><feat id="feat_unknown1"/></feats>'
            "</responsibility>"
            "</requirements>"
        )
        with pytest.raises(ValidationError, match="unknown feature id"):
            validate_requirements(tree, known_feature_ids={"feat_abc12345"})

    def test_duplicate_feature_in_same_feats_rejected(self):
        tree = _parse(
            "<requirements>"
            "<responsibility><name>session lifecycle</name>"
            '<feats><feat id="feat_abc12345"/><feat id="feat_abc12345"/></feats>'
            "</responsibility>"
            "</requirements>"
        )
        with pytest.raises(ValidationError, match="duplicate feature id"):
            validate_requirements(tree, known_feature_ids={"feat_abc12345"})


class TestNameDedup:
    """No two atoms may share a normalized name."""

    def test_literal_duplicate_rejected(self):
        tree = _parse(
            "<requirements>"
            + _resp("session-state lifecycle", ("feat_abc12345",))
            + _resp("session-state lifecycle", ("feat_def67890",))
            + _resp("event log", ("feat_xyz00001",))
            + "</requirements>"
        )
        with pytest.raises(ValidationError, match="duplicate names"):
            validate_requirements(tree, known_feature_ids=KNOWN)

    def test_whitespace_and_case_normalized(self):
        tree = _parse(
            "<requirements>"
            + _resp("Session State Lifecycle", ("feat_abc12345",))
            + _resp("session state  lifecycle ", ("feat_def67890",))
            + _resp("event log", ("feat_xyz00001",))
            + "</requirements>"
        )
        with pytest.raises(ValidationError, match="duplicate names"):
            validate_requirements(tree, known_feature_ids=KNOWN)


class TestFeatCoverageEnforced:
    """Every known feat must appear in at least one atom's <feats>."""

    def test_uncovered_feat_raises(self):
        tree = _parse(
            "<requirements>"
            + _resp("session lifecycle", ("feat_abc12345",))
            + _resp("invoice emission", ("feat_def67890",))
            # feat_xyz00001 is never tagged — rotation is incomplete.
            + "</requirements>"
        )
        with pytest.raises(ValidationError) as excinfo:
            validate_requirements(tree, known_feature_ids=KNOWN)
        assert "feat_xyz00001" in str(excinfo.value)
        assert "no atom tag" in str(excinfo.value)

    def test_full_coverage_passes(self):
        tree = _parse(
            "<requirements>"
            + _resp("session lifecycle", ("feat_abc12345",))
            + _resp("invoice emission", ("feat_def67890",))
            + _resp("event log", ("feat_xyz00001",))
            + "</requirements>"
        )
        resps = validate_requirements(tree, known_feature_ids=KNOWN)
        assert len(resps) == 3

    def test_feat_on_two_atoms_is_legal(self):
        # Many-to-many satisfies coverage as long as each feat
        # appears at least once. Two atoms tagging the same feat
        # is expected for cross-cutting features.
        tree = _parse(
            "<requirements>"
            + _resp("session lifecycle", ("feat_abc12345", "feat_def67890"))
            + _resp("rate limit buckets", ("feat_abc12345",))
            + _resp("invoice emission", ("feat_xyz00001",))
            + "</requirements>"
        )
        resps = validate_requirements(tree, known_feature_ids=KNOWN)
        assert len(resps) == 3

    def test_empty_feats_atom_does_not_satisfy_coverage(self):
        # An atom with empty <feats/> contributes nothing toward
        # coverage; if it's the only atom, every known feat is
        # uncovered.
        tree = _parse(
            "<requirements>"
            "<responsibility><name>ambient event log</name><feats></feats></responsibility>"
            "</requirements>"
        )
        with pytest.raises(ValidationError, match="no atom tag"):
            validate_requirements(tree, known_feature_ids={"feat_abc12345"})
