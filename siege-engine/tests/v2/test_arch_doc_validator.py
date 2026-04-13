"""Tests for backend.graph.parsers.validators.validate_arch_doc.

Parallels test_sysarch_validator.py's shape. Covers structural
validation (root + section order), fragment section rules
(non-empty, no nested tags), policy sub-grammar, external
dependencies (real comp IDs from the allowlist), subcomponent
structure (alias syntax, kind-inheritance-no-kind-tag, foundation
requirement, subresp coverage), sub-dependency rules (DAG,
self-loop, foundation-dep), and the un-fanned-out happy path.
"""

from __future__ import annotations

import pytest

from backend.graph.parsers.validators import ValidationError, validate_arch_doc
from backend.graph.parsers.xml_sections import TagNode, extract_tag_tree


def _parse(raw: str) -> TagNode:
    return extract_tag_tree(raw, "comparch")


# Reusable test fixtures: a full-coverage subresp set and a
# sibling-comp allowlist that satisfies most tests without
# per-test customization. known_resp_ids_for_policies always
# includes the subresps so policy <required> references can
# reach them.
KNOWN_SUBRESPS = {"resp_sub_sess", "resp_sub_cred", "resp_sub_found"}
KNOWN_SIBLINGS = {"comp_audit9999", "comp_foundati1"}
KNOWN_POLICY_RESPS = KNOWN_SUBRESPS | {"resp_top_audit"}


def _sub(
    alias: str,
    name: str,
    role: str,
    api_intent: str,
    resp_ids: tuple[str, ...],
    *,
    foundation: bool = False,
) -> str:
    resp_xml = "".join(f'<resp id="{rid}"/>' for rid in resp_ids)
    foundation_marker = "<foundation/>" if foundation else ""
    return (
        f'<subcomponent alias="{alias}">'
        f"<name>{name}</name>"
        f"<role>{role}</role>"
        f"<api-intent>{api_intent}</api-intent>"
        f"<responsibilities>{resp_xml}</responsibilities>"
        f"{foundation_marker}"
        "</subcomponent>"
    )


def _default_subcomponents() -> str:
    """Three-subcomponent layout covering all three KNOWN_SUBRESPS."""
    return (
        _sub(
            "session_store",
            "SessionStore",
            "Persist sessions.",
            "create_session(pid).",
            ("resp_sub_sess",),
        )
        + _sub(
            "credential_gate",
            "CredentialGate",
            "Verify credentials.",
            "verify(creds).",
            ("resp_sub_cred",),
        )
        + _sub(
            "foundation",
            "Foundation",
            "Own the component root.",
            "load_settings().",
            ("resp_sub_found",),
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
    known_subresp_ids: set[str] | None = None,
    known_sibling_comp_ids: set[str] | None = None,
    known_resp_ids_for_policies: set[str] | None = None,
):
    return validate_arch_doc(
        _parse(raw),
        known_subresp_ids=known_subresp_ids if known_subresp_ids is not None else KNOWN_SUBRESPS,
        known_sibling_comp_ids=known_sibling_comp_ids
        if known_sibling_comp_ids is not None
        else KNOWN_SIBLINGS,
        known_resp_ids_for_policies=known_resp_ids_for_policies
        if known_resp_ids_for_policies is not None
        else KNOWN_POLICY_RESPS,
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
                    "resp_sub_sess",
                    "Audit failed auths for compliance.",
                ),
                dependencies='<dep to="comp_audit9999"/><dep to="comp_foundati1"/>',
                subcomponents=_default_subcomponents(),
                sub_dependencies=_DEFAULT_SUB_DEPS,
            )
        )
        assert len(doc.policies) == 1
        assert doc.policies[0].name == "Audit Logging"
        assert doc.policies[0].required_resp_id == "resp_sub_sess"
        assert set(doc.external_deps) == {"comp_audit9999", "comp_foundati1"}

    def test_un_fanned_out_happy_path(self):
        """Empty subresps + empty sub sections → valid un-fanned-out."""
        doc = _validate(
            _arch_doc(subcomponents="", sub_dependencies=""),
            known_subresp_ids=set(),
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
                known_subresp_ids=set(),
                known_sibling_comp_ids=set(),
                known_resp_ids_for_policies=set(),
            )

    def test_missing_section_rejected(self):
        raw = (
            "<comparch>"
            "<technical-specification>t</technical-specification>"
            "<public-surface>p</public-surface>"
            "<private-surface>pr</private-surface>"
            "<policies></policies>"
            "<subcomponents></subcomponents>"
            "<sub-dependencies></sub-dependencies>"
            "</comparch>"
        )
        with pytest.raises(ValidationError, match="not in the required order"):
            _validate(raw, known_subresp_ids=set())

    def test_wrong_section_order_rejected(self):
        # swap subcomponents and sub-dependencies
        raw = (
            "<comparch>"
            "<technical-specification>t</technical-specification>"
            "<public-surface>p</public-surface>"
            "<private-surface>pr</private-surface>"
            "<policies></policies>"
            "<dependencies></dependencies>"
            "<sub-dependencies></sub-dependencies>"
            "<subcomponents></subcomponents>"
            "</comparch>"
        )
        with pytest.raises(ValidationError, match="not in the required order"):
            _validate(raw, known_subresp_ids=set())

    def test_duplicate_section_rejected(self):
        raw = (
            "<comparch>"
            "<technical-specification>t</technical-specification>"
            "<technical-specification>t2</technical-specification>"
            "<public-surface>p</public-surface>"
            "<private-surface>pr</private-surface>"
            "<policies></policies>"
            "<dependencies></dependencies>"
            "<subcomponents></subcomponents>"
            "<sub-dependencies></sub-dependencies>"
            "</comparch>"
        )
        with pytest.raises(ValidationError, match="more than one <technical-specification>"):
            _validate(raw, known_subresp_ids=set())

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
            "<policies></policies>"
            "<dependencies></dependencies>"
            "<subcomponents></subcomponents>"
            "<sub-dependencies></sub-dependencies>"
            "</comparch>"
        )
        with pytest.raises(ValidationError, match="must contain plain text"):
            _validate(raw, known_subresp_ids=set())


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
                    "resp_sub_found",
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
            "<required>resp_sub_found</required>"
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


