"""Tests for backend.graph.parsers.validators.validate_arch_doc.

Parallels test_sysarch_validator.py's shape. Covers structural
validation (root + section order), fragment section rules
(non-empty, no nested tags), policy sub-grammar, external
dependencies (real comp IDs from the allowlist), subcomponent
structure (alias syntax, kind-inheritance-no-kind-tag, foundation
requirement, ``<owns>`` claims, parent-resp + per-resp feat
coverage), sub-dependency rules (DAG, self-loop, foundation-dep),
and the un-fanned-out happy path.
"""

from __future__ import annotations

import pytest

from backend.graph.parsers.validators import ValidationError, validate_arch_doc
from backend.graph.parsers.xml_sections import TagNode, extract_tag_tree


def _parse(raw: str) -> TagNode:
    return extract_tag_tree(raw, "comparch")


# Reusable test fixtures: a parent-resp → feat-set map covering
# the default three-subcomponent layout, plus a sibling-comp
# allowlist used by the dependencies tests. Policy <required>
# IDs are validated against the keys of KNOWN_PARENT_RESPS — the
# old "subresps OR top-level" two-tier rule collapsed when subreqs
# was retired.
KNOWN_PARENT_RESPS: dict[str, frozenset[str]] = {
    "resp_sess0001": frozenset({"feat_sessl0001", "feat_sessr0002"}),
    "resp_cred0001": frozenset({"feat_login0001"}),
}
KNOWN_SIBLINGS = {"comp_audit9999", "comp_foundati1"}


def _sub(
    alias: str,
    name: str,
    owns: list[tuple[str, list[str]]],
    *,
    foundation: bool = False,
    purpose: str | None = None,
    owned_invariants: tuple[str, ...] | None = None,
    primary_operations: tuple[str, ...] | None = None,
    responsibilities: str | None = None,
) -> str:
    """Render a ``<subcomponent>`` in the micro-field grammar.

    ``owns`` is a list of ``(resp_id, [feat_ids])`` pairs rendered
    as ``<owns><resp id="..."><feat id="..."/></resp></owns>``. An
    empty list yields the legal self-closing ``<owns/>`` form.
    Tests can override ``purpose`` / ``owned_invariants`` /
    ``primary_operations`` / ``responsibilities`` to drive the
    micro-field validators directly.
    """
    if owns:
        blocks = []
        for rid, fids in owns:
            feats = "".join(f'<feat id="{fid}"/>' for fid in fids)
            blocks.append(f'<resp id="{rid}">{feats}</resp>')
        owns_xml = f"<owns>{''.join(blocks)}</owns>"
    else:
        owns_xml = "<owns/>"
    foundation_marker = "<foundation/>" if foundation else ""
    actual_purpose = purpose if purpose is not None else f"{name} exists."
    invariants = owned_invariants or (
        f"{name} invariant one",
        f"{name} invariant two",
    )
    operations = primary_operations or (
        f"do {name} one",
        f"do {name} two",
        f"do {name} three",
    )
    inv_xml = "".join(f"<invariant>{inv}</invariant>" for inv in invariants)
    op_xml = "".join(f"<operation>{op}</operation>" for op in operations)
    resp_text = (
        responsibilities
        if responsibilities is not None
        else f"{name} prose describing what this subcomp does."
    )
    return (
        f'<subcomponent alias="{alias}">'
        f"<name>{name}</name>"
        f"<purpose>{actual_purpose}</purpose>"
        f"<owned-invariants>{inv_xml}</owned-invariants>"
        f"<primary-operations>{op_xml}</primary-operations>"
        f"<responsibilities>{resp_text}</responsibilities>"
        f"{owns_xml}"
        f"{foundation_marker}"
        "</subcomponent>"
    )


def _default_subcomponents() -> str:
    """Three-subcomponent layout covering both default parent resps.

    session_store claims (resp_sess0001, [both feats]); credential_gate
    claims (resp_cred0001, [feat_login0001]); foundation has empty
    ``<owns/>`` and carries the foundation marker. Coverage is
    satisfied for every parent resp + every feat tagged on it.
    """
    return (
        _sub(
            "session_store",
            "SessionStore",
            [("resp_sess0001", ["feat_sessl0001", "feat_sessr0002"])],
        )
        + _sub(
            "credential_gate",
            "CredentialGate",
            [("resp_cred0001", ["feat_login0001"])],
        )
        + _sub(
            "foundation",
            "Foundation",
            [],
            foundation=True,
        )
    )


# Default sub-deps that satisfy the foundation-dep rule for the
# default three-subcomponent layout: every non-foundation
# subcomponent depends on foundation.
_DEFAULT_SUB_DEPS = (
    '<dep from="session_store" to="foundation"/><dep from="credential_gate" to="foundation"/>'
)


def _arch_doc(
    *,
    techspec: str = "Python + PostgreSQL stack.",
    pubapi: str = "authenticate(creds) -> Session.",
    privapi: str = "Internal: _verify_password.",
    failure_surface: str = "Verifier regression admits empty-hash matches.",
    policies: str = "",
    dependencies: str = "",
    subcomponents: str = "",
    sub_dependencies: str = "",
) -> str:
    return (
        "<comparch>"
        f"<technical-specification>{techspec}</technical-specification>"
        f"<public-surface>{pubapi}</public-surface>"
        f"<private-surface>{privapi}</private-surface>"
        f"<failure-surface>{failure_surface}</failure-surface>"
        f"<policies>{policies}</policies>"
        f"<dependencies>{dependencies}</dependencies>"
        f"<subcomponents>{subcomponents}</subcomponents>"
        f"<sub-dependencies>{sub_dependencies}</sub-dependencies>"
        "</comparch>"
    )


