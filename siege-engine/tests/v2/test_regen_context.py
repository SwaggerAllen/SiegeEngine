"""Tests for backend.graph.regen_context.

Covers ``build_regen_context`` DB-assembly behavior and
``format_regen_context`` pure-rendering behavior. The build tests
seed a multi-component project with fragments, edges, and
policies; the format tests synthesize ``RegenContext`` objects
directly to assert rendering without touching the DB.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database import Base
from backend.graph import events as ev
from backend.graph.fragments import FragmentKind, fragment_id
from backend.graph.ids import Kind, mint
from backend.graph.reducer import append_event
from backend.graph.regen_context import (
    build_regen_context,
    format_regen_context,
    format_regen_context_for_sub,
)
from backend.models import Project


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session: Session = factory()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _seed_feature(session: Session, project_id: str, name: str, order: int) -> str:
    fid = mint(session, Kind.FEAT)
    append_event(
        session,
        project_id,
        ev.NodeCreated(
            node_id=fid,
            tier="feat",
            kind="domain",
            parent_id=None,
            name=name,
            display_order=order,
            content=f"{name} feature.",
        ),
    )
    return fid


def _seed_top_level_resp(session: Session, project_id: str, name: str, order: int) -> str:
    rid = mint(session, Kind.RESP)
    append_event(
        session,
        project_id,
        ev.NodeCreated(
            node_id=rid,
            tier="resp",
            kind="domain",
            parent_id=None,
            name=name,
            display_order=order,
            content=f"{name} intent.",
        ),
    )
    return rid


def _seed_component(
    session: Session,
    project_id: str,
    name: str,
    order: int,
    parent_resp_ids: list[str],
    *,
    techspec: str = "",
    pubapi: str = "",
    kind: str = "domain",
) -> str:
    comp_id = mint(session, Kind.COMP)
    append_event(
        session,
        project_id,
        ev.NodeCreated(
            node_id=comp_id,
            tier="comp",
            kind=kind,
            parent_id=None,
            name=name,
            display_order=order,
            content="",
        ),
    )
    if techspec:
        append_event(
            session,
            project_id,
            ev.FragmentUpdated(
                fragment_id=fragment_id(comp_id, FragmentKind.TECHSPEC),
                owner_id=comp_id,
                fragment_kind=FragmentKind.TECHSPEC,
                new_content=techspec,
            ),
        )
    if pubapi:
        append_event(
            session,
            project_id,
            ev.FragmentUpdated(
                fragment_id=fragment_id(comp_id, FragmentKind.PUBAPI),
                owner_id=comp_id,
                fragment_kind=FragmentKind.PUBAPI,
                new_content=pubapi,
            ),
        )
    for pid in parent_resp_ids:
        edge_id = mint(session, Kind.EDGE)
        append_event(
            session,
            project_id,
            ev.EdgeCreated(
                edge_id=edge_id,
                edge_type="decomposition",
                source_id=pid,
                target_id=comp_id,
            ),
        )
    return comp_id


def _seed_feat_resp_edge(session: Session, project_id: str, feat_id: str, resp_id: str) -> None:
    edge_id = mint(session, Kind.EDGE)
    append_event(
        session,
        project_id,
        ev.EdgeCreated(
            edge_id=edge_id,
            edge_type="decomposition",
            source_id=feat_id,
            target_id=resp_id,
        ),
    )


def _seed_dep_edge(session: Session, project_id: str, from_comp: str, to_comp: str) -> None:
    edge_id = mint(session, Kind.EDGE)
    append_event(
        session,
        project_id,
        ev.EdgeCreated(
            edge_id=edge_id,
            edge_type="dependency",
            source_id=from_comp,
            target_id=to_comp,
        ),
    )


def _seed_subcomponent(
    session: Session,
    project_id: str,
    parent_comp_id: str,
    name: str,
    order: int,
    *,
    techspec: str = "",
    pubapi: str = "",
    privapi: str = "",
    kind: str = "domain",
) -> str:
    """Seed a subcomponent comp_* node under an existing top-level comp."""
    sub_id = mint(session, Kind.COMP)
    append_event(
        session,
        project_id,
        ev.NodeCreated(
            node_id=sub_id,
            tier="comp",
            kind=kind,
            parent_id=parent_comp_id,
            name=name,
            display_order=order,
            content="",
        ),
    )
    for kind, content in (
        (FragmentKind.TECHSPEC, techspec),
        (FragmentKind.PUBAPI, pubapi),
        (FragmentKind.PRIVAPI, privapi),
    ):
        if content:
            append_event(
                session,
                project_id,
                ev.FragmentUpdated(
                    fragment_id=fragment_id(sub_id, kind),
                    owner_id=sub_id,
                    fragment_kind=kind,
                    new_content=content,
                ),
            )
    return sub_id


def _seed_decomp_edge(session: Session, project_id: str, source_id: str, target_id: str) -> None:
    """Emit a decomposition edge from any source to any target.

    Used to wire (parent resp → sub) and (feat → sub) edges for the
    multi-owner ``<owns>`` ownership picture, in addition to the
    feat→resp and resp→comp edges seeded elsewhere.
    """
    edge_id = mint(session, Kind.EDGE)
    append_event(
        session,
        project_id,
        ev.EdgeCreated(
            edge_id=edge_id,
            edge_type="decomposition",
            source_id=source_id,
            target_id=target_id,
        ),
    )


def _seed_parent_privapi(session: Session, project_id: str, comp_id: str, privapi: str) -> None:
    """Seed a private-surface fragment on a top-level comp."""
    append_event(
        session,
        project_id,
        ev.FragmentUpdated(
            fragment_id=fragment_id(comp_id, FragmentKind.PRIVAPI),
            owner_id=comp_id,
            fragment_kind=FragmentKind.PRIVAPI,
            new_content=privapi,
        ),
    )


def _seed_top_level_policy(session: Session, project_id: str, name: str, order: int) -> str:
    pid = mint(session, Kind.POLICY)
    append_event(
        session,
        project_id,
        ev.NodeCreated(
            node_id=pid,
            tier="policy",
            kind="domain",
            parent_id=None,
            name=name,
            display_order=order,
            content=(
                f"<policy><name>{name}</name>"
                "<trigger>any call</trigger>"
                "<required>resp_x</required>"
                "<rationale>Rationale.</rationale></policy>"
            ),
        ),
    )
    return pid


def _apply_policy(session: Session, project_id: str, policy_id: str, comp_id: str) -> None:
    edge_id = mint(session, Kind.EDGE)
    append_event(
        session,
        project_id,
        ev.EdgeCreated(
            edge_id=edge_id,
            edge_type="policy_application",
            source_id=policy_id,
            target_id=comp_id,
        ),
    )


@pytest.fixture()
def seeded(db):
    """Full-shape project: 2 features, 3 resps, 3 components,
    some deps, subresps on one component, 2 top-level policies
    (one already applied to billing).

    Returns a dict of key IDs so tests can reference them without
    re-querying.
    """
    project_id = str(uuid.uuid4())
    db.add(Project(id=project_id, name="T", git_repo_path="/tmp/t"))
    db.flush()

    feat_pay = _seed_feature(db, project_id, "Accept payments", 0)
    feat_ui = _seed_feature(db, project_id, "Dashboard", 1)

    resp_bill = _seed_top_level_resp(db, project_id, "Billing", 0)
    resp_auth = _seed_top_level_resp(db, project_id, "Authentication", 1)
    resp_found = _seed_top_level_resp(db, project_id, "Foundation", 2)

    # feat → resp decomposition: both features route to billing,
    # only the UI feature routes to auth, foundation has its own
    # cross-cutting coverage
    _seed_feat_resp_edge(db, project_id, feat_pay, resp_bill)
    _seed_feat_resp_edge(db, project_id, feat_ui, resp_bill)
    _seed_feat_resp_edge(db, project_id, feat_ui, resp_auth)
    _seed_feat_resp_edge(db, project_id, feat_pay, resp_found)
    _seed_feat_resp_edge(db, project_id, feat_ui, resp_found)

    comp_billing = _seed_component(
        db,
        project_id,
        "BillingService",
        0,
        [resp_bill],
        techspec="Handles payments and subscription state.",
        pubapi="get_billing_state(id); record_payment(id, amount).",
    )
    comp_auth = _seed_component(
        db,
        project_id,
        "AuthService",
        1,
        [resp_auth],
        techspec="Identifies callers.",
        pubapi="authenticate(creds).",
    )
    comp_foundation = _seed_component(
        db,
        project_id,
        "Foundation",
        2,
        [resp_found],
        techspec="Owns project root.",
        pubapi="load_settings().",
    )

    # billing → auth, billing → foundation, auth → foundation
    _seed_dep_edge(db, project_id, comp_billing, comp_auth)
    _seed_dep_edge(db, project_id, comp_billing, comp_foundation)
    _seed_dep_edge(db, project_id, comp_auth, comp_foundation)

    # Top-level policies
    policy_tele = _seed_top_level_policy(db, project_id, "Telemetry", 0)
    policy_audit = _seed_top_level_policy(db, project_id, "Audit", 1)

    # Telemetry is already applied to billing; audit is still a candidate
    _apply_policy(db, project_id, policy_tele, comp_billing)

    db.commit()
    return {
        "project_id": project_id,
        "feat_pay": feat_pay,
        "feat_ui": feat_ui,
        "resp_bill": resp_bill,
        "resp_auth": resp_auth,
        "resp_found": resp_found,
        "comp_billing": comp_billing,
        "comp_auth": comp_auth,
        "comp_foundation": comp_foundation,
        "policy_tele": policy_tele,
        "policy_audit": policy_audit,
    }


class TestBuildRegenContext:
    def test_full_bundle_for_billing(self, db, seeded):
        ctx = build_regen_context(db, seeded["comp_billing"])

        # Component + fragments
        assert ctx.component.id == seeded["comp_billing"]
        assert ctx.component.name == "BillingService"
        assert "Handles payments" in ctx.component_techspec
        assert "get_billing_state" in ctx.component_pubapi

        # Parent resps = just billing
        assert [r.id for r in ctx.parent_resps] == [seeded["resp_bill"]]

        # Sibling top-level comps: auth + foundation (not billing itself)
        assert set(ctx.sibling_comp_ids) == {
            seeded["comp_auth"],
            seeded["comp_foundation"],
        }

        # Dep pubapi fragments: billing has outbound deps to auth + foundation
        assert set(ctx.dep_pubapi_fragments.keys()) == {
            seeded["comp_auth"],
            seeded["comp_foundation"],
        }
        assert "authenticate" in ctx.dep_pubapi_fragments[seeded["comp_auth"]]
        assert "load_settings" in ctx.dep_pubapi_fragments[seeded["comp_foundation"]]

        # Related features: both features reach billing via decomposition
        assert set(f.id for f in ctx.related_features) == {
            seeded["feat_pay"],
            seeded["feat_ui"],
        }

        # Top-level policy candidates: both
        assert set(p.id for p in ctx.top_level_policy_candidates) == {
            seeded["policy_tele"],
            seeded["policy_audit"],
        }

        # Already applied: telemetry only
        assert [p.id for p in ctx.already_applied_policies] == [seeded["policy_tele"]]

        # Neighbor diffs scaffolding is empty on first run
        assert ctx.neighbor_diffs == {}

    def test_component_with_no_siblings(self, db):
        """A project with a single top-level component produces empty siblings."""
        project_id = str(uuid.uuid4())
        db.add(Project(id=project_id, name="Solo", git_repo_path="/tmp/solo"))
        db.flush()
        resp = _seed_top_level_resp(db, project_id, "Core", 0)
        comp = _seed_component(
            db,
            project_id,
            "CoreService",
            0,
            [resp],
            techspec="Only component.",
            pubapi="run().",
        )
        db.commit()

        ctx = build_regen_context(db, comp)
        assert ctx.sibling_comp_ids == ()
        assert ctx.sibling_comps == ()
        assert ctx.dep_pubapi_fragments == {}

    def test_missing_dep_fragment_returns_empty_string(self, db, seeded):
        """A dep whose pubapi isn't minted yet returns empty string,
        not a KeyError and not a missing dict entry."""
        # Delete the auth pubapi fragment manually
        from backend.models.node import Fragment

        auth_pubapi_id = fragment_id(seeded["comp_auth"], FragmentKind.PUBAPI)
        frag = db.get(Fragment, auth_pubapi_id)
        assert frag is not None
        db.delete(frag)
        db.commit()

        ctx = build_regen_context(db, seeded["comp_billing"])
        # Still in dict (billing depends on auth), but empty content
        assert seeded["comp_auth"] in ctx.dep_pubapi_fragments
        assert ctx.dep_pubapi_fragments[seeded["comp_auth"]] == ""

    def test_feature_walk_deduplicates(self, db, seeded):
        """feat_ui decomposes into both resp_bill and resp_auth;
        billing gets it via resp_bill. It should appear once in
        related_features, not twice."""
        ctx = build_regen_context(db, seeded["comp_billing"])
        feat_ids = [f.id for f in ctx.related_features]
        assert len(feat_ids) == len(set(feat_ids)), "related_features should be deduplicated by id"

    def test_unknown_component_raises(self, db, seeded):
        with pytest.raises(ValueError, match="No node with id"):
            build_regen_context(db, "comp_missingX")

    def test_non_component_raises(self, db, seeded):
        with pytest.raises(ValueError, match="not a component"):
            build_regen_context(db, seeded["resp_bill"])


class TestFormatRegenContext:
    def test_returns_all_expected_keys(self, db, seeded):
        ctx = build_regen_context(db, seeded["comp_billing"])
        formatted = format_regen_context(ctx)
        expected_keys = {
            "project_techspec",
            "project_policies",
            "project_dependencies",
            "project_domain_parents",
            "component_summary",
            "parent_resps_summary",
            "sibling_comps_summary",
            "dep_pubapi_summary",
            "top_level_policy_candidates_summary",
            "related_features_summary",
            "vocab_summary",
            "domain_parent_surface",
            "referenced_content_summary",
        }
        assert set(formatted.keys()) == expected_keys

    def test_component_summary_includes_name_id_and_fragments(self, db, seeded):
        ctx = build_regen_context(db, seeded["comp_billing"])
        summary = format_regen_context(ctx)["component_summary"]
        assert "BillingService" in summary
        # The header line carries the comp_* id so the LLM (and
        # debug tools) can locate "this is the current target"
        # without guessing from the name alone.
        assert seeded["comp_billing"] in summary
        assert "Handles payments" in summary
        assert "get_billing_state" in summary

    def test_parent_resps_bullets_include_ids_and_feats(self, db, seeded):
        """parent_resps_summary renders each resp as a bullet with its
        id, name, and the bracketed feat-id slice tagged on that resp.
        feat_pay tags resp_bill in the seed, so the billing context's
        resp bullet must surface it."""
        ctx = build_regen_context(db, seeded["comp_billing"])
        summary = format_regen_context(ctx)["parent_resps_summary"]
        assert seeded["resp_bill"] in summary
        assert "Billing" in summary
        assert seeded["feat_pay"] in summary

    def test_sibling_comps_summary_excludes_self(self, db, seeded):
        ctx = build_regen_context(db, seeded["comp_billing"])
        summary = format_regen_context(ctx)["sibling_comps_summary"]
        assert seeded["comp_auth"] in summary
        assert seeded["comp_foundation"] in summary
        assert seeded["comp_billing"] not in summary

    def test_dep_pubapi_summary_includes_sibling_pubapis(self, db, seeded):
        ctx = build_regen_context(db, seeded["comp_billing"])
        summary = format_regen_context(ctx)["dep_pubapi_summary"]
        # Contains both sibling pubapi contents
        assert "authenticate" in summary
        assert "load_settings" in summary

    def test_dep_pubapi_summary_empty_when_no_deps(self, db, seeded):
        ctx = build_regen_context(db, seeded["comp_foundation"])
        formatted = format_regen_context(ctx)
        # Foundation has no outbound deps
        assert formatted["dep_pubapi_summary"] == ""

    def test_policy_candidates_marks_already_applied(self, db, seeded):
        ctx = build_regen_context(db, seeded["comp_billing"])
        summary = format_regen_context(ctx)["top_level_policy_candidates_summary"]
        # Both policies listed
        assert seeded["policy_tele"] in summary
        assert seeded["policy_audit"] in summary
        # Telemetry is tagged [applied], Audit is not
        tele_line = [line for line in summary.splitlines() if seeded["policy_tele"] in line][0]
        audit_line = [line for line in summary.splitlines() if seeded["policy_audit"] in line][0]
        assert "[applied]" in tele_line
        assert "[applied]" not in audit_line

    def test_related_features_summary_lists_feature_names(self, db, seeded):
        ctx = build_regen_context(db, seeded["comp_billing"])
        summary = format_regen_context(ctx)["related_features_summary"]
        assert "Accept payments" in summary
        assert "Dashboard" in summary

    def test_format_is_pure(self, db, seeded):
        """format_regen_context should be pure — calling twice yields
        the same output without touching the DB."""
        ctx = build_regen_context(db, seeded["comp_billing"])
        a = format_regen_context(ctx)
        b = format_regen_context(ctx)
        assert a == b

    def test_plugs_into_comparch_render_user_prompt(self, db, seeded):
        """The dict returned by format_regen_context must kwargs-spread
        cleanly into the comparch render_user_prompt function."""
        from backend.graph.prompts.comparch import render_user_prompt

        ctx = build_regen_context(db, seeded["comp_billing"])
        formatted = format_regen_context(ctx)
        prompt = render_user_prompt(
            **formatted,
            prior_approved=None,
            prior_pending=None,
            feedback=None,
            parse_error=None,
        )
        # Basic sanity: prompt includes component name and at least
        # one parent resp id
        assert "BillingService" in prompt
        assert seeded["resp_bill"] in prompt


@pytest.fixture()
def seeded_with_sub(db, seeded):
    """Extend the seeded fixture with a subcomponent layout under billing.

    Seeds three subcomponents (session_store, credential_gate,
    foundation) under billing, plus the parent_resp→sub and
    feat→sub decomposition edges mimicking what comparch_mint
    emits from the parent's ``<owns>`` block, and a parent
    privapi on billing. session_store is the resp+feat owner;
    credential_gate is a co-owner of the resp (multi-owner) but
    claims no feats; foundation has empty ownership.
    """
    project_id = seeded["project_id"]
    # Give billing a private surface fragment
    _seed_parent_privapi(
        db,
        project_id,
        seeded["comp_billing"],
        "Internal: _tokenize(raw) and _rotate_keys(cutoff).",
    )

    sub_store = _seed_subcomponent(
        db,
        project_id,
        seeded["comp_billing"],
        "SessionStore",
        0,
        techspec="Persist session tokens.",
        pubapi="create_session(pid) -> Session.",
    )
    sub_gate = _seed_subcomponent(
        db,
        project_id,
        seeded["comp_billing"],
        "CredentialGate",
        1,
        techspec="Verify credentials.",
        pubapi="verify(creds) -> PrincipalId | None.",
    )
    sub_found = _seed_subcomponent(
        db,
        project_id,
        seeded["comp_billing"],
        "Foundation",
        2,
        techspec="Own the component root.",
        pubapi="load_settings(). configure_logging().",
    )

    # parent_resp → sub and feat → sub decomposition edges mirroring
    # comparch_mint's post-approval edge emissions from the parent's
    # <owns> block. session_store claims (resp_bill, feat_pay);
    # credential_gate co-claims resp_bill (multi-owner) without any
    # feat-slice; foundation has empty ownership.
    _seed_decomp_edge(db, project_id, seeded["resp_bill"], sub_store)
    _seed_decomp_edge(db, project_id, seeded["feat_pay"], sub_store)
    _seed_decomp_edge(db, project_id, seeded["resp_bill"], sub_gate)

    db.commit()
    return {
        **seeded,
        "sub_store": sub_store,
        "sub_gate": sub_gate,
        "sub_found": sub_found,
    }


class TestBuildRegenContextForSubcomponent:
    def test_populates_parent_fields(self, db, seeded_with_sub):
        ctx = build_regen_context(db, seeded_with_sub["sub_store"])
        assert ctx.parent_component is not None
        assert ctx.parent_component.id == seeded_with_sub["comp_billing"]
        assert "Handles payments" in ctx.parent_techspec
        assert "get_billing_state" in ctx.parent_pubapi
        assert "_tokenize" in ctx.parent_privapi

    def test_sibling_subcomps_excludes_self(self, db, seeded_with_sub):
        ctx = build_regen_context(db, seeded_with_sub["sub_store"])
        sibling_ids = set(ctx.sibling_subcomp_ids)
        assert seeded_with_sub["sub_gate"] in sibling_ids
        assert seeded_with_sub["sub_found"] in sibling_ids
        assert seeded_with_sub["sub_store"] not in sibling_ids

    def test_sibling_subcomp_pubapi_fragments(self, db, seeded_with_sub):
        ctx = build_regen_context(db, seeded_with_sub["sub_store"])
        assert "verify(creds)" in ctx.sibling_subcomp_pubapi_fragments[seeded_with_sub["sub_gate"]]
        assert "load_settings" in ctx.sibling_subcomp_pubapi_fragments[seeded_with_sub["sub_found"]]

    def test_sibling_comp_ids_are_parents_siblings(self, db, seeded_with_sub):
        """For a subcomponent, sibling_comp_ids holds the parent's
        sibling top-level comps, not the sub's same-parent siblings."""
        ctx = build_regen_context(db, seeded_with_sub["sub_store"])
        # Billing's siblings are auth + foundation
        assert set(ctx.sibling_comp_ids) == {
            seeded_with_sub["comp_auth"],
            seeded_with_sub["comp_foundation"],
        }

    def test_dep_pubapi_fragments_are_parents_deps(self, db, seeded_with_sub):
        """For a subcomponent, dep_pubapi_fragments holds the parent's
        outbound dep pubapis (what the parent already depends on)."""
        ctx = build_regen_context(db, seeded_with_sub["sub_store"])
        # Billing depends on auth + foundation
        assert set(ctx.dep_pubapi_fragments.keys()) == {
            seeded_with_sub["comp_auth"],
            seeded_with_sub["comp_foundation"],
        }
        assert "authenticate" in ctx.dep_pubapi_fragments[seeded_with_sub["comp_auth"]]

    def test_subcomponent_with_no_same_parent_siblings(self, db):
        project_id = str(uuid.uuid4())
        db.add(Project(id=project_id, name="Solo", git_repo_path="/tmp/solo"))
        db.flush()
        resp = _seed_top_level_resp(db, project_id, "Core", 0)
        comp = _seed_component(
            db,
            project_id,
            "CoreService",
            0,
            [resp],
            techspec="Only component.",
            pubapi="run().",
        )
        sub = _seed_subcomponent(db, project_id, comp, "OnlySub", 0, techspec="x", pubapi="y")
        db.commit()

        ctx = build_regen_context(db, sub)
        assert ctx.sibling_subcomp_ids == ()
        assert ctx.sibling_subcomps == ()
        assert ctx.sibling_subcomp_pubapi_fragments == {}

    def test_subcomponent_with_missing_parent_privapi(self, db, seeded_with_sub):
        """Missing parent privapi → empty string, no error."""
        # Delete the privapi fragment we seeded
        from backend.models.node import Fragment

        frag = db.get(
            Fragment,
            fragment_id(seeded_with_sub["comp_billing"], FragmentKind.PRIVAPI),
        )
        assert frag is not None
        db.delete(frag)
        db.commit()

        ctx = build_regen_context(db, seeded_with_sub["sub_store"])
        assert ctx.parent_privapi == ""

    def test_top_level_comp_has_empty_subcomponent_fields(self, db, seeded):
        """A top-level comp context must have None parent_component
        and empty sub-specific fields — behavior unchanged from Phase 4."""
        ctx = build_regen_context(db, seeded["comp_billing"])
        assert ctx.parent_component is None
        assert ctx.parent_techspec == ""
        assert ctx.sibling_subcomp_ids == ()