class TestSubcomponentStructure:
    def test_missing_alias_rejected(self):
        bad = (
            "<subcomponent>"
            "<name>X</name><role>x</role>"
            "<api-intent>x</api-intent>"
            "<responsibilities></responsibilities>"
            "</subcomponent>"
        )
        raw = _arch_doc(subcomponents=bad, sub_dependencies="")
        with pytest.raises(ValidationError, match="missing the alias attribute"):
            _validate(raw)

    def test_invalid_alias_rejected(self):
        bad = _sub(
            "Bad-Alias!",
            "X",
            "x",
            "x",
            ("resp_sub_sess",),
        )
        raw = _arch_doc(subcomponents=bad, sub_dependencies="")
        with pytest.raises(ValidationError, match="invalid alias"):
            _validate(raw, known_subresp_ids={"resp_sub_sess"})

    def test_duplicate_alias_rejected(self):
        dupe = _sub("dup", "First", "x", "x", ("resp_sub_sess",)) + _sub(
            "dup", "Second", "y", "y", ("resp_sub_cred",), foundation=True
        )
        raw = _arch_doc(subcomponents=dupe, sub_dependencies="")
        with pytest.raises(ValidationError, match="same alias 'dup'"):
            _validate(raw, known_subresp_ids={"resp_sub_sess", "resp_sub_cred"})

    def test_kind_tag_rejected(self):
        # Subcomponents must NOT redeclare kind — they inherit from
        # the owning component. A <kind> child is unexpected.
        bad = (
            '<subcomponent alias="thing">'
            "<name>X</name>"
            "<kind>domain</kind>"
            "<role>x</role>"
            "<api-intent>x</api-intent>"
            '<responsibilities><resp id="resp_sub_sess"/></responsibilities>'
            "<foundation/>"
            "</subcomponent>"
        )
        raw = _arch_doc(subcomponents=bad, sub_dependencies="")
        with pytest.raises(ValidationError, match="unexpected child <kind>"):
            _validate(raw, known_subresp_ids={"resp_sub_sess"})

    def test_empty_name_rejected(self):
        bad = _sub("x", "", "role", "api", ("resp_sub_sess",), foundation=True)
        raw = _arch_doc(subcomponents=bad, sub_dependencies="")
        with pytest.raises(ValidationError, match="empty <name>"):
            _validate(raw, known_subresp_ids={"resp_sub_sess"})

    def test_empty_role_rejected(self):
        bad = _sub("x", "Name", "", "api", ("resp_sub_sess",), foundation=True)
        raw = _arch_doc(subcomponents=bad, sub_dependencies="")
        with pytest.raises(ValidationError, match="empty <role>"):
            _validate(raw, known_subresp_ids={"resp_sub_sess"})

    def test_empty_responsibilities_rejected(self):
        bad = _sub("x", "Name", "role", "api", (), foundation=True)
        raw = _arch_doc(subcomponents=bad, sub_dependencies="")
        with pytest.raises(ValidationError, match="empty <responsibilities>"):
            _validate(raw, known_subresp_ids={"resp_sub_sess"})

    def test_unknown_subresp_rejected(self):
        bad = _sub("x", "Name", "role", "api", ("resp_unknown1",), foundation=True)
        raw = _arch_doc(subcomponents=bad, sub_dependencies="")
        with pytest.raises(ValidationError, match="unknown subresponsibility"):
            _validate(raw, known_subresp_ids={"resp_sub_sess"})