def _policy(name: str, trigger: str, required: str, rationale: str) -> str:
    return (
        "<policy>"
        f"<name>{name}</name>"
        f"<trigger>{trigger}</trigger>"
        f"<required>{required}</required>"
        f"<rationale>{rationale}</rationale>"
        "</policy>"
    )


def _validate(
    raw: str,
    *,
    known_parent_resp_ids: dict[str, frozenset[str]] | None = None,
    known_sibling_comp_ids: set[str] | None = None,
    target_is_foundation: bool = False,
):
    return validate_arch_doc(
        _parse(raw),
        known_parent_resp_ids=(
            known_parent_resp_ids if known_parent_resp_ids is not None else KNOWN_PARENT_RESPS
        ),
        known_sibling_comp_ids=(
            known_sibling_comp_ids if known_sibling_comp_ids is not None else KNOWN_SIBLINGS
        ),
        target_is_foundation=target_is_foundation,
    )


class TestHappyPath:
    def test_minimal_decomposed(self):
        doc = _validate(
            _arch_doc(
                subcomponents=_default_subcomponents(),
                sub_dependencies=_DEFAULT_SUB_DEPS,
            )
        )
        assert doc.techspec == "Python + PostgreSQL stack."
        assert doc.pubapi == "authenticate(creds) -> Session."
        assert doc.privapi == "Internal: _verify_password."
        assert doc.policies == ()
        assert doc.external_deps == ()
        assert [s.alias for s in doc.subcomponents] == [
            "session_store",
            "credential_gate",
            "foundation",
        ]
        assert [s.is_foundation for s in doc.subcomponents] == [False, False, True]
        assert len(doc.sub_deps) == 2

    def test_with_policies_and_external_deps(self):
        doc = _validate(
            _arch_doc(
                policies=_policy(
                    "Audit Logging",
                    "any failed auth",
                    "resp_sess0001",
                    "Audit failed auths for compliance.",
                ),
                dependencies='<dep to="comp_audit9999"/><dep to="comp_foundati1"/>',
                subcomponents=_default_subcomponents(),
                sub_dependencies=_DEFAULT_SUB_DEPS,
            )
        )
        assert len(doc.policies) == 1
        assert doc.policies[0].name == "Audit Logging"
        assert doc.policies[0].required_resp_id == "resp_sess0001"
        assert set(doc.external_deps) == {"comp_audit9999", "comp_foundati1"}

    def test_un_fanned_out_happy_path(self):
        """Empty parent_resp map + empty sub sections → valid un-fanned-out.

        With no parent resps assigned to this comp, coverage rules
        degenerate to no-ops and an empty <subcomponents> block is
        legal (the comp's territory rolls wholesale into a single
        impl_* leaf at mint time).
        """
        doc = _validate(
            _arch_doc(subcomponents="", sub_dependencies=""),
            known_parent_resp_ids={},
        )
        assert doc.subcomponents == ()
        assert doc.sub_deps == ()
        # All three fragment sections are still populated
        assert doc.techspec
        assert doc.pubapi
        assert doc.privapi


class TestRootAndSectionOrder:
    def test_wrong_root_rejected(self):
        tree = TagNode(tag="sysarch", text="", children=[])
        with pytest.raises(ValidationError, match="Expected root tag <comparch>"):
            validate_arch_doc(
                tree,
                known_parent_resp_ids={},
                known_sibling_comp_ids=set(),
            )

    def test_missing_section_rejected(self):
        raw = (
            "<comparch>"
            "<technical-specification>t</technical-specification>"
            "<public-surface>p</public-surface>"
            "<private-surface>pr</private-surface>"
            "<failure-surface>fs</failure-surface>"
            "<policies></policies>"
            "<subcomponents></subcomponents>"
            "<sub-dependencies></sub-dependencies>"
            "</comparch>"
        )
        with pytest.raises(ValidationError, match="not in the required order"):
            _validate(raw, known_parent_resp_ids={})

    def test_wrong_section_order_rejected(self):
        # swap subcomponents and sub-dependencies
        raw = (
            "<comparch>"
            "<technical-specification>t</technical-specification>"
            "<public-surface>p</public-surface>"
            "<private-surface>pr</private-surface>"
            "<failure-surface>fs</failure-surface>"
            "<policies></policies>"
            "<dependencies></dependencies>"
            "<sub-dependencies></sub-dependencies>"
            "<subcomponents></subcomponents>"
            "</comparch>"
        )
        with pytest.raises(ValidationError, match="not in the required order"):
            _validate(raw, known_parent_resp_ids={})

    def test_duplicate_section_rejected(self):
        raw = (
            "<comparch>"
            "<technical-specification>t</technical-specification>"
            "<technical-specification>t2</technical-specification>"
            "<public-surface>p</public-surface>"
            "<private-surface>pr</private-surface>"
            "<failure-surface>fs</failure-surface>"
            "<policies></policies>"
            "<dependencies></dependencies>"
            "<subcomponents></subcomponents>"
            "<sub-dependencies></sub-dependencies>"
            "</comparch>"
        )
        with pytest.raises(ValidationError, match="more than one <technical-specification>"):
            _validate(raw, known_parent_resp_ids={})

    def test_unknown_section_rejected(self):
        raw = _arch_doc(subcomponents=_default_subcomponents(), sub_dependencies=_DEFAULT_SUB_DEPS)
        raw = raw.replace("</comparch>", "<widget></widget></comparch>")
        with pytest.raises(ValidationError, match="unexpected child <widget>"):
            _validate(raw)