class TestFormatRegenContextForSub:
    def test_returns_all_expected_keys(self, db, seeded_with_sub):
        ctx = build_regen_context(db, seeded_with_sub["sub_store"])
        formatted = format_regen_context_for_sub(ctx)
        expected = {
            "project_techspec",
            "project_policies",
            "project_dependencies",
            "project_domain_parents",
            "subcomponent_summary",
            "parent_component_summary",
            "parent_policies",
            "parent_failure_surface",
            "owns_summary",
            "sibling_subcomps_summary",
            "parent_sibling_comps_summary",
            "dep_pubapi_summary",
            "related_features_summary",
            "vocab_summary",
            "domain_parent_surface",
            "referenced_content_summary",
        }
        assert set(formatted.keys()) == expected

    def test_subcomponent_summary_includes_name_id_and_role(self, db, seeded_with_sub):
        ctx = build_regen_context(db, seeded_with_sub["sub_store"])
        summary = format_regen_context_for_sub(ctx)["subcomponent_summary"]
        assert "SessionStore" in summary
        # The subcomponent's own comp_* id appears in the header
        # line alongside the name (Phase 6 observability fix).
        assert seeded_with_sub["sub_store"] in summary
        assert "Persist session tokens" in summary

    def test_parent_component_summary_includes_three_fragments(self, db, seeded_with_sub):
        ctx = build_regen_context(db, seeded_with_sub["sub_store"])
        summary = format_regen_context_for_sub(ctx)["parent_component_summary"]
        assert "BillingService" in summary
        assert "Handles payments" in summary  # techspec
        assert "get_billing_state" in summary  # pubapi
        assert "_tokenize" in summary  # privapi

    def test_sibling_subcomps_summary_includes_real_ids(self, db, seeded_with_sub):
        ctx = build_regen_context(db, seeded_with_sub["sub_store"])
        summary = format_regen_context_for_sub(ctx)["sibling_subcomps_summary"]
        # Aliases gone — siblings are listed by their real comp_* IDs
        # so the LLM can reference them directly in <dep to="comp_...">.
        assert seeded_with_sub["sub_gate"] in summary
        assert seeded_with_sub["sub_found"] in summary
        # Names are still shown for LLM readability
        assert "CredentialGate" in summary
        assert "Foundation" in summary
        # The sub's own id should NOT appear in its own sibling list
        assert seeded_with_sub["sub_store"] not in summary

    def test_parent_sibling_comps_summary_lists_real_ids(self, db, seeded_with_sub):
        ctx = build_regen_context(db, seeded_with_sub["sub_store"])
        summary = format_regen_context_for_sub(ctx)["parent_sibling_comps_summary"]
        assert seeded_with_sub["comp_auth"] in summary
        assert seeded_with_sub["comp_foundation"] in summary
        assert seeded_with_sub["comp_billing"] not in summary  # parent excluded

    def test_dep_pubapi_summary_from_parents_deps(self, db, seeded_with_sub):
        ctx = build_regen_context(db, seeded_with_sub["sub_store"])
        summary = format_regen_context_for_sub(ctx)["dep_pubapi_summary"]
        assert "authenticate" in summary or "load_settings" in summary

    def test_owns_summary_shows_claimed_resp_and_feat(self, db, seeded_with_sub):
        ctx = build_regen_context(db, seeded_with_sub["sub_store"])
        summary = format_regen_context_for_sub(ctx)["owns_summary"]
        # sub_store claims (resp_bill, [feat_pay]) via the seeded
        # decomposition edges that mirror comparch_mint's <owns>
        # block emissions.
        assert seeded_with_sub["resp_bill"] in summary
        assert "Billing" in summary
        assert seeded_with_sub["feat_pay"] in summary

    def test_owns_summary_empty_for_foundation_subcomp(self, db, seeded_with_sub):
        """foundation subcomp claims no parent resps in the seed; the
        owns_summary surfaces the empty-claim sentinel rather than an
        empty string so the prompt section is always present."""
        ctx = build_regen_context(db, seeded_with_sub["sub_found"])
        summary = format_regen_context_for_sub(ctx)["owns_summary"]
        assert "does not anchor any parent responsibility" in summary

    def test_raises_on_top_level_context(self, db, seeded):
        ctx = build_regen_context(db, seeded["comp_billing"])
        with pytest.raises(ValueError, match="top-level component context"):
            format_regen_context_for_sub(ctx)

    def test_plugs_into_subcomparch_render_user_prompt(self, db, seeded_with_sub):
        from backend.graph.prompts.subcomparch import render_user_prompt

        ctx = build_regen_context(db, seeded_with_sub["sub_store"])
        formatted = format_regen_context_for_sub(ctx)
        prompt = render_user_prompt(
            **formatted,
            prior_approved=None,
            prior_pending=None,
            feedback=None,
            parse_error=None,
        )
        assert "SessionStore" in prompt
        assert "BillingService" in prompt  # parent
        assert seeded_with_sub["comp_auth"] in prompt  # parent sibling comp id


