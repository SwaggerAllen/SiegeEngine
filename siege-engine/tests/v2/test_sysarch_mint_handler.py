"""Tests for backend.graph.handlers.sysarch_mint.

Mint handler is deterministic (no LLM call) and idempotent.
Each test seeds a project with features + top-level resps +
an approved sysarch node whose content is a valid <sysarch>
blob, then asserts the mint handler emits the expected
NodeCreated / FragmentUpdated / EdgeCreated events.

The subreqs bootstrap fan-out lands inside the same transaction
as the node mints but its generation-job enqueue happens post-
commit, so tests that assert on queued jobs look at the Job
table after the handler returns.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database import Base
from backend.graph import events as ev
from backend.graph.fragments import FragmentKind, fragment_id
from backend.graph.handlers.sysarch_mint import (
    SysarchMintHandlerError,
    mint_sysarch,
)
from backend.graph.reducer import append_event
from backend.graph.sysarch import bootstrap_sysarch_node
from backend.models import Project
from backend.models.job import Job
from backend.models.node import Edge, Fragment, Node


@pytest.fixture()
def shared_session_factory(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    import backend.database as _database_mod
    import backend.graph.handlers.sysarch_mint as _handler_mod

    monkeypatch.setattr(_database_mod, "SessionLocal", factory)
    monkeypatch.setattr(_handler_mod, "SessionLocal", factory)
    yield factory
    engine.dispose()


def _mint_top_level_resp(session: Session, project_id: str, name: str, order: int) -> str:
    from backend.graph.ids import Kind, mint

    resp_id = mint(session, Kind.RESP)
    append_event(
        session,
        project_id,
        ev.NodeCreated(
            node_id=resp_id,
            tier="resp",
            kind="domain",
            parent_id=None,
            name=name,
            display_order=order,
            content=f"{name} intent.",
        ),
    )
    return resp_id


def _seed_project(session: Session) -> tuple[str, list[str]]:
    """Create a project + three top-level resps + bootstrapped sysarch node.

    Returns ``(project_id, [auth_rid, billing_rid, foundation_rid])``.
    Caller must write the approved sysarch content before calling
    the mint handler.
    """
    project_id = str(uuid.uuid4())
    session.add(Project(id=project_id, name="T", git_repo_path="/tmp/t"))
    session.flush()
    auth_rid = _mint_top_level_resp(session, project_id, "Authentication", 0)
    billing_rid = _mint_top_level_resp(session, project_id, "Billing", 1)
    foundation_rid = _mint_top_level_resp(session, project_id, "Foundation", 2)
    bootstrap_sysarch_node(session, project_id)
    session.commit()
    return project_id, [auth_rid, billing_rid, foundation_rid]


def _set_sysarch_content(session: Session, project_id: str, content: str) -> None:
    """Simulate DraftApproved by writing directly to sysarch node."""
    node = session.execute(
        select(Node).where(Node.project_id == project_id, Node.tier == "sysarch")
    ).scalar_one()
    node.content = content
    session.commit()


_TECHSPEC_STUB = (
    "<techspec>"
    "<runtime>Python 3.11 FastAPI async loop.</runtime>"
    "<persistence>PostgreSQL via SQLAlchemy.</persistence>"
    "<write-path>Event-sourced reducer; no direct ORM writes.</write-path>"
    "<concurrency>Async handlers + worker pool.</concurrency>"
    "<testing>pytest with an integration drain harness.</testing>"
    "<deploy>Docker on Fly.io with a Postgres sidecar.</deploy>"
    "<technologies>FastAPI, SQLAlchemy, PostgreSQL.</technologies>"
    "</techspec>"
)


def _comp_xml(
    alias: str,
    name: str,
    purpose: str,
    resp_ids: tuple[str, ...],
    *,
    foundation: bool = False,
) -> str:
    resp_xml = "".join(f'<resp id="{rid}"/>' for rid in resp_ids)
    foundation_marker = "<foundation/>" if foundation else ""
    return (
        f'<component alias="{alias}">'
        f"<name>{name}</name>"
        f"<kind>domain</kind>"
        f"<purpose>{purpose}</purpose>"
        f"<owned-invariants>"
        f"<invariant>{alias} owns state A</invariant>"
        f"<invariant>{alias} owns state B</invariant>"
        f"</owned-invariants>"
        f"<primary-operations>"
        f"<operation>do {alias} thing one</operation>"
        f"<operation>do {alias} thing two</operation>"
        f"<operation>do {alias} thing three</operation>"
        f"</primary-operations>"
        f"<responsibilities>{resp_xml}</responsibilities>"
        f"{foundation_marker}"
        "</component>"
    )


def _valid_sysarch(resp_ids: list[str]) -> str:
    auth_id, billing_id, foundation_id = resp_ids
    return (
        "<sysarch>"
        + _TECHSPEC_STUB
        + "<components>"
        + _comp_xml("auth", "Authentication", "Identify callers.", (auth_id,))
        + _comp_xml("billing", "Billing Service", "Handle payments.", (billing_id,))
        + _comp_xml(
            "foundation",
            "Foundation",
            "Own project root.",
            (foundation_id,),
            foundation=True,
        )
        + "</components>"
        "<policies>"
        "<policy>"
        "<name>LLM Telemetry</name>"
        "<trigger>any LLM call</trigger>"
        f"<required>{foundation_id}</required>"
        "<rationale>Record tokens and model for audit.</rationale>"
        "</policy>"
        "</policies>"
        "<dependencies>"
        '<dep from="billing" to="auth"/>'
        '<dep from="billing" to="foundation"/>'
        '<dep from="auth" to="foundation"/>'
        "</dependencies>"
        "<domain-parent></domain-parent>"
        "</sysarch>"
    )


class TestHappyPath:
    def test_mints_components_fragments_policies_and_edges(self, shared_session_factory):
        factory = shared_session_factory
        s = factory()
        try:
            project_id, resp_ids = _seed_project(s)
            _set_sysarch_content(s, project_id, _valid_sysarch(resp_ids))
        finally:
            s.close()

        asyncio.run(mint_sysarch({"project_id": project_id}))

        s = factory()
        try:
            # ── Components ───────────────────────────────────
            comps = list(
                s.execute(
                    select(Node)
                    .where(
                        Node.project_id == project_id,
                        Node.tier == "comp",
                        Node.parent_id.is_(None),
                    )
                    .order_by(Node.display_order)
                ).scalars()
            )
            assert [c.name for c in comps] == [
                "Authentication",
                "Billing Service",
                "Foundation",
            ]
            assert all(c.id.startswith("comp_") for c in comps)
            # content stays empty — role + api-intent live in
            # fragments, and failure-surface is validate-time only
            # (see sysarch_mint.py NodeCreated for the rationale).
            assert all(c.content == "" for c in comps)

            comp_by_name = {c.name: c for c in comps}
            auth_cid = comp_by_name["Authentication"].id
            billing_cid = comp_by_name["Billing Service"].id
            foundation_cid = comp_by_name["Foundation"].id

            # The <foundation/> marker in the sysarch XML must be
            # persisted on the minted comp node so downstream
            # comparch generation can apply the "foundations don't
            # nest" carve-out without re-parsing the sysarch output.
            assert comp_by_name["Foundation"].is_foundation is True
            assert comp_by_name["Authentication"].is_foundation is False
            assert comp_by_name["Billing Service"].is_foundation is False

            # ── Per-component fragments ──────────────────────
            frags = list(
                s.execute(select(Fragment).where(Fragment.project_id == project_id)).scalars()
            )
            frag_ids = {f.id for f in frags}
            for cid in (auth_cid, billing_cid, foundation_cid):
                assert fragment_id(cid, FragmentKind.TECHSPEC) in frag_ids
                assert fragment_id(cid, FragmentKind.PUBAPI) in frag_ids

            # Content of one specific fragment — techspec = formatted
            # purpose + owned-invariants under the micro-field grammar.
            auth_techspec = s.execute(
                select(Fragment).where(Fragment.id == fragment_id(auth_cid, FragmentKind.TECHSPEC))
            ).scalar_one()
            assert "Identify callers" in auth_techspec.content
            assert "auth owns state A" in auth_techspec.content

            # ── Sysarch techspec fragment ────────────────────
            sysarch_node = s.execute(
                select(Node).where(Node.project_id == project_id, Node.tier == "sysarch")
            ).scalar_one()
            sys_techspec = s.execute(
                select(Fragment).where(
                    Fragment.id == fragment_id(sysarch_node.id, FragmentKind.TECHSPEC)
                )
            ).scalar_one()
            # Structured labeled-block render: each block is a
            # bolded heading + short prose. Check for any of the
            # labels to confirm the render ran.
            assert "Runtime." in sys_techspec.content
            assert "Technologies." in sys_techspec.content

            # ── Policies ─────────────────────────────────────
            policies = list(
                s.execute(
                    select(Node).where(Node.project_id == project_id, Node.tier == "policy")
                ).scalars()
            )
            assert len(policies) == 1
            assert policies[0].name == "LLM Telemetry"
            assert policies[0].id.startswith("policy_")
            # Content is an inline <policy> blob
            assert "<trigger>any LLM call</trigger>" in policies[0].content

            # ── Edges: decomposition + dependency + (no domain-parent) ──
            edges = list(s.execute(select(Edge).where(Edge.project_id == project_id)).scalars())
            decomp_edges = [e for e in edges if e.edge_type == "decomposition"]
            dep_edges = [e for e in edges if e.edge_type == "dependency"]
            dp_edges = [e for e in edges if e.edge_type == "domain_parent"]

            # One decomposition edge per resp assignment (3 total).
            assert len(decomp_edges) == 3
            decomp_pairs = {(e.source_id, e.target_id) for e in decomp_edges}
            assert (resp_ids[0], auth_cid) in decomp_pairs
            assert (resp_ids[1], billing_cid) in decomp_pairs
            assert (resp_ids[2], foundation_cid) in decomp_pairs

            # Three dep edges from the seed data
            assert len(dep_edges) == 3
            dep_pairs = {(e.source_id, e.target_id) for e in dep_edges}
            assert (billing_cid, auth_cid) in dep_pairs
            assert (billing_cid, foundation_cid) in dep_pairs
            assert (auth_cid, foundation_cid) in dep_pairs

            # No domain-parent edges in this fixture
            assert len(dp_edges) == 0
        finally:
            s.close()

    def test_subreqs_bootstrap_fan_out(self, shared_session_factory):
        factory = shared_session_factory
        s = factory()
        try:
            project_id, resp_ids = _seed_project(s)
            _set_sysarch_content(s, project_id, _valid_sysarch(resp_ids))
        finally:
            s.close()

        asyncio.run(mint_sysarch({"project_id": project_id}))

        s = factory()
        try:
            # One subreqs_* per top-level comp (3 total).
            subreqs = list(
                s.execute(
                    select(Node).where(Node.project_id == project_id, Node.tier == "subreqs")
                ).scalars()
            )
            assert len(subreqs) == 3
            assert all(sr.id.startswith("subreqs_") for sr in subreqs)
            # Each parented to a comp_*
            for sr in subreqs:
                assert sr.parent_id is not None
                assert sr.parent_id.startswith("comp_")

            # One v2.generate_subrequirements job per comp.
            jobs = list(
                s.execute(
                    select(Job).where(Job.job_type == "v2.generate_subrequirements")
                ).scalars()
            )
            job_comp_ids = {j.payload.get("component_id") for j in jobs}
            comp_ids = {sr.parent_id for sr in subreqs}
            assert job_comp_ids == comp_ids
        finally:
            s.close()


class TestIdempotency:
    def test_second_run_skips(self, shared_session_factory):
        factory = shared_session_factory
        s = factory()
        try:
            project_id, resp_ids = _seed_project(s)
            _set_sysarch_content(s, project_id, _valid_sysarch(resp_ids))
        finally:
            s.close()

        asyncio.run(mint_sysarch({"project_id": project_id}))
        asyncio.run(mint_sysarch({"project_id": project_id}))

        s = factory()
        try:
            comps = list(
                s.execute(
                    select(Node).where(
                        Node.project_id == project_id,
                        Node.tier == "comp",
                        Node.parent_id.is_(None),
                    )
                ).scalars()
            )
            # Still 3, not 6
            assert len(comps) == 3
            edges = list(
                s.execute(
                    select(Edge).where(
                        Edge.project_id == project_id,
                        Edge.edge_type == "decomposition",
                    )
                ).scalars()
            )
            assert len(edges) == 3  # not 6
        finally:
            s.close()


class TestFailureModes:
    def test_missing_project_id_raises(self, shared_session_factory):
        with pytest.raises(SysarchMintHandlerError, match="project_id"):
            asyncio.run(mint_sysarch({}))

    def test_missing_sysarch_node_raises(self, shared_session_factory):
        factory = shared_session_factory
        s = factory()
        try:
            pid = str(uuid.uuid4())
            s.add(Project(id=pid, name="T2", git_repo_path="/tmp/t2"))
            s.commit()
        finally:
            s.close()
        with pytest.raises(SysarchMintHandlerError, match="no sysarch node"):
            asyncio.run(mint_sysarch({"project_id": pid}))

    def test_empty_content_raises(self, shared_session_factory):
        factory = shared_session_factory
        s = factory()
        try:
            project_id, _ = _seed_project(s)
        finally:
            s.close()
        with pytest.raises(SysarchMintHandlerError, match="empty content"):
            asyncio.run(mint_sysarch({"project_id": project_id}))

    def test_malformed_content_raises(self, shared_session_factory):
        factory = shared_session_factory
        s = factory()
        try:
            project_id, _ = _seed_project(s)
            _set_sysarch_content(s, project_id, "not xml at all")
        finally:
            s.close()
        with pytest.raises(SysarchMintHandlerError, match="could not parse"):
            asyncio.run(mint_sysarch({"project_id": project_id}))
