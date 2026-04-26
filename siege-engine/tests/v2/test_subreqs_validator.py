"""Tests for backend.graph.parsers.validators.validate_subrequirements."""

from __future__ import annotations

import pytest

from backend.graph.parsers.validators import (
    ValidationError,
    validate_subrequirements,
)
from backend.graph.parsers.xml_sections import TagNode, extract_tag_tree


def _parse(raw: str) -> TagNode:
    return extract_tag_tree(raw, "subrequirements")


def _derived(*resp_ids: str) -> str:
    return "<derived-from>" + "".join(f'<resp id="{rid}"/>' for rid in resp_ids) + "</derived-from>"


def _feats(*feat_ids: str) -> str:
    return "<feats>" + "".join(f'<feat id="{fid}"/>' for fid in feat_ids) + "</feats>"


# Default fixtures for the typical happy-path tests. Two parent
# resps + two feats is enough to exercise coverage + leak checks.
KNOWN_PARENTS = {"resp_parent001", "resp_parent002"}
KNOWN_FEATS = {"feat_alpha001", "feat_beta0002"}


def _validate(raw: str, *, parents=KNOWN_PARENTS, feats=KNOWN_FEATS):
    return validate_subrequirements(
        _parse(raw),
        known_parent_resp_ids=parents,
        known_feat_ids=feats,
    )


class TestHappyPath:
    def test_single_subresp(self):
        subresps = _validate(
            "<subrequirements>"
            "<subresponsibility>"
            "<name>Card Tokenization</name>"
            + _feats("feat_alpha001", "feat_beta0002")
            + _derived("resp_parent001", "resp_parent002")
            + "</subresponsibility>"
            "</subrequirements>"
        )
        assert len(subresps) == 1
        assert subresps[0].name == "Card Tokenization"
        assert set(subresps[0].feats) == KNOWN_FEATS
        assert set(subresps[0].derived_from) == KNOWN_PARENTS

    def test_multiple_preserve_order(self):
        subresps = _validate(
            "<subrequirements>"
            "<subresponsibility><name>A</name>"
            + _feats("feat_alpha001")
            + _derived("resp_parent001")
            + "</subresponsibility>"
            "<subresponsibility><name>B</name>"
            + _feats("feat_beta0002")
            + _derived("resp_parent002")
            + "</subresponsibility>"
            "</subrequirements>"
        )
        assert [s.name for s in subresps] == ["A", "B"]

    def test_many_to_many_parent_shared_across_subresps(self):
        subresps = _validate(
            "<subrequirements>"
            "<subresponsibility><name>Retry Scheduling</name>"
            + _feats("feat_alpha001", "feat_beta0002")
            + _derived("resp_parent001", "resp_parent002")
            + "</subresponsibility>"
            "<subresponsibility><name>Backoff</name>"
            + _feats("feat_alpha001")
            + _derived("resp_parent001")
            + "</subresponsibility>"
            "</subrequirements>"
        )
        assert "resp_parent001" in subresps[0].derived_from
        assert "resp_parent001" in subresps[1].derived_from

    def test_empty_feats_legal_for_component_emergent(self):
        # A component-emergent atom (no direct feature cause) may
        # carry empty <feats/>, as long as the union of feats
        # across all atoms still covers every in-scope feat.
        subresps = _validate(
            "<subrequirements>"
            "<subresponsibility><name>Token Cache Eviction</name>"
            + "<feats/>"
            + _derived("resp_parent001")
            + "</subresponsibility>"
            "<subresponsibility><name>Coverage Atom</name>"
            + _feats("feat_alpha001", "feat_beta0002")
            + _derived("resp_parent002")
            + "</subresponsibility>"
            "</subrequirements>"
        )
        assert len(subresps) == 2
        assert subresps[0].feats == ()
        assert set(subresps[1].feats) == KNOWN_FEATS