# ── Phase 6: domain-parent context ───────────────────────────────────


def _seed_domain_parent_edge(
    session: Session, project_id: str, presentational_id: str, domain_id: str
) -> None:
    """Emit a ``domain_parent`` edge from presentational → domain."""
    edge_id = mint(session, Kind.EDGE)
    append_event(
        session,
        project_id,
        ev.EdgeCreated(
            edge_id=edge_id,
            edge_type="domain_parent",
            source_id=presentational_id,
            target_id=domain_id,
        ),
    )


@pytest.fixture()
def seeded_with_presentational(db, seeded):
    """Extend the seeded fixture with a presentational top-level comp.

    Adds ``comp_billing_ui`` as a presentational comp with a
    ``domain_parent`` edge pointing at ``comp_billing``. The
    presentational comp has no resps of its own (matches the real
    sysarch pattern where presentational comps often own their
    own user-facing resps; this fixture keeps the seeded dict
    shape minimal for the Phase 6 assertions).

    Also seeds a subcomponent ``sub_billing_ui_form`` under the
    presentational comp, so we can verify that subs of a
    presentational parent inherit the domain-parent bundle.
    """
    project_id = seeded["project_id"]

    comp_billing_ui = _seed_component(
        db,
        project_id,
        "BillingUI",
        3,
        [],
        techspec="React dashboard bound to billing state.",
        pubapi="BillingPage() component; useBillingState() hook.",
        kind="presentational",
    )
    _seed_domain_parent_edge(db, project_id, comp_billing_ui, seeded["comp_billing"])

    sub_billing_ui_form = _seed_subcomponent(
        db,
        project_id,
        comp_billing_ui,
        "BillingForm",
        0,
        techspec="Card-entry form.",
        pubapi="<BillingForm /> rendered inside BillingPage.",
        kind="presentational",
    )

    db.commit()
    return {
        **seeded,
        "comp_billing_ui": comp_billing_ui,
        "sub_billing_ui_form": sub_billing_ui_form,
    }


