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
from backend.graph.queries import get_component_context
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