class TestFragmentSections:
    def test_empty_techspec_rejected(self):
        raw = _arch_doc(
            techspec="",
            subcomponents=_default_subcomponents(),
            sub_dependencies=_DEFAULT_SUB_DEPS,
        )
        with pytest.raises(ValidationError, match="<technical-specification> is empty"):
            _validate(raw)

    def test_empty_pubapi_rejected(self):
        raw = _arch_doc(
            pubapi="",
            subcomponents=_default_subcomponents(),
            sub_dependencies=_DEFAULT_SUB_DEPS,
        )
        with pytest.raises(ValidationError, match="<public-surface> is empty"):
            _validate(raw)

    def test_empty_privapi_rejected(self):
        raw = _arch_doc(
            privapi="",
            subcomponents=_default_subcomponents(),
            sub_dependencies=_DEFAULT_SUB_DEPS,
        )
        with pytest.raises(ValidationError, match="<private-surface> is empty"):
            _validate(raw)

    def test_nested_tags_in_fragment_rejected(self):
        raw = (
            "<comparch>"
            "<technical-specification>t <nested>no</nested></technical-specification>"
            "<public-surface>p</public-surface>"
            "<private-surface>pr</private-surface>"
            "<failure-surface>auth bypass on verifier regression</failure-surface>"
            "<policies></policies>"
            "<dependencies></dependencies>"
            "<subcomponents></subcomponents>"
            "<sub-dependencies></sub-dependencies>"
            "</comparch>"
        )
        with pytest.raises(ValidationError, match="must contain plain text"):
            _validate(raw, known_parent_resp_ids={})

    def test_empty_failure_surface_rejected(self):
        raw = _arch_doc(
            failure_surface="",
            subcomponents=_default_subcomponents(),
            sub_dependencies=_DEFAULT_SUB_DEPS,
        )
        with pytest.raises(ValidationError, match="<failure-surface> is empty"):
            _validate(raw)

    def test_failure_surface_persisted_on_doc(self):
        doc = _validate(
            _arch_doc(
                failure_surface="verifier regression admits empty-hash matches",
                subcomponents=_default_subcomponents(),
                sub_dependencies=_DEFAULT_SUB_DEPS,
            )
        )
        assert "verifier regression" in doc.failure_surface


class TestExternalDependencies:
    def test_known_sibling_accepted(self):
        doc = _validate(
            _arch_doc(
                dependencies='<dep to="comp_audit9999"/>',
                subcomponents=_default_subcomponents(),
                sub_dependencies=_DEFAULT_SUB_DEPS,
            )
        )
        assert doc.external_deps == ("comp_audit9999",)

    def test_unknown_sibling_rejected(self):
        raw = _arch_doc(
            dependencies='<dep to="comp_strange99"/>',
            subcomponents=_default_subcomponents(),
            sub_dependencies=_DEFAULT_SUB_DEPS,
        )
        with pytest.raises(ValidationError, match="not in the allowed sibling component set"):
            _validate(raw)

    def test_missing_to_attribute_rejected(self):
        raw = _arch_doc(
            dependencies="<dep/>",
            subcomponents=_default_subcomponents(),
            sub_dependencies=_DEFAULT_SUB_DEPS,
        )
        with pytest.raises(ValidationError, match="missing the to attribute"):
            _validate(raw)

    def test_from_attribute_rejected(self):
        # External deps must not have a from attribute — that's for
        # sub-dependencies. Catch the common LLM mistake of carrying
        # sysarch's <dep from/to/> shape forward.
        raw = _arch_doc(
            dependencies='<dep from="self" to="comp_audit9999"/>',
            subcomponents=_default_subcomponents(),
            sub_dependencies=_DEFAULT_SUB_DEPS,
        )
        with pytest.raises(ValidationError, match="has a from attribute"):
            _validate(raw)

    def test_duplicate_target_rejected(self):
        raw = _arch_doc(
            dependencies='<dep to="comp_audit9999"/><dep to="comp_audit9999"/>',
            subcomponents=_default_subcomponents(),
            sub_dependencies=_DEFAULT_SUB_DEPS,
        )
        with pytest.raises(ValidationError, match="duplicate target"):
            _validate(raw)


class TestPolicies:
    def test_policy_happy_path(self):
        doc = _validate(
            _arch_doc(
                policies=_policy(
                    "Telemetry",
                    "any LLM call",
                    "resp_cred0001",
                    "Cost audit.",
                ),
                subcomponents=_default_subcomponents(),
                sub_dependencies=_DEFAULT_SUB_DEPS,
            )
        )
        assert len(doc.policies) == 1
        assert doc.policies[0].trigger == "any LLM call"

    def test_policy_unknown_required_rejected(self):
        bad = _policy("Bad", "x", "resp_mystery00", "y")
        raw = _arch_doc(
            policies=bad,
            subcomponents=_default_subcomponents(),
            sub_dependencies=_DEFAULT_SUB_DEPS,
        )
        with pytest.raises(ValidationError, match="unknown responsibility"):
            _validate(raw)

    def test_policy_missing_trigger_rejected(self):
        bad = (
            "<policy><name>Bad</name>"
            "<required>resp_cred0001</required>"
            "<rationale>x</rationale></policy>"
        )
        raw = _arch_doc(
            policies=bad,
            subcomponents=_default_subcomponents(),
            sub_dependencies=_DEFAULT_SUB_DEPS,
        )
        with pytest.raises(ValidationError, match="missing a <trigger>"):
            _validate(raw)

    def test_empty_policies_accepted(self):
        doc = _validate(
            _arch_doc(
                policies="",
                subcomponents=_default_subcomponents(),
                sub_dependencies=_DEFAULT_SUB_DEPS,
            )
        )
        assert doc.policies == ()