class TestBuildRegenContextDomainParent:
    def test_domain_comp_has_empty_domain_parent_bundle(self, db, seeded):
        ctx = build_regen_context(db, seeded["comp_billing"])
        assert ctx.domain_parents == ()
        assert ctx.domain_parent_techspecs == {}
        assert ctx.domain_parent_pubapis == {}

    def test_presentational_top_level_loads_domain_parent_fragments(
        self, db, seeded_with_presentational
    ):
        ctx = build_regen_context(db, seeded_with_presentational["comp_billing_ui"])
        parent_ids = [p.id for p in ctx.domain_parents]
        assert parent_ids == [seeded_with_presentational["comp_billing"]]
        billing_id = seeded_with_presentational["comp_billing"]
        assert "Handles payments" in ctx.domain_parent_techspecs[billing_id]
        assert "get_billing_state" in ctx.domain_parent_pubapis[billing_id]

    def test_subcomponent_of_presentational_parent_inherits_bundle(
        self, db, seeded_with_presentational
    ):
        ctx = build_regen_context(db, seeded_with_presentational["sub_billing_ui_form"])
        parent_ids = [p.id for p in ctx.domain_parents]
        assert parent_ids == [seeded_with_presentational["comp_billing"]]
        billing_id = seeded_with_presentational["comp_billing"]
        assert "Handles payments" in ctx.domain_parent_techspecs[billing_id]
        assert "get_billing_state" in ctx.domain_parent_pubapis[billing_id]

    def test_subcomponent_of_domain_parent_has_empty_bundle(self, db, seeded_with_sub):
        ctx = build_regen_context(db, seeded_with_sub["sub_store"])
        assert ctx.domain_parents == ()
        assert ctx.domain_parent_techspecs == {}
        assert ctx.domain_parent_pubapis == {}


