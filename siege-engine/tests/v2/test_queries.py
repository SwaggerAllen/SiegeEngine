"""Tests for backend.graph.queries helpers that need explicit coverage.

The other helpers are exercised indirectly via route / handler /
reducer tests. ``get_component_context`` is the first helper
that's non-trivial enough to warrant dedicated tests — it
fetches from six different tables and has edge cases around
missing fragments and dep-graph direction.
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
from backend.graph.queries import (
    get_component_context,
    most_recent_discarded_draft_content,
    pending_draft_kinds_by_comp,
)
from backend.graph.reducer import append_event
from backend.graph.subrequirements import bootstrap_subreqs_node
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


def _seed_resp(
    session: Session, project_id: str, name: str, order: int, parent: str | None = None
) -> str:
    rid = mint(session, Kind.RESP)
    append_event(
        session,
        project_id,
        ev.NodeCreated(
            node_id=rid,
            tier="resp",
            kind="domain",
            parent_id=parent,
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
) -> str:
    comp_id = mint(session, Kind.COMP)
    append_event(
        session,
        project_id,
        ev.NodeCreated(
            node_id=comp_id,
            tier="comp",
            kind="domain",
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
    for parent_id in parent_resp_ids:
        edge_id = mint(session, Kind.EDGE)
        append_event(
            session,
            project_id,
            ev.EdgeCreated(
                edge_id=edge_id,
                edge_type="decomposition",
                source_id=parent_id,
                target_id=comp_id,
            ),
        )
    return comp_id


def _seed_dep(session: Session, project_id: str, from_comp: str, to_comp: str) -> str:
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
    return edge_id


@pytest.fixture()
def seeded(db):
    """Project with auth + billing + foundation components, resps, and deps.

    Shape: billing depends on auth + foundation, auth depends on foundation.
    Each component has techspec + pubapi fragments. billing has a subresp.
    """
    project_id = str(uuid.uuid4())
    db.add(Project(id=project_id, name="T", git_repo_path="/tmp/t"))
    db.flush()

    resp_auth = _seed_resp(db, project_id, "Authentication", 0)
    resp_bill = _seed_resp(db, project_id, "Billing", 1)
    resp_found = _seed_resp(db, project_id, "Foundation", 2)

    comp_auth = _seed_component(
        db,
        project_id,
        "AuthService",
        0,
        [resp_auth],
        techspec="Identify callers.",
        pubapi="authenticate(creds).",
    )
    comp_billing = _seed_component(
        db,
        project_id,
        "BillingService",
        1,
        [resp_bill],
        techspec="Handle payments.",
        pubapi="get_billing_state(id).",
    )
    comp_foundation = _seed_component(
        db,
        project_id,
        "Foundation",
        2,
        [resp_found],
        techspec="Project root.",
        pubapi="load_settings().",
    )

    _seed_dep(db, project_id, comp_billing, comp_auth)
    _seed_dep(db, project_id, comp_billing, comp_foundation)
    _seed_dep(db, project_id, comp_auth, comp_foundation)

    # Subresp under billing
    subresp = mint(db, Kind.RESP)
    append_event(
        db,
        project_id,
        ev.NodeCreated(
            node_id=subresp,
            tier="resp",
            kind="domain",
            parent_id=comp_billing,
            name="Tokenization",
            display_order=0,
            content="Convert cards to tokens.",
        ),
    )

    bootstrap_subreqs_node(db, project_id, comp_billing)
    db.commit()
    return {
        "project_id": project_id,
        "comp_auth": comp_auth,
        "comp_billing": comp_billing,
        "comp_foundation": comp_foundation,
        "resp_auth": resp_auth,
        "resp_bill": resp_bill,
        "resp_found": resp_found,
        "subresp": subresp,
    }


class TestGetComponentContext:
    def test_bundles_everything_for_a_non_foundation_comp(self, db, seeded):
        ctx = get_component_context(db, seeded["comp_billing"])

        assert ctx.node.id == seeded["comp_billing"]
        assert ctx.node.name == "BillingService"
        assert ctx.techspec == "Handle payments."
        assert ctx.pubapi == "get_billing_state(id)."

        # Parent resps: just "Billing"
        assert [r.id for r in ctx.parent_resps] == [seeded["resp_bill"]]

        # Subresps: the one we seeded under billing
        assert [r.id for r in ctx.subresps] == [seeded["subresp"]]

        # Outbound deps: billing → auth, billing → foundation
        outbound_ids = {n.id for n in ctx.outbound_deps}
        assert outbound_ids == {seeded["comp_auth"], seeded["comp_foundation"]}

        # Inbound deps: nothing points at billing
        assert ctx.inbound_deps == ()

    def test_inbound_deps_for_foundation(self, db, seeded):
        ctx = get_component_context(db, seeded["comp_foundation"])

        # Foundation has no outbound deps
        assert ctx.outbound_deps == ()

        # Both auth and billing point at foundation
        inbound_ids = {n.id for n in ctx.inbound_deps}
        assert inbound_ids == {seeded["comp_auth"], seeded["comp_billing"]}

    def test_mixed_directions_for_auth(self, db, seeded):
        ctx = get_component_context(db, seeded["comp_auth"])

        # Auth depends on foundation (outbound)
        assert [n.id for n in ctx.outbound_deps] == [seeded["comp_foundation"]]

        # Billing depends on auth (inbound)
        assert [n.id for n in ctx.inbound_deps] == [seeded["comp_billing"]]

    def test_missing_fragments_return_empty_strings(self, db, seeded):
        # Seed a component with no fragments
        comp_id = _seed_component(db, seeded["project_id"], "NoFragments", 3, [seeded["resp_auth"]])
        db.commit()

        ctx = get_component_context(db, comp_id)
        assert ctx.techspec == ""
        assert ctx.pubapi == ""
        assert ctx.node.name == "NoFragments"

    def test_component_with_no_subresps(self, db, seeded):
        ctx = get_component_context(db, seeded["comp_auth"])
        assert ctx.subresps == ()

    def test_unknown_component_raises(self, db, seeded):
        with pytest.raises(ValueError, match="No node with id"):
            get_component_context(db, "comp_missingX")

    def test_non_component_node_raises(self, db, seeded):
        with pytest.raises(ValueError, match="not a component"):
            get_component_context(db, seeded["resp_auth"])


# ── pending_draft_kinds_by_comp ──────────────────────────────────────


def _seed_pending_node_draft(session: Session, project_id: str, target_id: str) -> None:
    """Emit a DraftGenerated event targeting ``target_id``."""
    import secrets

    draft_id = f"draft_{secrets.token_hex(8)}"
    batch_id = f"batch_{secrets.token_hex(8)}"
    append_event(
        session,
        project_id,
        ev.DraftGenerated(
            draft_id=draft_id,
            target_type="node",
            target_id=target_id,
            content="<stub>pending</stub>",
            batch_id=batch_id,
        ),
    )


def _seed_subreqs_node(session: Session, project_id: str, owning_comp_id: str) -> str:
    """Seed a subreqs_* node parented to a top-level comp.

    Mirrors ``bootstrap_subreqs_node`` but without the tier
    bootstrap side effects — this helper's only job is to
    produce a subreqs node whose ``parent_id`` is the owning
    comp, so the pending-draft helper can attribute its draft
    back to that comp.
    """
    subreqs_id = mint(session, Kind.SUBREQS)
    append_event(
        session,
        project_id,
        ev.NodeCreated(
            node_id=subreqs_id,
            tier="subreqs",
            kind="domain",
            parent_id=owning_comp_id,
            name="subreqs for comp",
            display_order=0,
            content="",
        ),
    )
    return subreqs_id


class TestPendingDraftKindsByComp:
    def test_empty_when_no_pending_drafts(self, db, seeded):
        assert pending_draft_kinds_by_comp(db, seeded["project_id"]) == {}

    def test_comparch_kind_for_top_level_comp_draft(self, db, seeded):
        _seed_pending_node_draft(db, seeded["project_id"], seeded["comp_billing"])
        db.commit()
        result = pending_draft_kinds_by_comp(db, seeded["project_id"])
        assert result == {seeded["comp_billing"]: "comparch"}

    def test_subreqs_kind_reported_under_owning_comp(self, db, seeded):
        subreqs_id = _seed_subreqs_node(db, seeded["project_id"], seeded["comp_billing"])
        _seed_pending_node_draft(db, seeded["project_id"], subreqs_id)
        db.commit()
        result = pending_draft_kinds_by_comp(db, seeded["project_id"])
        # Reported under comp_billing (the subreqs node's parent),
        # not under subreqs_id — the dashboard surfaces waiting
        # state per component, not per bootstrap node.
        assert result == {seeded["comp_billing"]: "subreqs"}

    def test_subcomparch_kind_for_subcomponent_draft(self, db, seeded):
        # Mint a subcomponent under comp_billing and seed a draft on it.
        sub_id = mint(db, Kind.COMP)
        append_event(
            db,
            seeded["project_id"],
            ev.NodeCreated(
                node_id=sub_id,
                tier="comp",
                kind="domain",
                parent_id=seeded["comp_billing"],
                name="TokenStore",
                display_order=0,
                content="",
            ),
        )
        _seed_pending_node_draft(db, seeded["project_id"], sub_id)
        db.commit()
        result = pending_draft_kinds_by_comp(db, seeded["project_id"])
        assert result == {sub_id: "subcomparch"}

    def test_multiple_comps_each_waiting_on_their_own_kind(self, db, seeded):
        subreqs_id = _seed_subreqs_node(db, seeded["project_id"], seeded["comp_auth"])
        _seed_pending_node_draft(db, seeded["project_id"], subreqs_id)
        _seed_pending_node_draft(db, seeded["project_id"], seeded["comp_billing"])
        db.commit()
        result = pending_draft_kinds_by_comp(db, seeded["project_id"])
        assert result == {
            seeded["comp_auth"]: "subreqs",
            seeded["comp_billing"]: "comparch",
        }

    def test_non_pending_drafts_are_excluded(self, db, seeded):
        # Generate a draft, then approve it — the DraftApproved
        # event flips its status to "applied" and it should not
        # appear in the pending set.
        draft_id = "draft_applied01"
        append_event(
            db,
            seeded["project_id"],
            ev.DraftGenerated(
                draft_id=draft_id,
                target_type="node",
                target_id=seeded["comp_billing"],
                content="<stub>applied</stub>",
                batch_id="batch_applied01",
            ),
        )
        append_event(db, seeded["project_id"], ev.DraftApproved(draft_id=draft_id))
        db.commit()
        assert pending_draft_kinds_by_comp(db, seeded["project_id"]) == {}


# ── most_recent_discarded_draft_content ──────────────────────────────


def _seed_and_discard_draft(
    session: Session,
    project_id: str,
    target_id: str,
    content: str,
    *,
    reason: str | None = "user_regen",
) -> str:
    """Emit DraftGenerated + DraftDiscarded so the row lands as discarded.

    ``reason`` defaults to ``"user_regen"`` — the discard path all
    tests exercised pre-auto-revision. Pass ``None`` to simulate
    a legacy event (no reason recorded) or ``"auto_revision"`` to
    simulate an AI-revision intermediate.
    """
    import secrets

    draft_id = f"draft_{secrets.token_hex(8)}"
    append_event(
        session,
        project_id,
        ev.DraftGenerated(
            draft_id=draft_id,
            target_type="node",
            target_id=target_id,
            content=content,
            batch_id=f"batch_{secrets.token_hex(8)}",
        ),
    )
    append_event(
        session,
        project_id,
        ev.DraftDiscarded(draft_id=draft_id, reason=reason),
    )
    return draft_id


class TestMostRecentDiscardedDraftContent:
    def test_returns_none_when_no_discards_exist(self, db, seeded):
        # Brand-new bootstrap: no drafts, discarded or otherwise.
        assert (
            most_recent_discarded_draft_content(
                db,
                seeded["project_id"],
                seeded["comp_billing"],
            )
            is None
        )

    def test_ignores_pending_and_applied_drafts(self, db, seeded):
        # One pending draft, one approved — neither is discarded,
        # so the helper should still return None.
        _seed_pending_node_draft(db, seeded["project_id"], seeded["comp_billing"])
        applied_id = "draft_applied02"
        append_event(
            db,
            seeded["project_id"],
            ev.DraftGenerated(
                draft_id=applied_id,
                target_type="node",
                target_id=seeded["comp_billing"],
                content="<stub>approved</stub>",
                batch_id="batch_applied02",
            ),
        )
        append_event(db, seeded["project_id"], ev.DraftApproved(draft_id=applied_id))
        db.commit()
        assert (
            most_recent_discarded_draft_content(
                db,
                seeded["project_id"],
                seeded["comp_billing"],
            )
            is None
        )

    def test_returns_content_of_most_recent_discarded(self, db, seeded):
        import time

        _seed_and_discard_draft(
            db,
            seeded["project_id"],
            seeded["comp_billing"],
            "<sysarch>v1</sysarch>",
        )
        # updated_at resolution on SQLite is seconds; sleep briefly
        # so the second discard sorts after the first.
        time.sleep(1.1)
        _seed_and_discard_draft(
            db,
            seeded["project_id"],
            seeded["comp_billing"],
            "<sysarch>v2</sysarch>",
        )
        db.commit()
        assert (
            most_recent_discarded_draft_content(
                db,
                seeded["project_id"],
                seeded["comp_billing"],
            )
            == "<sysarch>v2</sysarch>"
        )

    def test_scopes_by_target_id(self, db, seeded):
        # Discard against comp_auth, query against comp_billing:
        # must not leak across targets.
        _seed_and_discard_draft(
            db,
            seeded["project_id"],
            seeded["comp_auth"],
            "<sysarch>auth</sysarch>",
        )
        db.commit()
        assert (
            most_recent_discarded_draft_content(
                db,
                seeded["project_id"],
                seeded["comp_billing"],
            )
            is None
        )
        assert (
            most_recent_discarded_draft_content(
                db,
                seeded["project_id"],
                seeded["comp_auth"],
            )
            == "<sysarch>auth</sysarch>"
        )

    def test_scopes_by_project_id(self, db, seeded):
        # Seed a discard under a different project with the same
        # target_id; the helper must not return it when querying
        # the original project.
        other_project = str(uuid.uuid4())
        db.add(Project(id=other_project, name="other", git_repo_path="/tmp/o"))
        db.flush()
        _seed_and_discard_draft(
            db,
            other_project,
            seeded["comp_billing"],
            "<sysarch>leak</sysarch>",
        )
        db.commit()
        assert (
            most_recent_discarded_draft_content(
                db,
                seeded["project_id"],
                seeded["comp_billing"],
            )
            is None
        )

    def test_skips_auto_revision_discards(self, db, seeded):
        # Phase 12 auto-revision: intermediate passes are discarded
        # with ``reason="auto_revision"``. The diff helper must skip
        # them and return the previous user-visible discard instead.
        import time

        _seed_and_discard_draft(
            db,
            seeded["project_id"],
            seeded["comp_billing"],
            "<sysarch>user-visible v1</sysarch>",
            reason="user_regen",
        )
        time.sleep(1.1)
        # Auto-revision intermediate landed after — most recent by
        # timestamp, but must be filtered out.
        _seed_and_discard_draft(
            db,
            seeded["project_id"],
            seeded["comp_billing"],
            "<sysarch>mid-loop intermediate</sysarch>",
            reason="auto_revision",
        )
        db.commit()
        assert (
            most_recent_discarded_draft_content(
                db,
                seeded["project_id"],
                seeded["comp_billing"],
            )
            == "<sysarch>user-visible v1</sysarch>"
        )

    def test_accepts_legacy_discards_with_null_reason(self, db, seeded):
        # Events emitted before the reason field was added have
        # ``reason=None``; the reducer projects NULL. Those are all
        # user-initiated by construction and must still qualify as
        # the diff baseline.
        _seed_and_discard_draft(
            db,
            seeded["project_id"],
            seeded["comp_billing"],
            "<sysarch>legacy</sysarch>",
            reason=None,
        )
        db.commit()
        assert (
            most_recent_discarded_draft_content(
                db,
                seeded["project_id"],
                seeded["comp_billing"],
            )
            == "<sysarch>legacy</sysarch>"
        )