_SOLO_RESP_MAP: dict[str, frozenset[str]] = {"resp_sess0001": frozenset({"feat_sessl0001"})}


class TestSubcomponentStructure:
    def test_missing_alias_rejected(self):
        bad = (
            "<subcomponent>"
            "<name>X</name>"
            "<purpose>x</purpose>"
            "<owned-invariants><invariant>a</invariant><invariant>b</invariant></owned-invariants>"
            "<primary-operations>"
            "<operation>a</operation><operation>b</operation><operation>c</operation>"
            "</primary-operations>"
            "<responsibilities>x</responsibilities>"
            "<owns/>"
            "</subcomponent>"
        )
        raw = _arch_doc(subcomponents=bad, sub_dependencies="")
        with pytest.raises(ValidationError, match="missing the alias attribute"):
            _validate(raw)

    def test_invalid_alias_rejected(self):
        bad = _sub(
            "Bad-Alias!",
            "X",
            [("resp_sess0001", ["feat_sessl0001"])],
        )
        raw = _arch_doc(subcomponents=bad, sub_dependencies="")
        with pytest.raises(ValidationError, match="invalid alias"):
            _validate(raw, known_parent_resp_ids=_SOLO_RESP_MAP)

    def test_duplicate_alias_rejected(self):
        dupe = _sub("dup", "First", [("resp_sess0001", ["feat_sessl0001"])]) + _sub(
            "dup", "Second", [("resp_cred0001", ["feat_login0001"])], foundation=True
        )
        raw = _arch_doc(subcomponents=dupe, sub_dependencies="")
        with pytest.raises(ValidationError, match="same alias 'dup'"):
            _validate(raw)

    def test_kind_tag_rejected(self):
        # Subcomponents must NOT redeclare kind — they inherit from
        # the owning component. A <kind> child is unexpected.
        bad = (
            '<subcomponent alias="thing">'
            "<name>X</name>"
            "<kind>domain</kind>"
            "<purpose>x</purpose>"
            "<owned-invariants><invariant>a</invariant><invariant>b</invariant></owned-invariants>"
            "<primary-operations>"
            "<operation>a</operation><operation>b</operation><operation>c</operation>"
            "</primary-operations>"
            "<responsibilities>x</responsibilities>"
            '<owns><resp id="resp_sess0001"><feat id="feat_sessl0001"/></resp></owns>'
            "<foundation/>"
            "</subcomponent>"
        )
        raw = _arch_doc(subcomponents=bad, sub_dependencies="")
        with pytest.raises(ValidationError, match="unexpected child <kind>"):
            _validate(raw, known_parent_resp_ids=_SOLO_RESP_MAP)

    def test_empty_name_rejected(self):
        bad = _sub(
            "x",
            "",
            [("resp_sess0001", ["feat_sessl0001"])],
            foundation=True,
        )
        raw = _arch_doc(subcomponents=bad, sub_dependencies="")
        with pytest.raises(ValidationError, match="empty <name>"):
            _validate(raw, known_parent_resp_ids=_SOLO_RESP_MAP)

    def test_empty_purpose_rejected(self):
        bad = _sub(
            "x",
            "Name",
            [("resp_sess0001", ["feat_sessl0001"])],
            foundation=True,
            purpose="",
        )
        raw = _arch_doc(subcomponents=bad, sub_dependencies="")
        with pytest.raises(ValidationError, match="empty <purpose>"):
            _validate(raw, known_parent_resp_ids=_SOLO_RESP_MAP)

    def test_too_few_subcomp_invariants_rejected(self):
        bad = _sub(
            "x",
            "Name",
            [("resp_sess0001", ["feat_sessl0001"])],
            foundation=True,
            owned_invariants=("only one",),
        )
        raw = _arch_doc(subcomponents=bad, sub_dependencies="")
        with pytest.raises(ValidationError, match=r"1 <invariant> entries"):
            _validate(raw, known_parent_resp_ids=_SOLO_RESP_MAP)

    def test_too_few_subcomp_operations_rejected(self):
        bad = _sub(
            "x",
            "Name",
            [("resp_sess0001", ["feat_sessl0001"])],
            foundation=True,
            primary_operations=("do a", "do b"),
        )
        raw = _arch_doc(subcomponents=bad, sub_dependencies="")
        with pytest.raises(ValidationError, match=r"2 <operation> entries"):
            _validate(raw, known_parent_resp_ids=_SOLO_RESP_MAP)

    def test_empty_responsibilities_rejected(self):
        # <responsibilities> is now free-text prose; an empty body
        # is rejected with the prose-section error.
        bad = _sub(
            "x",
            "Name",
            [("resp_sess0001", ["feat_sessl0001"])],
            foundation=True,
            responsibilities="",
        )
        raw = _arch_doc(subcomponents=bad, sub_dependencies="")
        with pytest.raises(ValidationError, match="empty <responsibilities>"):
            _validate(raw, known_parent_resp_ids=_SOLO_RESP_MAP)

    def test_responsibilities_with_nested_tags_rejected(self):
        # The pre-Phase-A grammar carried <resp id=…/> children
        # inside <responsibilities>; in the new grammar those live
        # in <owns> and any nested tag inside <responsibilities>
        # is rejected.
        bad = _sub(
            "x",
            "Name",
            [("resp_sess0001", ["feat_sessl0001"])],
            foundation=True,
            responsibilities='<resp id="resp_sess0001"/>',
        )
        raw = _arch_doc(subcomponents=bad, sub_dependencies="")
        with pytest.raises(ValidationError, match="nested tags inside <responsibilities>"):
            _validate(raw, known_parent_resp_ids=_SOLO_RESP_MAP)