class TestRootLevel:
    def test_wrong_root_rejected(self):
        tree = TagNode(tag="requirements", text="", children=[])
        with pytest.raises(ValidationError, match="Expected root tag <subrequirements>"):
            validate_subrequirements(tree, known_parent_resp_ids=set(), known_feat_ids=set())

    def test_unknown_child_rejected(self):
        with pytest.raises(ValidationError, match="unexpected child <widget>"):
            _validate(
                "<subrequirements>"
                "<subresponsibility><name>A</name>"
                + _feats("feat_alpha001", "feat_beta0002")
                + _derived("resp_parent001", "resp_parent002")
                + "</subresponsibility>"
                "<widget>nope</widget>"
                "</subrequirements>"
            )

    def test_empty_block_legal(self):
        # Empty <subrequirements/> is legal under the new
        # decomposition-on-demand semantics — every parent resp
        # gets assigned wholesale to a subcomponent at comparch
        # time. No coverage failure to report.
        result = validate_subrequirements(
            _parse("<subrequirements></subrequirements>"),
            known_parent_resp_ids={"resp_parent001"},
            known_feat_ids={"feat_alpha001"},
        )
        assert result == []


class TestSubrespStructure:
    def test_missing_name_rejected(self):
        with pytest.raises(ValidationError, match="missing a <name>"):
            _validate(
                "<subrequirements>"
                "<subresponsibility>"
                + _feats("feat_alpha001", "feat_beta0002")
                + _derived("resp_parent001", "resp_parent002")
                + "</subresponsibility>"
                "</subrequirements>"
            )

    def test_missing_feats_rejected(self):
        with pytest.raises(ValidationError, match="missing a <feats>"):
            _validate(
                "<subrequirements>"
                "<subresponsibility><name>A</name>"
                + _derived("resp_parent001", "resp_parent002")
                + "</subresponsibility>"
                "</subrequirements>"
            )

    def test_missing_derived_from_rejected(self):
        with pytest.raises(ValidationError, match="missing a <derived-from>"):
            _validate(
                "<subrequirements>"
                "<subresponsibility><name>A</name>"
                + _feats("feat_alpha001", "feat_beta0002")
                + "</subresponsibility>"
                "</subrequirements>"
            )

    def test_empty_name_rejected(self):
        with pytest.raises(ValidationError, match="empty <name>"):
            _validate(
                "<subrequirements>"
                "<subresponsibility><name> </name>"
                + _feats("feat_alpha001", "feat_beta0002")
                + _derived("resp_parent001", "resp_parent002")
                + "</subresponsibility>"
                "</subrequirements>"
            )

    def test_unknown_intent_child_rejected(self):
        # Stray <intent> from the old grammar is now a parse error
        # — a defence-in-depth check that the validator doesn't
        # silently tolerate the dropped tag if a stale prompt or a
        # human emits it.
        with pytest.raises(ValidationError, match="unexpected child <intent>"):
            _validate(
                "<subrequirements>"
                "<subresponsibility><name>A</name><intent>old shape</intent>"
                + _feats("feat_alpha001", "feat_beta0002")
                + _derived("resp_parent001", "resp_parent002")
                + "</subresponsibility>"
                "</subrequirements>"
            )


class TestFeatsValidation:
    def test_unknown_feat_id_rejected(self):
        with pytest.raises(ValidationError, match="unknown feature id 'feat_strange1'"):
            _validate(
                "<subrequirements>"
                "<subresponsibility><name>A</name>"
                + _feats("feat_strange1")
                + _derived("resp_parent001", "resp_parent002")
                + "</subresponsibility>"
                "</subrequirements>"
            )

    def test_duplicate_feat_in_same_block_rejected(self):
        with pytest.raises(ValidationError, match="duplicate feature id 'feat_alpha001'"):
            _validate(
                "<subrequirements>"
                "<subresponsibility><name>A</name>"
                + _feats("feat_alpha001", "feat_alpha001", "feat_beta0002")
                + _derived("resp_parent001", "resp_parent002")
                + "</subresponsibility>"
                "</subrequirements>"
            )

    def test_feat_missing_id_rejected(self):
        with pytest.raises(ValidationError, match="<feat> entry.*with no id attribute"):
            _validate(
                "<subrequirements>"
                "<subresponsibility><name>A</name>"
                "<feats><feat/></feats>"
                + _derived("resp_parent001", "resp_parent002")
                + "</subresponsibility>"
                "</subrequirements>"
            )