class TestFormatDomainParentSurface:
    """Unit tests for the pure formatter in prompts.comparch."""

    def test_empty_parents_returns_empty_string(self):
        from backend.graph.prompts.comparch import format_domain_parent_surface

        assert format_domain_parent_surface((), {}, {}) == ""

    def test_renders_name_and_id_per_parent(self):
        from backend.graph.prompts.comparch import format_domain_parent_surface

        class _FakeNode:
            def __init__(self, node_id, name):
                self.id = node_id
                self.name = name

        parents = (_FakeNode("comp_aaa11111", "BillingService"),)
        out = format_domain_parent_surface(
            parents,
            {"comp_aaa11111": "Handles payments."},
            {"comp_aaa11111": "get_billing_state(id)."},
        )
        assert "BillingService" in out
        assert "comp_aaa11111" in out
        assert "Handles payments" in out
        assert "get_billing_state" in out
        # Fenced blocks keep domain content from being mistaken for
        # prompt directives.
        assert "```" in out

    def test_omits_empty_fragment_sections(self):
        from backend.graph.prompts.comparch import format_domain_parent_surface

        class _FakeNode:
            def __init__(self, node_id, name):
                self.id = node_id
                self.name = name

        parents = (_FakeNode("comp_aaa11111", "Billing"),)
        # Only pubapi present; techspec is empty and should not add
        # a "Technical specification" header to the output.
        out = format_domain_parent_surface(
            parents,
            {"comp_aaa11111": ""},
            {"comp_aaa11111": "get_billing_state(id)."},
        )
        assert "Technical specification" not in out
        assert "Public surface" in out