class TestSubcomponentCoverage:
    def test_unassigned_subresp_rejected(self):
        # Two subs cover only two of three known subresps
        subs = _sub("store", "SessionStore", "x", "x", ("resp_sub_sess",)) + _sub(
            "foundation",
            "Foundation",
            "x",
            "x",
            ("resp_sub_found",),
            foundation=True,
        )
        raw = _arch_doc(
            subcomponents=subs,
            sub_dependencies='<dep from="store" to="foundation"/>',
        )
        with pytest.raises(ValidationError, match="does not assign every pre-minted"):
            _validate(raw)

    def test_double_assigned_subresp_rejected(self):
        subs = (
            _sub("store", "SessionStore", "x", "x", ("resp_sub_sess", "resp_sub_cred"))
            + _sub("gate", "CredentialGate", "x", "x", ("resp_sub_cred",))
            + _sub(
                "foundation",
                "Foundation",
                "x",
                "x",
                ("resp_sub_found",),
                foundation=True,
            )
        )
        raw = _arch_doc(
            subcomponents=subs,
            sub_dependencies=(
                '<dep from="store" to="foundation"/><dep from="gate" to="foundation"/>'
            ),
        )
        with pytest.raises(ValidationError, match="assigned to both"):
            _validate(raw)

    def test_empty_subcomponents_with_known_subresps_rejected(self):
        # Un-fanned-out is only legal when there are no subresps.
        # If subreqs produced subresps, you must decompose.
        raw = _arch_doc(subcomponents="", sub_dependencies="")
        with pytest.raises(ValidationError, match="pre-minted subresponsibilities"):
            _validate(raw)


class TestFoundationSubcomponent:
    def test_no_foundation_rejected_when_decomposing(self):
        subs = (
            _sub("store", "SessionStore", "x", "x", ("resp_sub_sess",))
            + _sub("gate", "CredentialGate", "x", "x", ("resp_sub_cred",))
            + _sub("config", "Config", "x", "x", ("resp_sub_found",))
        )
        raw = _arch_doc(subcomponents=subs, sub_dependencies="")
        with pytest.raises(ValidationError, match="no foundation subcomponent"):
            _validate(raw)

    def test_multiple_foundations_rejected(self):
        subs = (
            _sub("store", "S", "x", "x", ("resp_sub_sess",), foundation=True)
            + _sub("gate", "G", "x", "x", ("resp_sub_cred",))
            + _sub(
                "foundation",
                "Foundation",
                "x",
                "x",
                ("resp_sub_found",),
                foundation=True,
            )
        )
        raw = _arch_doc(subcomponents=subs, sub_dependencies="")
        with pytest.raises(ValidationError, match="2 foundation subcomponents"):
            _validate(raw)


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

    def test_all_foundation_deps_present_accepted(self):
        doc = _validate(
            _arch_doc(
                subcomponents=_default_subcomponents(),
                sub_dependencies=_DEFAULT_SUB_DEPS,
            )
        )
        assert len(doc.sub_deps) == 2
        assert all(d.to_alias == "foundation" for d in doc.sub_deps)