class TestDerivedFromValidation:
    def test_empty_derived_from_rejected(self):
        with pytest.raises(ValidationError, match="empty <derived-from>"):
            _validate(
                "<subrequirements>"
                "<subresponsibility><name>A</name>"
                + _feats("feat_alpha001", "feat_beta0002")
                + "<derived-from></derived-from>"
                + "</subresponsibility>"
                "</subrequirements>"
            )

    def test_derived_from_unknown_tag_rejected(self):
        with pytest.raises(ValidationError, match="unexpected.*<widget>"):
            _validate(
                "<subrequirements>"
                "<subresponsibility><name>A</name>"
                + _feats("feat_alpha001", "feat_beta0002")
                + '<derived-from><resp id="resp_parent001"/><widget/></derived-from>'
                + "</subresponsibility>"
                "</subrequirements>"
            )

    def test_resp_missing_id_rejected(self):
        with pytest.raises(ValidationError, match="no id attribute"):
            _validate(
                "<subrequirements>"
                "<subresponsibility><name>A</name>"
                + _feats("feat_alpha001", "feat_beta0002")
                + "<derived-from><resp/></derived-from>"
                + "</subresponsibility>"
                "</subrequirements>"
            )

    def test_duplicate_resp_in_same_block_rejected(self):
        with pytest.raises(ValidationError, match="duplicate id"):
            _validate(
                "<subrequirements>"
                "<subresponsibility><name>A</name>"
                + _feats("feat_alpha001", "feat_beta0002")
                + _derived("resp_parent001", "resp_parent001")
                + "</subresponsibility>"
                "</subrequirements>"
            )

    def test_cross_component_leak_rejected(self):
        with pytest.raises(ValidationError, match="Cross-component leaks are forbidden"):
            _validate(
                "<subrequirements>"
                "<subresponsibility><name>A</name>"
                + _feats("feat_alpha001", "feat_beta0002")
                + _derived("resp_strange01")
                + "</subresponsibility>"
                "</subrequirements>"
            )


class TestSelectiveDecomposition:
    """Subresps are an optional decomposition. Parents not
    referenced by any subresp will be assigned wholesale to a
    subcomponent at comparch time — no coverage rule applies."""

    def test_uncovered_parent_legal(self):
        # parent001 has a subresp; parent002 has none and is
        # expected to flow through wholesale.
        subresps = _validate(
            "<subrequirements>"
            "<subresponsibility><name>A</name>"
            + _feats("feat_alpha001", "feat_beta0002")
            + _derived("resp_parent001")
            + "</subresponsibility>"
            "</subrequirements>"
        )
        assert len(subresps) == 1

    def test_uncovered_feat_legal(self):
        # feat_alpha001 tagged on a subresp; feat_beta0002 not
        # tagged — that's fine, it falls through with its parent.
        subresps = _validate(
            "<subrequirements>"
            "<subresponsibility><name>A</name>"
            + _feats("feat_alpha001")
            + _derived("resp_parent001")
            + "</subresponsibility>"
            "<subresponsibility><name>B</name>"
            + _feats("feat_alpha001")
            + _derived("resp_parent002")
            + "</subresponsibility>"
            "</subrequirements>"
        )
        assert len(subresps) == 2

    def test_union_coverage_accepted(self):
        # Both axes covered by the union of two atoms.
        subresps = _validate(
            "<subrequirements>"
            "<subresponsibility><name>A</name>"
            + _feats("feat_alpha001")
            + _derived("resp_parent001")
            + "</subresponsibility>"
            "<subresponsibility><name>B</name>"
            + _feats("feat_beta0002")
            + _derived("resp_parent002")
            + "</subresponsibility>"
            "</subrequirements>"
        )
        assert len(subresps) == 2


class TestNameDedup:
    def test_collision_rejected(self):
        with pytest.raises(ValidationError, match="duplicate names"):
            _validate(
                "<subrequirements>"
                "<subresponsibility><name>Card Tokenization</name>"
                + _feats("feat_alpha001")
                + _derived("resp_parent001")
                + "</subresponsibility>"
                "<subresponsibility><name>card  tokenization</name>"
                + _feats("feat_beta0002")
                + _derived("resp_parent002")
                + "</subresponsibility>"
                "</subrequirements>"
            )

    def test_distinct_names_accepted(self):
        subresps = _validate(
            "<subrequirements>"
            "<subresponsibility><name>Tokenize</name>"
            + _feats("feat_alpha001")
            + _derived("resp_parent001")
            + "</subresponsibility>"
            "<subresponsibility><name>Backoff</name>"
            + _feats("feat_beta0002")
            + _derived("resp_parent002")
            + "</subresponsibility>"
            "</subrequirements>"
        )
        assert {s.name for s in subresps} == {"Tokenize", "Backoff"}