class TestSubcomponentCoverage:
    def test_uncaimed_parent_resp_rejected(self):
        # Two subs cover only one of two known parent resps —
        # resp_cred0001 is left unclaimed.
        subs = _sub(
            "store",
            "SessionStore",
            [("resp_sess0001", ["feat_sessl0001", "feat_sessr0002"])],
        ) + _sub("foundation", "Foundation", [], foundation=True)
        raw = _arch_doc(
            subcomponents=subs,
            sub_dependencies='<dep from="store" to="foundation"/>',
        )
        with pytest.raises(ValidationError, match="does not claim every parent responsibility"):
            _validate(raw)

    def test_uncovered_feat_under_claimed_resp_rejected(self):
        # session_store claims resp_sess0001 but only one of its two
        # feats; no other subcomp picks up the missing feat.
        subs = (
            _sub(
                "store",
                "SessionStore",
                [("resp_sess0001", ["feat_sessl0001"])],
            )
            + _sub(
                "credential_gate",
                "CredentialGate",
                [("resp_cred0001", ["feat_login0001"])],
            )
            + _sub("foundation", "Foundation", [], foundation=True)
        )
        raw = _arch_doc(
            subcomponents=subs,
            sub_dependencies=_DEFAULT_SUB_DEPS,
        )
        with pytest.raises(ValidationError, match="some feats tagged on parent"):
            _validate(raw)

    def test_un_fanned_out_with_parent_resps_is_legal(self):
        """Empty <subcomponents> is legal even when the comp carries
        parent resps — the resps roll wholesale into a single impl
        leaf at mint time and the coverage rules degenerate."""
        raw = _arch_doc(subcomponents="", sub_dependencies="")
        doc = _validate(raw)
        assert doc.subcomponents == ()
        assert doc.sub_deps == ()


class TestFoundationSubcomponent:
    def test_no_foundation_rejected_when_decomposing(self):
        subs = (
            _sub(
                "store",
                "SessionStore",
                [("resp_sess0001", ["feat_sessl0001", "feat_sessr0002"])],
            )
            + _sub(
                "gate",
                "CredentialGate",
                [("resp_cred0001", ["feat_login0001"])],
            )
            + _sub("config", "Config", [])
        )
        raw = _arch_doc(subcomponents=subs, sub_dependencies="")
        with pytest.raises(ValidationError, match="no foundation subcomponent"):
            _validate(raw)

    def test_multiple_foundations_rejected(self):
        subs = (
            _sub(
                "store",
                "S",
                [("resp_sess0001", ["feat_sessl0001", "feat_sessr0002"])],
                foundation=True,
            )
            + _sub("gate", "G", [("resp_cred0001", ["feat_login0001"])])
            + _sub("foundation", "Foundation", [], foundation=True)
        )
        raw = _arch_doc(subcomponents=subs, sub_dependencies="")
        with pytest.raises(ValidationError, match="2 foundation subcomponents"):
            _validate(raw)