class TestFormatRegenContextDomainParent:
    def test_domain_comp_yields_empty_surface(self, db, seeded):
        ctx = build_regen_context(db, seeded["comp_billing"])
        formatted = format_regen_context(ctx)
        assert formatted["domain_parent_surface"] == ""

    def test_presentational_comp_populates_surface(self, db, seeded_with_presentational):
        ctx = build_regen_context(db, seeded_with_presentational["comp_billing_ui"])
        formatted = format_regen_context(ctx)
        surface = formatted["domain_parent_surface"]
        assert "BillingService" in surface
        assert seeded_with_presentational["comp_billing"] in surface
        assert "Handles payments" in surface  # domain techspec
        assert "get_billing_state" in surface  # domain pubapi

    def test_comparch_prompt_includes_presenting_block(self, db, seeded_with_presentational):
        from backend.graph.prompts.comparch import render_user_prompt

        ctx = build_regen_context(db, seeded_with_presentational["comp_billing_ui"])
        formatted = format_regen_context(ctx)
        prompt = render_user_prompt(
            **formatted,
            prior_approved=None,
            prior_pending=None,
            feedback=None,
            parse_error=None,
        )
        assert "# This component presents" in prompt
        assert seeded_with_presentational["comp_billing"] in prompt
        assert "Handles payments" in prompt
        assert "get_billing_state" in prompt

    def test_comparch_prompt_omits_section_for_domain_comp(self, db, seeded):
        from backend.graph.prompts.comparch import render_user_prompt

        ctx = build_regen_context(db, seeded["comp_billing"])
        formatted = format_regen_context(ctx)
        prompt = render_user_prompt(
            **formatted,
            prior_approved=None,
            prior_pending=None,
            feedback=None,
            parse_error=None,
        )
        assert "# This component presents" not in prompt


