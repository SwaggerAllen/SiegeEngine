"""Tests for backend.graph.parsers.validators.validate_sysarch.

Parallels test_features_validator.py and test_requirements_validator.py.
Covers structural validation, alias rules, resp assignment coverage,
foundation requirement, policy sub-grammar, dep cycle detection, and
domain-parent direction enforcement.
"""

from __future__ import annotations

import pytest

from backend.graph.parsers.validators import (
    ValidationError,
    validate_policy_blob,
    validate_sysarch,
)
from backend.graph.parsers.xml_sections import TagNode, extract_tag_tree


def _parse(raw: str) -> TagNode:
    return extract_tag_tree(raw, "sysarch")


# Fixed known-resp set used across tests. Three resps across three
# components keeps the invariants exercisable without bloat.
KNOWN_RESPS = {"resp_auth00001", "resp_billing001", "resp_config001"}


def _comp(
    alias: str,
    name: str,
    kind: str,
    role: str,
    api_intent: str,
    resp_ids: tuple[str, ...],
    *,
    foundation: bool = False,
    purpose: str | None = None,
    owned_invariants: tuple[str, ...] | None = None,
    primary_operations: tuple[str, ...] | None = None,
) -> str:
    """Build a ``<component>`` XML blob in the micro-field grammar.

    ``role`` and ``api_intent`` are still positional for test-site
    brevity but are now used as defaults for ``purpose`` / first
    ``operation`` respectively when the richer fields aren't
    provided explicitly. Tests that exercise the new micro-fields
    pass them directly.
    """
    resp_xml = "".join(f'<resp id="{rid}"/>' for rid in resp_ids)
    foundation_marker = "<foundation/>" if foundation else ""
    actual_purpose = purpose if purpose is not None else (role or f"{name} exists.")
    invariants = owned_invariants or (
        f"{name} invariant one",
        f"{name} invariant two",
    )
    operations = primary_operations or (
        api_intent or f"do {name} thing one",
        f"do {name} thing two",
        f"do {name} thing three",
    )
    inv_xml = "".join(f"<invariant>{inv}</invariant>" for inv in invariants)
    op_xml = "".join(f"<operation>{op}</operation>" for op in operations)
    return (
        f'<component alias="{alias}">'
        f"<name>{name}</name>"
        f"<kind>{kind}</kind>"
        f"<purpose>{actual_purpose}</purpose>"
        f"<owned-invariants>{inv_xml}</owned-invariants>"
        f"<primary-operations>{op_xml}</primary-operations>"
        f"<responsibilities>{resp_xml}</responsibilities>"
        f"{foundation_marker}"
        "</component>"
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


def _default_techspec() -> str:
    """Standard structured techspec for happy-path tests."""
    return (
        "<techspec>"
        "<runtime>Python 3.11 FastAPI single-process async loop.</runtime>"
        "<persistence>PostgreSQL via SQLAlchemy with typed-ID keys.</persistence>"
        "<write-path>Event-sourced reducer; no direct ORM writes.</write-path>"
        "<concurrency>Async handlers + custom worker pool.</concurrency>"
        "<testing>pytest with an integration drain harness.</testing>"
        "<deploy>Docker on Fly.io with a Postgres sidecar.</deploy>"
        "<technologies>FastAPI, SQLAlchemy, PostgreSQL, React 18.</technologies>"
        "</techspec>"
    )


def _sysarch(
    *,
    techspec: str | None = None,
    components: str = "",
    policies: str = "",
    dependencies: str = "",
    domain_parent: str = "",
) -> str:
    """Assemble a ``<sysarch>`` XML doc from section fragments.

    ``techspec`` accepts either a raw ``<techspec>...</techspec>``
    block or ``None`` (for the default structured block) or an
    empty string (for a deliberately-empty block used by negative
    tests).
    """
    if techspec is None:
        ts_block = _default_techspec()
    elif techspec == "":
        ts_block = "<techspec></techspec>"
    elif techspec.startswith("<techspec"):
        ts_block = techspec
    else:
        # Raw content — wrap it (used by negative tests that
        # want to feed plain prose into the labeled-block shape).
        ts_block = f"<techspec>{techspec}</techspec>"
    return (
        "<sysarch>"
        f"{ts_block}"
        f"<components>{components}</components>"
        f"<policies>{policies}</policies>"
        f"<dependencies>{dependencies}</dependencies>"
        f"<domain-parent>{domain_parent}</domain-parent>"
        "</sysarch>"
    )


def _default_components() -> str:
    """Three-component happy-path layout covering all three KNOWN_RESPS."""
    return (
        _comp(
            "auth",
            "Authentication",
            "domain",
            "Identify callers and maintain session state.",
            "authenticate(creds) -> Session; resolve_session(token) -> Principal.",
            ("resp_auth00001",),
        )
        + _comp(
            "billing",
            "Billing Service",
            "domain",
            "Handle subscription state and payment collection.",
            "get_billing_state(account_id); record_payment(account_id, amount).",
            ("resp_billing001",),
        )
        + _comp(
            "foundation",
            "Foundation",
            "domain",
            "Own the project root, build config, shared utilities, entry point.",
            "load_settings(); configure_logging(); shared base classes.",
            ("resp_config001",),
            foundation=True,
        )
    )


# Every non-foundation component in _default_components() must have
# a <dep> edge to "foundation" after the Phase 3 stage 2 foundation-
# dependency rule landed. Tests that don't specifically exercise
# dependency validation use this helper to keep the noise down.
_DEFAULT_DEPS = '<dep from="auth" to="foundation"/><dep from="billing" to="foundation"/>'


class TestHappyPath:
    def test_minimal_valid_sysarch(self):
        doc = validate_sysarch(
            _parse(_sysarch(components=_default_components(), dependencies=_DEFAULT_DEPS)),
            known_top_level_resp_ids=KNOWN_RESPS,
        )
        assert doc.techspec.runtime.startswith("Python 3.11")
        assert "PostgreSQL" in doc.techspec.technologies
        assert [c.alias for c in doc.components] == ["auth", "billing", "foundation"]
        assert doc.policies == ()
        assert len(doc.deps) == 2
        assert doc.domain_parents == ()
        # Foundation flag preserved
        assert [c.is_foundation for c in doc.components] == [False, False, True]

    def test_with_policies_and_edges(self):
        components = _default_components() + _comp(
            "ui_billing",
            "Billing UI",
            "presentational",
            "Render the billing dashboard.",
            "BillingDashboard component, tied to the billing API.",
            (),
        )
        # ui_billing has zero resps — it's purely presentational. But
        # the validator requires at least one resp per component, so
        # this would actually fail. Add a resp specifically for the UI.
        components = _default_components().replace(
            _comp(
                "foundation",
                "Foundation",
                "domain",
                "Own the project root, build config, shared utilities, entry point.",
                "load_settings(); configure_logging(); shared base classes.",
                ("resp_config001",),
                foundation=True,
            ),
            "",  # remove foundation
        )
        # Rebuild with a UI component that mirrors its domain parent's
        # resp. Presentational components can no longer have unique
        # resps — they must share resps with their domain parent.
        known = {"resp_auth00001", "resp_billing001", "resp_config001"}
        components = (
            _comp(
                "auth",
                "Authentication",
                "domain",
                "Identify callers.",
                "authenticate(creds) -> Session.",
                ("resp_auth00001",),
            )
            + _comp(
                "billing",
                "Billing",
                "domain",
                "Handle payments.",
                "get_billing_state(id).",
                ("resp_billing001",),
            )
            + _comp(
                "foundation",
                "Foundation",
                "domain",
                "Project root and shared utilities.",
                "load_settings().",
                ("resp_config001",),
                foundation=True,
            )
            + _comp(
                "ui_billing",
                "Billing UI",
                "presentational",
                "Render the billing dashboard.",
                "BillingDashboard view.",
                ("resp_billing001",),
            )
        )
        xml = _sysarch(
            components=components,
            policies=_policy(
                "Telemetry",
                "any LLM call",
                "resp_config001",
                "Record tokens for audit.",
            ),
            dependencies=(
                '<dep from="billing" to="auth"/>'
                '<dep from="billing" to="foundation"/>'
                '<dep from="auth" to="foundation"/>'
                '<dep from="ui_billing" to="billing"/>'
                '<dep from="ui_billing" to="foundation"/>'
            ),
            domain_parent='<parent from="ui_billing" to="billing"/>',
        )
        doc = validate_sysarch(_parse(xml), known_top_level_resp_ids=known)
        assert len(doc.components) == 4
        assert len(doc.policies) == 1
        assert doc.policies[0].name == "Telemetry"
        assert doc.policies[0].required_resp_id == "resp_config001"
        assert len(doc.deps) == 5
        assert len(doc.domain_parents) == 1
        assert doc.domain_parents[0].from_alias == "ui_billing"
        assert doc.domain_parents[0].to_alias == "billing"


class TestRootAndSectionOrder:
    def test_wrong_root_rejected(self):
        tree = TagNode(tag="features", text="", children=[])
        with pytest.raises(ValidationError, match="Expected root tag <sysarch>"):
            validate_sysarch(tree, known_top_level_resp_ids=set())

    def test_missing_section_rejected(self):
        # Omit <dependencies>
        raw = (
            "<sysarch>"
            "<techspec>x</techspec>"
            f"<components>{_default_components()}</components>"
            "<policies></policies>"
            "<domain-parent></domain-parent>"
            "</sysarch>"
        )
        with pytest.raises(ValidationError, match="not in the required order"):
            validate_sysarch(_parse(raw), known_top_level_resp_ids=KNOWN_RESPS)

    def test_wrong_section_order_rejected(self):
        # Swap policies and dependencies
        raw = (
            "<sysarch>"
            "<techspec>x</techspec>"
            f"<components>{_default_components()}</components>"
            "<dependencies></dependencies>"
            "<policies></policies>"
            "<domain-parent></domain-parent>"
            "</sysarch>"
        )
        with pytest.raises(ValidationError, match="not in the required order"):
            validate_sysarch(_parse(raw), known_top_level_resp_ids=KNOWN_RESPS)

    def test_duplicate_section_rejected(self):
        raw = (
            "<sysarch>"
            "<techspec>x</techspec>"
            "<techspec>y</techspec>"
            f"<components>{_default_components()}</components>"
            "<policies></policies>"
            "<dependencies></dependencies>"
            "<domain-parent></domain-parent>"
            "</sysarch>"
        )
        with pytest.raises(ValidationError, match="more than one <techspec>"):
            validate_sysarch(_parse(raw), known_top_level_resp_ids=KNOWN_RESPS)

    def test_unknown_section_rejected(self):
        raw = (
            "<sysarch>"
            "<techspec>x</techspec>"
            f"<components>{_default_components()}</components>"
            "<policies></policies>"
            "<dependencies></dependencies>"
            "<domain-parent></domain-parent>"
            "<widgets></widgets>"
            "</sysarch>"
        )
        with pytest.raises(ValidationError, match="unexpected child <widgets>"):
            validate_sysarch(_parse(raw), known_top_level_resp_ids=KNOWN_RESPS)

    def test_empty_techspec_rejected(self):
        # Empty <techspec> (no labeled children) reads as "sections
        # not in the required order" because the structured
        # labeled-block shape is what the validator enforces now.
        raw = _sysarch(techspec="", components=_default_components())
        with pytest.raises(
            ValidationError,
            match=r"<techspec> sections are not in the required order",
        ):
            validate_sysarch(_parse(raw), known_top_level_resp_ids=KNOWN_RESPS)

    def test_techspec_missing_one_block_rejected(self):
        # Drop the <technologies> block specifically.
        partial = (
            "<techspec>"
            "<runtime>x</runtime>"
            "<persistence>x</persistence>"
            "<write-path>x</write-path>"
            "<concurrency>x</concurrency>"
            "<testing>x</testing>"
            "<deploy>x</deploy>"
            "</techspec>"
        )
        raw = _sysarch(techspec=partial, components=_default_components())
        with pytest.raises(
            ValidationError,
            match=r"<techspec> sections are not in the required order",
        ):
            validate_sysarch(_parse(raw), known_top_level_resp_ids=KNOWN_RESPS)

    def test_techspec_empty_labeled_block_rejected(self):
        # <runtime> is present but empty.
        bad = (
            "<techspec>"
            "<runtime></runtime>"
            "<persistence>x</persistence>"
            "<write-path>x</write-path>"
            "<concurrency>x</concurrency>"
            "<testing>x</testing>"
            "<deploy>x</deploy>"
            "<technologies>x</technologies>"
            "</techspec>"
        )
        raw = _sysarch(techspec=bad, components=_default_components())
        with pytest.raises(
            ValidationError,
            match=r"<techspec><runtime> is empty",
        ):
            validate_sysarch(_parse(raw), known_top_level_resp_ids=KNOWN_RESPS)


class TestComponentStructure:
    def test_missing_components_rejected(self):
        raw = _sysarch(components="")
        with pytest.raises(ValidationError, match="no <component> entries"):
            validate_sysarch(_parse(raw), known_top_level_resp_ids=set())

    def test_missing_alias_rejected(self):
        # Build a component without alias="" — use raw XML.
        bad = (
            "<component>"
            "<name>Thing</name><kind>domain</kind>"
            "<purpose>x</purpose>"
            "<owned-invariants><invariant>a</invariant><invariant>b</invariant></owned-invariants>"
            "<primary-operations>"
            "<operation>do a</operation><operation>do b</operation><operation>do c</operation>"
            "</primary-operations>"
            "<responsibilities></responsibilities>"
            "</component>"
        )
        raw = _sysarch(components=bad)
        with pytest.raises(ValidationError, match="missing the alias attribute"):
            validate_sysarch(_parse(raw), known_top_level_resp_ids=set())

    def test_invalid_alias_rejected(self):
        bad = _comp(
            "Bad-Alias!",
            "Thing",
            "domain",
            "x",
            "x",
            ("resp_auth00001",),
        )
        raw = _sysarch(components=bad)
        with pytest.raises(ValidationError, match="invalid alias"):
            validate_sysarch(_parse(raw), known_top_level_resp_ids={"resp_auth00001"})

    def test_duplicate_alias_rejected(self):
        dupe = (
            _comp(
                "billing",
                "First",
                "domain",
                "x",
                "x",
                ("resp_auth00001",),
            )
            + _comp(
                "billing",  # same alias
                "Second",
                "domain",
                "y",
                "y",
                ("resp_billing001",),
            )
            + _comp(
                "foundation",
                "Foundation",
                "domain",
                "z",
                "z",
                ("resp_config001",),
                foundation=True,
            )
        )
        raw = _sysarch(components=dupe)
        with pytest.raises(ValidationError, match="same alias 'billing'"):
            validate_sysarch(_parse(raw), known_top_level_resp_ids=KNOWN_RESPS)

    def test_invalid_kind_rejected(self):
        bad = _comp(
            "thing",
            "Thing",
            "weird",  # not domain or presentational
            "x",
            "x",
            ("resp_auth00001",),
            foundation=True,
        )
        raw = _sysarch(components=bad)
        with pytest.raises(ValidationError, match="invalid <kind>"):
            validate_sysarch(_parse(raw), known_top_level_resp_ids={"resp_auth00001"})

    def test_missing_name_rejected(self):
        bad = (
            '<component alias="thing">'
            "<kind>domain</kind>"
            "<purpose>x</purpose>"
            "<owned-invariants><invariant>a</invariant><invariant>b</invariant></owned-invariants>"
            "<primary-operations>"
            "<operation>do a</operation><operation>do b</operation><operation>do c</operation>"
            "</primary-operations>"
            '<responsibilities><resp id="resp_auth00001"/></responsibilities>'
            "<foundation/>"
            "</component>"
        )
        raw = _sysarch(components=bad)
        with pytest.raises(ValidationError, match="missing a <name>"):
            validate_sysarch(_parse(raw), known_top_level_resp_ids={"resp_auth00001"})

    def test_empty_purpose_rejected(self):
        bad = _comp(
            "thing",
            "Thing",
            "domain",
            "role-placeholder",
            "api-placeholder",
            ("resp_auth00001",),
            foundation=True,
            purpose="",
        )
        raw = _sysarch(components=bad)
        with pytest.raises(ValidationError, match="empty <purpose>"):
            validate_sysarch(_parse(raw), known_top_level_resp_ids={"resp_auth00001"})

    def test_too_few_invariants_rejected(self):
        bad = _comp(
            "thing",
            "Thing",
            "domain",
            "r",
            "a",
            ("resp_auth00001",),
            foundation=True,
            owned_invariants=("only one invariant",),
        )
        raw = _sysarch(components=bad)
        with pytest.raises(ValidationError, match=r"1 <invariant> entries"):
            validate_sysarch(_parse(raw), known_top_level_resp_ids={"resp_auth00001"})

    def test_too_many_invariants_rejected(self):
        bad = _comp(
            "thing",
            "Thing",
            "domain",
            "r",
            "a",
            ("resp_auth00001",),
            foundation=True,
            owned_invariants=("one", "two", "three", "four", "five"),
        )
        raw = _sysarch(components=bad)
        with pytest.raises(ValidationError, match=r"5 <invariant> entries"):
            validate_sysarch(_parse(raw), known_top_level_resp_ids={"resp_auth00001"})

    def test_too_few_operations_rejected(self):
        bad = _comp(
            "thing",
            "Thing",
            "domain",
            "r",
            "a",
            ("resp_auth00001",),
            foundation=True,
            primary_operations=("do a", "do b"),  # only 2
        )
        raw = _sysarch(components=bad)
        with pytest.raises(ValidationError, match=r"2 <operation> entries"):
            validate_sysarch(_parse(raw), known_top_level_resp_ids={"resp_auth00001"})

    def test_too_many_operations_rejected(self):
        bad = _comp(
            "thing",
            "Thing",
            "domain",
            "r",
            "a",
            ("resp_auth00001",),
            foundation=True,
            primary_operations=tuple(f"op{i}" for i in range(7)),
        )
        raw = _sysarch(components=bad)
        with pytest.raises(ValidationError, match=r"7 <operation> entries"):
            validate_sysarch(_parse(raw), known_top_level_resp_ids={"resp_auth00001"})

    def test_empty_responsibilities_rejected(self):
        bad = _comp(
            "thing",
            "Thing",
            "domain",
            "x",
            "x",
            (),  # no resps
            foundation=True,
        )
        raw = _sysarch(components=bad)
        with pytest.raises(ValidationError, match="empty <responsibilities>"):
            validate_sysarch(_parse(raw), known_top_level_resp_ids={"resp_auth00001"})


class TestFoundationRequirement:
    def test_no_foundation_rejected(self):
        # Replace the default (which has foundation=True) with a
        # layout that has none.
        comps = (
            _comp("auth", "A", "domain", "x", "x", ("resp_auth00001",))
            + _comp("billing", "B", "domain", "x", "x", ("resp_billing001",))
            + _comp("config", "C", "domain", "x", "x", ("resp_config001",))
        )
        raw = _sysarch(components=comps)
        with pytest.raises(ValidationError, match="no foundation component"):
            validate_sysarch(_parse(raw), known_top_level_resp_ids=KNOWN_RESPS)

    def test_multiple_foundations_rejected(self):
        comps = (
            _comp("auth", "A", "domain", "x", "x", ("resp_auth00001",), foundation=True)
            + _comp("billing", "B", "domain", "x", "x", ("resp_billing001",))
            + _comp(
                "foundation", "Foundation", "domain", "x", "x", ("resp_config001",), foundation=True
            )
        )
        raw = _sysarch(components=comps)
        with pytest.raises(ValidationError, match="2 foundation components"):
            validate_sysarch(_parse(raw), known_top_level_resp_ids=KNOWN_RESPS)


class TestRespAssignmentCoverage:
    def test_unassigned_resp_rejected(self):
        # Known set has 3 resps, components only assign 2.
        comps = _comp("auth", "A", "domain", "x", "x", ("resp_auth00001",)) + _comp(
            "foundation", "F", "domain", "x", "x", ("resp_config001",), foundation=True
        )
        raw = _sysarch(components=comps)
        with pytest.raises(ValidationError, match="does not assign every"):
            validate_sysarch(_parse(raw), known_top_level_resp_ids=KNOWN_RESPS)

    def test_double_assigned_resp_in_two_domains_rejected(self):
        """A resp assigned to two domain components is rejected."""
        comps = (
            _comp("auth", "A", "domain", "x", "x", ("resp_auth00001", "resp_billing001"))
            + _comp(
                "billing",
                "B",
                "domain",
                "x",
                "x",
                ("resp_billing001",),  # also in auth — two domain owners
            )
            + _comp("foundation", "F", "domain", "x", "x", ("resp_config001",), foundation=True)
        )
        raw = _sysarch(components=comps)
        with pytest.raises(ValidationError, match="assigned to domain components"):
            validate_sysarch(_parse(raw), known_top_level_resp_ids=KNOWN_RESPS)

    def test_domain_plus_presentational_mirror_accepted(self):
        """A resp in one domain + one presentational (with domain_parent) is OK."""
        comps = (
            _comp("auth", "A", "domain", "x", "x", ("resp_auth00001",))
            + _comp("billing", "B", "domain", "x", "x", ("resp_billing001",))
            + _comp("foundation", "F", "domain", "x", "x", ("resp_config001",), foundation=True)
            + _comp(
                "ui_billing",
                "BillingUI",
                "presentational",
                "Render billing.",
                "Dashboard view.",
                ("resp_billing001",),  # mirrors domain parent's resp
            )
        )
        raw = _sysarch(
            components=comps,
            dependencies=(_DEFAULT_DEPS + '<dep from="ui_billing" to="foundation"/>'),
            domain_parent='<parent from="ui_billing" to="billing"/>',
        )
        doc = validate_sysarch(_parse(raw), known_top_level_resp_ids=KNOWN_RESPS)
        assert len(doc.components) == 4

    def test_unknown_resp_id_rejected(self):
        comps = (
            _comp("auth", "A", "domain", "x", "x", ("resp_unknown1",))
            + _comp("billing", "B", "domain", "x", "x", ("resp_billing001",))
            + _comp("foundation", "F", "domain", "x", "x", ("resp_config001",), foundation=True)
        )
        raw = _sysarch(components=comps)
        with pytest.raises(ValidationError, match="unknown top-level responsibility"):
            validate_sysarch(_parse(raw), known_top_level_resp_ids=KNOWN_RESPS)


class TestPolicyValidation:
    def test_policy_happy_path(self):
        raw = _sysarch(
            components=_default_components(),
            dependencies=_DEFAULT_DEPS,
            policies=_policy(
                "Telemetry",
                "any LLM call",
                "resp_config001",
                "Record tokens for audit.",
            ),
        )
        doc = validate_sysarch(_parse(raw), known_top_level_resp_ids=KNOWN_RESPS)
        assert len(doc.policies) == 1
        assert doc.policies[0].trigger == "any LLM call"
        assert doc.policies[0].required_resp_id == "resp_config001"

    def test_policy_missing_trigger_rejected(self):
        bad = (
            "<policy>"
            "<name>Bad</name>"
            "<required>resp_config001</required>"
            "<rationale>x</rationale>"
            "</policy>"
        )
        raw = _sysarch(components=_default_components(), policies=bad)
        with pytest.raises(ValidationError, match="missing a <trigger>"):
            validate_sysarch(_parse(raw), known_top_level_resp_ids=KNOWN_RESPS)

    def test_policy_unknown_required_rejected(self):
        bad = _policy("Bad", "any call", "resp_unknown1", "x")
        raw = _sysarch(components=_default_components(), policies=bad)
        with pytest.raises(ValidationError, match="unknown responsibility"):
            validate_sysarch(_parse(raw), known_top_level_resp_ids=KNOWN_RESPS)

    def test_validate_policy_blob_happy_path(self):
        blob = _policy("Telemetry", "any LLM call", "resp_config001", "Audit.")
        policy = validate_policy_blob(blob, known_resp_ids=KNOWN_RESPS)
        assert policy.name == "Telemetry"
        assert policy.required_resp_id == "resp_config001"

    def test_validate_policy_blob_rejects_bad_required(self):
        blob = _policy("Bad", "x", "resp_unknown1", "y")
        with pytest.raises(ValidationError, match="unknown responsibility"):
            validate_policy_blob(blob, known_resp_ids=KNOWN_RESPS)


class TestDependencyEdges:
    def test_unknown_from_alias_rejected(self):
        raw = _sysarch(
            components=_default_components(),
            dependencies='<dep from="mystery" to="auth"/>',
        )
        with pytest.raises(ValidationError, match="unknown from alias 'mystery'"):
            validate_sysarch(_parse(raw), known_top_level_resp_ids=KNOWN_RESPS)

    def test_unknown_to_alias_rejected(self):
        raw = _sysarch(
            components=_default_components(),
            dependencies='<dep from="billing" to="mystery"/>',
        )
        with pytest.raises(ValidationError, match="unknown to alias 'mystery'"):
            validate_sysarch(_parse(raw), known_top_level_resp_ids=KNOWN_RESPS)

    def test_self_dep_rejected(self):
        raw = _sysarch(
            components=_default_components(),
            dependencies='<dep from="billing" to="billing"/>',
        )
        with pytest.raises(ValidationError, match="from == to"):
            validate_sysarch(_parse(raw), known_top_level_resp_ids=KNOWN_RESPS)

    def test_simple_cycle_rejected(self):
        raw = _sysarch(
            components=_default_components(),
            dependencies=('<dep from="auth" to="billing"/><dep from="billing" to="auth"/>'),
        )
        with pytest.raises(ValidationError, match="Dependency cycle detected"):
            validate_sysarch(_parse(raw), known_top_level_resp_ids=KNOWN_RESPS)

    def test_three_cycle_rejected(self):
        raw = _sysarch(
            components=_default_components(),
            dependencies=(
                '<dep from="auth" to="billing"/>'
                '<dep from="billing" to="foundation"/>'
                '<dep from="foundation" to="auth"/>'
            ),
        )
        with pytest.raises(ValidationError, match="Dependency cycle detected"):
            validate_sysarch(_parse(raw), known_top_level_resp_ids=KNOWN_RESPS)

    def test_dag_accepted(self):
        raw = _sysarch(
            components=_default_components(),
            dependencies=(
                '<dep from="billing" to="auth"/>'
                '<dep from="billing" to="foundation"/>'
                '<dep from="auth" to="foundation"/>'
            ),
        )
        doc = validate_sysarch(_parse(raw), known_top_level_resp_ids=KNOWN_RESPS)
        assert len(doc.deps) == 3


class TestDomainParentEdges:
    def test_presentational_to_domain_accepted(self):
        comps = _default_components() + _comp(
            "ui_billing",
            "Billing UI",
            "presentational",
            "Render billing dashboard.",
            "Dashboard view.",
            ("resp_billing001",),  # mirrors domain parent's resp
        )
        raw = _sysarch(
            components=comps,
            dependencies=(_DEFAULT_DEPS + '<dep from="ui_billing" to="foundation"/>'),
            domain_parent='<parent from="ui_billing" to="billing"/>',
        )
        doc = validate_sysarch(_parse(raw), known_top_level_resp_ids=KNOWN_RESPS)
        assert len(doc.domain_parents) == 1

    def test_from_domain_rejected(self):
        # both ends domain — invalid, from must be presentational.
        raw = _sysarch(
            components=_default_components(),
            domain_parent='<parent from="billing" to="auth"/>',
        )
        with pytest.raises(ValidationError, match="must be a presentational"):
            validate_sysarch(_parse(raw), known_top_level_resp_ids=KNOWN_RESPS)

    def test_to_presentational_rejected(self):
        comps = _default_components() + _comp(
            "ui_billing",
            "Billing UI",
            "presentational",
            "Render billing dashboard.",
            "Dashboard view.",
            ("resp_billing001",),  # mirrors domain parent's resp
        )
        raw = _sysarch(
            components=comps,
            # ui_billing → ui_billing is both from-presentational and
            # to-presentational; from is valid but to is wrong.
            domain_parent='<parent from="ui_billing" to="ui_billing"/>',
        )
        with pytest.raises(ValidationError, match="must be a domain"):
            validate_sysarch(_parse(raw), known_top_level_resp_ids=KNOWN_RESPS)

    def test_two_domain_parents_accepted(self):
        # Two parents is the upper bound and must validate cleanly.
        comps = _default_components() + _comp(
            "ui_combo",
            "Billing + Auth View",
            "presentational",
            "Surfaces billing status and login state together.",
            "Combined view.",
            ("resp_billing001", "resp_auth00001"),
        )
        raw = _sysarch(
            components=comps,
            dependencies=(_DEFAULT_DEPS + '<dep from="ui_combo" to="foundation"/>'),
            domain_parent=(
                '<parent from="ui_combo" to="billing"/><parent from="ui_combo" to="auth"/>'
            ),
        )
        doc = validate_sysarch(_parse(raw), known_top_level_resp_ids=KNOWN_RESPS)
        assert len(doc.domain_parents) == 2

    def test_three_domain_parents_rejected(self):
        # Three or more means the presentational has conflated
        # multiple user tasks into an application-shaped component.
        # The fix is to split it, not to widen the edge count.
        comps = _default_components() + _comp(
            "ui_everything",
            "Everything Dashboard",
            "presentational",
            "Surfaces all the things.",
            "One view to rule them all.",
            ("resp_billing001", "resp_auth00001", "resp_config001"),
        )
        raw = _sysarch(
            components=comps,
            dependencies=(_DEFAULT_DEPS + '<dep from="ui_everything" to="foundation"/>'),
            domain_parent=(
                '<parent from="ui_everything" to="billing"/>'
                '<parent from="ui_everything" to="auth"/>'
                '<parent from="ui_everything" to="foundation"/>'
            ),
        )
        with pytest.raises(
            ValidationError,
            match=r"has 3 <domain-parent> edges; the cap is 2",
        ):
            validate_sysarch(_parse(raw), known_top_level_resp_ids=KNOWN_RESPS)

    def test_cap_is_per_presentational_not_global(self):
        # Two different presentationals with two parents each must
        # validate — the cap applies per component, not in aggregate.
        comps = (
            _default_components()
            + _comp(
                "ui_one",
                "UI One",
                "presentational",
                "First task.",
                "v1",
                ("resp_billing001",),
            )
            + _comp(
                "ui_two",
                "UI Two",
                "presentational",
                "Second task.",
                "v2",
                ("resp_auth00001",),
            )
        )
        raw = _sysarch(
            components=comps,
            dependencies=(
                _DEFAULT_DEPS
                + '<dep from="ui_one" to="foundation"/>'
                + '<dep from="ui_two" to="foundation"/>'
            ),
            domain_parent=(
                '<parent from="ui_one" to="billing"/>'
                '<parent from="ui_one" to="auth"/>'
                '<parent from="ui_two" to="billing"/>'
                '<parent from="ui_two" to="auth"/>'
            ),
        )
        doc = validate_sysarch(_parse(raw), known_top_level_resp_ids=KNOWN_RESPS)
        assert len(doc.domain_parents) == 4


class TestFoundationDependency:
    def test_all_non_foundation_with_dep_accepted(self):
        raw = _sysarch(
            components=_default_components(),
            dependencies=_DEFAULT_DEPS,
        )
        doc = validate_sysarch(_parse(raw), known_top_level_resp_ids=KNOWN_RESPS)
        # Both non-foundation components have a dep to foundation
        assert len(doc.deps) == 2
        assert all(d.to_alias == "foundation" for d in doc.deps)

    def test_missing_dep_from_one_component_rejected(self):
        # auth is missing its foundation dep; billing has one.
        raw = _sysarch(
            components=_default_components(),
            dependencies='<dep from="billing" to="foundation"/>',
        )
        with pytest.raises(ValidationError, match="Missing foundation dependency from: auth"):
            validate_sysarch(_parse(raw), known_top_level_resp_ids=KNOWN_RESPS)

    def test_missing_dep_from_all_components_rejected(self):
        raw = _sysarch(
            components=_default_components(),
            dependencies="",
        )
        with pytest.raises(
            ValidationError,
            match="Missing foundation dependency from: auth, billing",
        ):
            validate_sysarch(_parse(raw), known_top_level_resp_ids=KNOWN_RESPS)

    def test_foundation_needs_no_self_dependency(self):
        # Foundation itself is exempt — no requirement to depend on
        # anything. The default components have auth and billing
        # each depending on foundation, and foundation with no
        # outbound deps. That's the intended shape.
        raw = _sysarch(
            components=_default_components(),
            dependencies=_DEFAULT_DEPS,
        )
        doc = validate_sysarch(_parse(raw), known_top_level_resp_ids=KNOWN_RESPS)
        foundation_outbound = [d for d in doc.deps if d.from_alias == "foundation"]
        assert foundation_outbound == []

    def test_policy_induced_deps_still_require_foundation(self):
        # A dep to a non-foundation target doesn't count toward the
        # foundation requirement. billing → auth isn't enough.
        raw = _sysarch(
            components=_default_components(),
            dependencies='<dep from="billing" to="auth"/><dep from="auth" to="foundation"/>',
        )
        with pytest.raises(ValidationError, match="Missing foundation dependency from: billing"):
            validate_sysarch(_parse(raw), known_top_level_resp_ids=KNOWN_RESPS)

    def test_presentational_component_also_requires_foundation_dep(self):
        # The foundation-dep rule applies to presentational components
        # too, not just domain components.
        comps = _default_components() + _comp(
            "ui_billing",
            "Billing UI",
            "presentational",
            "Render billing.",
            "Dashboard view.",
            ("resp_billing001",),  # mirrors domain parent's resp
        )
        raw = _sysarch(
            components=comps,
            dependencies=_DEFAULT_DEPS,  # no ui_billing → foundation
            domain_parent='<parent from="ui_billing" to="billing"/>',
        )
        with pytest.raises(ValidationError, match="Missing foundation dependency from: ui_billing"):
            validate_sysarch(_parse(raw), known_top_level_resp_ids=KNOWN_RESPS)