class TestFoundationDecomposingAFoundation:
    """Foundations don't nest.

    When the target comp itself carries the foundation role, its
    own comparch decomposition must *not* include another
    foundation subcomponent — the foundation concept is already
    "catch-all at this level" and nesting it would double-count
    the role. The validator accepts an exhaustive decomposition
    with no <foundation/> marker, rejects any <foundation/>
    marker in the subcomponents, and skips the
    ``_enforce_sub_foundation_dependency`` check because there's
    no foundation sub to depend on.
    """

    def _exhaustive_subs_no_foundation(self) -> str:
        """Two subcomponents covering all parent resps + their feats,
        neither of which carries ``<foundation/>``."""
        return _sub(
            "bootstrap",
            "Bootstrap",
            [("resp_sess0001", ["feat_sessl0001", "feat_sessr0002"])],
        ) + _sub(
            "config_loader",
            "ConfigLoader",
            [("resp_cred0001", ["feat_login0001"])],
        )

    def test_accepts_exhaustive_decomposition(self):
        """A foundation comp may decompose into subcomponents with
        no <foundation/> marker, as long as every parent resp +
        feat is covered and sub-deps are acyclic."""
        raw = _arch_doc(
            subcomponents=self._exhaustive_subs_no_foundation(),
            sub_dependencies="",
        )
        doc = _validate(raw, target_is_foundation=True)
        assert len(doc.subcomponents) == 2
        # None of the minted subs are foundations.
        assert all(not s.is_foundation for s in doc.subcomponents)

    def test_rejects_nested_foundation_marker(self):
        """A foundation decomposing into subs with a <foundation/>
        marker is rejected with a clear error."""
        subs = _sub(
            "bootstrap", "B", [("resp_sess0001", ["feat_sessl0001", "feat_sessr0002"])]
        ) + _sub(
            "config_loader",
            "Foundation",
            [("resp_cred0001", ["feat_login0001"])],
            foundation=True,
        )
        raw = _arch_doc(subcomponents=subs, sub_dependencies="")
        with pytest.raises(ValidationError, match="Foundations do not nest"):
            _validate(raw, target_is_foundation=True)

    def test_skips_foundation_dep_rule(self):
        """The 'every non-foundation sub depends on foundation'
        rule is skipped when the target is itself a foundation —
        there's no foundation sub to depend on, so sub-deps are
        free (as long as they're acyclic)."""
        raw = _arch_doc(
            subcomponents=self._exhaustive_subs_no_foundation(),
            # No foundation-dep edges, which would normally fail
            # _enforce_sub_foundation_dependency. Passes here.
            sub_dependencies="",
        )
        # Should not raise.
        _validate(raw, target_is_foundation=True)

    def test_normal_rules_still_reject_empty_foundation_list(self):
        """Sanity check: target_is_foundation=False still enforces
        the 'exactly one foundation subcomponent required' rule
        on decomposition. The carve-out is scoped to foundation
        targets only."""
        raw = _arch_doc(
            subcomponents=self._exhaustive_subs_no_foundation(),
            sub_dependencies="",
        )
        with pytest.raises(ValidationError, match="no foundation subcomponent"):
            _validate(raw, target_is_foundation=False)

    def test_un_fanned_out_foundation_still_legal(self):
        """A foundation component that stays un-fanned-out
        (empty <subcomponents>) is legal under both branches —
        the carve-out only kicks in when decomposition actually
        happens."""
        raw = _arch_doc(subcomponents="", sub_dependencies="")
        # With no parent resps assigned, empty <subcomponents> is fine.
        doc = _validate(
            raw,
            known_parent_resp_ids={},
            target_is_foundation=True,
        )
        assert doc.subcomponents == ()