class TestFormatRegenContextForSubDomainParent:
    """Subcomparch receives the grandparent-domain context via its parent."""

    def test_domain_sub_yields_empty_surface(self, db, seeded_with_sub):
        ctx = build_regen_context(db, seeded_with_sub["sub_store"])
        formatted = format_regen_context_for_sub(ctx)
        assert formatted["domain_parent_surface"] == ""

    def test_sub_of_presentational_parent_populates_surface(self, db, seeded_with_presentational):
        ctx = build_regen_context(db, seeded_with_presentational["sub_billing_ui_form"])
        formatted = format_regen_context_for_sub(ctx)
        surface = formatted["domain_parent_surface"]
        assert "BillingService" in surface
        assert seeded_with_presentational["comp_billing"] in surface
        assert "Handles payments" in surface  # domain techspec
        assert "get_billing_state" in surface  # domain pubapi

    def test_subcomparch_prompt_includes_grandparent_block(self, db, seeded_with_presentational):
        from backend.graph.prompts.subcomparch import render_user_prompt

        ctx = build_regen_context(db, seeded_with_presentational["sub_billing_ui_form"])
        formatted = format_regen_context_for_sub(ctx)
        prompt = render_user_prompt(
            **formatted,
            prior_approved=None,
            prior_pending=None,
            feedback=None,
            parse_error=None,
        )
        assert "# Grandparent domain context" in prompt
        assert seeded_with_presentational["comp_billing"] in prompt
        assert "Handles payments" in prompt
        assert "get_billing_state" in prompt

    def test_subcomparch_prompt_omits_section_for_domain_sub(self, db, seeded_with_sub):
        from backend.graph.prompts.subcomparch import render_user_prompt

        ctx = build_regen_context(db, seeded_with_sub["sub_store"])
        formatted = format_regen_context_for_sub(ctx)
        prompt = render_user_prompt(
            **formatted,
            prior_approved=None,
            prior_pending=None,
            feedback=None,
            parse_error=None,
        )
        assert "# Grandparent domain context" not in prompt

    def test_format_domain_parent_surface_for_sub_empty(self):
        from backend.graph.prompts.subcomparch import format_domain_parent_surface_for_sub

        assert format_domain_parent_surface_for_sub((), {}, {}) == ""