class TestSubDependencies:
    def test_self_dep_rejected(self):
        raw = _arch_doc(
            subcomponents=_default_subcomponents(),
            sub_dependencies='<dep from="session_store" to="session_store"/>',
        )
        with pytest.raises(ValidationError, match="from == to"):
            _validate(raw)

    def test_unknown_alias_rejected(self):
        raw = _arch_doc(
            subcomponents=_default_subcomponents(),
            sub_dependencies='<dep from="session_store" to="mystery"/>',
        )
        with pytest.raises(ValidationError, match="unknown to alias 'mystery'"):
            _validate(raw)

    def test_cycle_rejected(self):
        raw = _arch_doc(
            subcomponents=_default_subcomponents(),
            sub_dependencies=(
                '<dep from="session_store" to="credential_gate"/>'
                '<dep from="credential_gate" to="session_store"/>'
                '<dep from="session_store" to="foundation"/>'
                '<dep from="credential_gate" to="foundation"/>'
            ),
        )
        with pytest.raises(ValidationError, match="Dependency cycle detected"):
            _validate(raw)

    def test_missing_foundation_dep_rejected(self):
        raw = _arch_doc(
            subcomponents=_default_subcomponents(),
            # Only one of the two non-foundation subs has its foundation dep
            sub_dependencies='<dep from="session_store" to="foundation"/>',
        )
        with pytest.raises(
            ValidationError,
            match="Missing foundation dependency from: credential_gate",
        ):
            _validate(raw)

    def test_undeclared_cross_sub_reference_inducing_cycle_rejected(self):
        """The reviewer-flagged case: SubA's prose mentions SubB by
        name AND SubB's prose mentions SubA by name, but no
        ``<dep>`` edge is declared in either direction. The declared
        graph alone is acyclic, but the implicit reference graph
        forms a cycle, which will surface as a circular module
        dep at impl time. Reject on parse so the retry loop fires
        with a clear repair instruction."""
        subs = (
            _sub(
                "shell_substrate",
                "ShellSubstrate",
                [("resp_sess0001", ["feat_sessl0001", "feat_sessr0002"])],
                responsibilities=(
                    "Shared foundation that ShellChrome depends on for layout config."
                ),
            )
            + _sub(
                "shell_chrome",
                "ShellChrome",
                [("resp_cred0001", ["feat_login0001"])],
                responsibilities=(
                    "Renders the chrome surrounding ShellSubstrate's exposed regions."
                ),
            )
            + _sub("foundation", "Foundation", [], foundation=True)
        )
        raw = _arch_doc(
            subcomponents=subs,
            sub_dependencies=(
                '<dep from="shell_substrate" to="foundation"/>'
                '<dep from="shell_chrome" to="foundation"/>'
            ),
        )
        with pytest.raises(ValidationError, match="Undeclared sub-dependency cycle"):
            _validate(raw)

    def test_one_directional_undeclared_reference_with_declared_reverse_rejected(self):
        """Mixed case: one direction is declared, the other is only
        in prose. Together they form a cycle. The declared cycle
        check (run first) sees only the declared edge and is
        happy; the undeclared-cycle check must catch this."""
        subs = (
            _sub(
                "reducer_gate",
                "ReducerGate",
                [("resp_sess0001", ["feat_sessl0001", "feat_sessr0002"])],
                responsibilities=(
                    "Validates commands. Calls into WebhookDeliveryPipeline "
                    "to schedule outbound deliveries on commit."
                ),
            )
            + _sub(
                "webhook_delivery_pipeline",
                "WebhookDeliveryPipeline",
                [("resp_cred0001", ["feat_login0001"])],
                # No mention of ReducerGate — this direction is
                # declared explicitly via <dep> below.
            )
            + _sub("foundation", "Foundation", [], foundation=True)
        )
        raw = _arch_doc(
            subcomponents=subs,
            sub_dependencies=(
                # Declared: WebhookDeliveryPipeline → ReducerGate
                '<dep from="webhook_delivery_pipeline" to="reducer_gate"/>'
                '<dep from="reducer_gate" to="foundation"/>'
                '<dep from="webhook_delivery_pipeline" to="foundation"/>'
            ),
        )
        # Implicit (from prose): reducer_gate → webhook_delivery_pipeline.
        # Union forms a cycle: reducer_gate → webhook_delivery_pipeline → reducer_gate.
        with pytest.raises(ValidationError, match="Undeclared sub-dependency cycle"):
            _validate(raw)

    def test_undeclared_reference_without_cycle_accepted(self):
        """A subcomponent's prose can mention another by name without
        a declared ``<dep>`` as long as the implicit edge doesn't
        form a cycle. We only fail on cycles — plain undeclared
        references are too noisy to gate on without false positives."""
        subs = (
            _sub(
                "session_store",
                "SessionStore",
                [("resp_sess0001", ["feat_sessl0001", "feat_sessr0002"])],
                responsibilities=("Persists sessions. References CredentialGate for login flows."),
            )
            + _sub(
                "credential_gate",
                "CredentialGate",
                [("resp_cred0001", ["feat_login0001"])],
                # No back-reference to SessionStore — implicit edge
                # is one-way only.
            )
            + _sub("foundation", "Foundation", [], foundation=True)
        )
        # Validator should accept; implicit edge session_store →
        # credential_gate alone is acyclic.
        doc = _validate(
            _arch_doc(
                subcomponents=subs,
                sub_dependencies=_DEFAULT_SUB_DEPS,
            )
        )
        assert len(doc.subcomponents) == 3

    def test_short_or_lowercase_name_does_not_trip_match(self):
        """Names that aren't unambiguous PascalCase identifiers
        (too short or no internal uppercase) shouldn't trigger
        false-positive matches when those character sequences
        appear coincidentally in prose. Guards against a sub
        named ``Core`` or ``Hub`` matching every casual mention
        of the word in another sub's responsibilities."""
        # "Hub" is 3 chars — below the eligibility threshold.
        # SessionStore mentions "hub" in casual prose; this should
        # NOT be flagged as an implicit dep on a sub named "Hub".
        subs = (
            _sub(
                "session_store",
                "SessionStore",
                [("resp_sess0001", ["feat_sessl0001", "feat_sessr0002"])],
                responsibilities=("The session storage hub for the auth flow."),
            )
            + _sub(
                "credential_gate",
                "Hub",
                [("resp_cred0001", ["feat_login0001"])],
                responsibilities=("Validates credentials. References SessionStore on login."),
            )
            + _sub("foundation", "Foundation", [], foundation=True)
        )
        # Even though the word "hub" appears in session_store's prose
        # AND credential_gate references session_store, the implicit
        # graph has only credential_gate → session_store (one-way) —
        # no cycle, no rejection.
        doc = _validate(
            _arch_doc(
                subcomponents=subs,
                sub_dependencies=_DEFAULT_SUB_DEPS,
            )
        )
        assert len(doc.subcomponents) == 3

    def test_all_foundation_deps_present_accepted(self):
        doc = _validate(
            _arch_doc(
                subcomponents=_default_subcomponents(),
                sub_dependencies=_DEFAULT_SUB_DEPS,
            )
        )
        assert len(doc.sub_deps) == 2
        assert all(d.to_alias == "foundation" for d in doc.sub_deps)


class TestOwns:
    """Coverage of the new ``<owns>`` invariants.

    Replaces the retired pre-Phase-A subresp-assignment tests:
    ``<owns>`` collapses subreqs and the parent-resp claim into
    a single block. Multi-owner is allowed at both axes (same
    resp under multiple subcomps; same feat across subcomps that
    cooperate). The validator now enforces resp + feat coverage
    at the component level instead of 1:1 assignment.
    """

    def test_empty_owns_is_legal_for_foundation(self):
        """An empty ``<owns/>`` is the canonical foundation /
        internal-plumbing shape — no parent resp claims, value
        comes from the structural marker plus other subcomps'
        ownership picture."""
        doc = _validate(
            _arch_doc(
                subcomponents=_default_subcomponents(),
                sub_dependencies=_DEFAULT_SUB_DEPS,
            )
        )
        foundation = next(s for s in doc.subcomponents if s.alias == "foundation")
        assert foundation.owns == ()

    def test_multi_owner_same_resp_accepted(self):
        """Two subcomponents may both claim the same parent resp
        as long as their feat slices together cover every feat
        tagged on the resp. The validator must accept this and
        return both subcomps' OwnedResp entries."""
        subs = (
            _sub(
                "store",
                "SessionStore",
                [("resp_sess0001", ["feat_sessl0001"])],
            )
            + _sub(
                "credential_gate",
                "CredentialGate",
                [
                    ("resp_sess0001", ["feat_sessr0002"]),
                    ("resp_cred0001", ["feat_login0001"]),
                ],
            )
            + _sub("foundation", "Foundation", [], foundation=True)
        )
        doc = _validate(
            _arch_doc(
                subcomponents=subs,
                sub_dependencies=(
                    '<dep from="store" to="foundation"/>'
                    '<dep from="credential_gate" to="foundation"/>'
                ),
            )
        )
        owners_of_sess = [
            s.alias
            for s in doc.subcomponents
            if any(owned.resp_id == "resp_sess0001" for owned in s.owns)
        ]
        assert sorted(owners_of_sess) == ["credential_gate", "store"]

    def test_multi_owner_same_feat_accepted(self):
        """Two subcomponents may both claim the same feat under
        the same parent resp when they genuinely cooperate on
        that feature; uniqueness is per-(subcomp, resp), not
        across the component."""
        subs = (
            _sub(
                "store",
                "SessionStore",
                [("resp_sess0001", ["feat_sessl0001", "feat_sessr0002"])],
            )
            + _sub(
                "co_owner",
                "CoOwner",
                [
                    ("resp_sess0001", ["feat_sessl0001"]),
                    ("resp_cred0001", ["feat_login0001"]),
                ],
            )
            + _sub("foundation", "Foundation", [], foundation=True)
        )
        doc = _validate(
            _arch_doc(
                subcomponents=subs,
                sub_dependencies=(
                    '<dep from="store" to="foundation"/><dep from="co_owner" to="foundation"/>'
                ),
            )
        )
        # Both store and co_owner list feat_sessl0001 under
        # resp_sess0001 — multi-feat-owner is legal.
        owners_of_feat = [
            s.alias
            for s in doc.subcomponents
            for owned in s.owns
            if owned.resp_id == "resp_sess0001" and "feat_sessl0001" in owned.feat_ids
        ]
        assert sorted(owners_of_feat) == ["co_owner", "store"]

    def test_unknown_resp_id_rejected(self):
        """A ``<resp id=…>`` referencing an id outside this
        component's parent-resp allowlist fails the cross-
        component-leak check."""
        subs = _sub(
            "store",
            "SessionStore",
            [("resp_mystery01", ["feat_sessl0001"])],
            foundation=True,
        )
        raw = _arch_doc(subcomponents=subs, sub_dependencies="")
        with pytest.raises(
            ValidationError,
            match="not one of this component's parent responsibilities",
        ):
            _validate(raw, known_parent_resp_ids=_SOLO_RESP_MAP)

    def test_feat_not_tagged_on_resp_rejected(self):
        """A ``<feat id=…>`` inside ``<owns><resp>`` must be tagged
        on that parent resp; an unrelated feat id is rejected."""
        subs = _sub(
            "store",
            "SessionStore",
            [("resp_sess0001", ["feat_unrelated"])],
            foundation=True,
        )
        raw = _arch_doc(subcomponents=subs, sub_dependencies="")
        with pytest.raises(
            ValidationError,
            match=r"is not tagged on 'resp_sess0001'",
        ):
            _validate(raw, known_parent_resp_ids=_SOLO_RESP_MAP)

    def test_missing_resp_coverage_rejected(self):
        """Every parent resp in the allowlist must be claimed by
        at least one subcomponent; otherwise the comparch is
        incomplete and the validator surfaces the missing ids."""
        subs = _sub(
            "store",
            "SessionStore",
            [("resp_sess0001", ["feat_sessl0001", "feat_sessr0002"])],
        ) + _sub("foundation", "Foundation", [], foundation=True)
        raw = _arch_doc(
            subcomponents=subs,
            sub_dependencies='<dep from="store" to="foundation"/>',
        )
        with pytest.raises(
            ValidationError,
            match="does not claim every parent responsibility",
        ):
            _validate(raw)

    def test_missing_feat_coverage_rejected(self):
        """Per-resp feat coverage: every feat tagged on a parent
        resp must be claimed by at least one subcomponent that
        also claims that resp."""
        subs = (
            _sub(
                "store",
                "SessionStore",
                [("resp_sess0001", ["feat_sessl0001"])],  # missing feat_sessr0002
            )
            + _sub(
                "credential_gate",
                "CredentialGate",
                [("resp_cred0001", ["feat_login0001"])],
            )
            + _sub("foundation", "Foundation", [], foundation=True)
        )
        raw = _arch_doc(
            subcomponents=subs,
            sub_dependencies=_DEFAULT_SUB_DEPS,
        )
        with pytest.raises(
            ValidationError,
            match=r"resp_sess0001 → feat_sessr0002",
        ):
            _validate(raw)

    def test_duplicate_resp_within_one_subcomp_rejected(self):
        """The same ``<resp id=…>`` cannot appear twice inside
        one subcomp's ``<owns>`` — the validator demands a single
        ``<resp>`` entry with the union of feat children."""
        bad_subcomp = (
            '<subcomponent alias="store">'
            "<name>SessionStore</name>"
            "<purpose>x</purpose>"
            "<owned-invariants>"
            "<invariant>a</invariant><invariant>b</invariant>"
            "</owned-invariants>"
            "<primary-operations>"
            "<operation>a</operation><operation>b</operation><operation>c</operation>"
            "</primary-operations>"
            "<responsibilities>prose</responsibilities>"
            "<owns>"
            '<resp id="resp_sess0001"><feat id="feat_sessl0001"/></resp>'
            '<resp id="resp_sess0001"><feat id="feat_sessr0002"/></resp>'
            "</owns>"
            "<foundation/>"
            "</subcomponent>"
        )
        raw = _arch_doc(subcomponents=bad_subcomp, sub_dependencies="")
        with pytest.raises(ValidationError, match="duplicate <owns><resp"):
            _validate(raw, known_parent_resp_ids=_SOLO_RESP_MAP)
