"""Tests for backend.graph.handlers.comparch_mint.

Mint handler is deterministic (no LLM call) and idempotent.
Each test seeds a project + approved comparch draft content on
the target comp_* node, runs the mint, and asserts the full
set of downstream events landed correctly: fragments, sub
mints, policy mints, external deps, sub deps, decomposition
edges, and the post-commit policy-application fan-out.
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
from backend.graph.handlers.comparch_mint import (
    ComparchMintHandlerError,
    mint_comparch,
)
from backend.graph.ids import Kind, mint
from backend.graph.reducer import append_event
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
    import backend.graph.handlers.comparch_mint as _handler_mod

    monkeypatch.setattr(_database_mod, "SessionLocal", factory)
    monkeypatch.setattr(_handler_mod, "SessionLocal", factory)
    yield factory
    engine.dispose()


def _seed_top_resp(session, project_id, name, order):
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


def _seed_comp(session, project_id, name, order, parent_resp_ids, *, content=""):
    cid = mint(session, Kind.COMP)
    append_event(
        session,
        project_id,
        ev.NodeCreated(
            node_id=cid,
            tier="comp",
            kind="domain",
            parent_id=None,
            name=name,
            display_order=order,
            content=content,
        ),
    )
    for rid in parent_resp_ids:
        eid = mint(session, Kind.EDGE)
        append_event(
            session,
            project_id,
            ev.EdgeCreated(
                edge_id=eid,
                edge_type="decomposition",
                source_id=rid,
                target_id=cid,
            ),
        )
    return cid


def _seed_subresp(session, project_id, parent_comp, name, order):
    sid = mint(session, Kind.RESP)
    append_event(
        session,
        project_id,
        ev.NodeCreated(
            node_id=sid,
            tier="resp",
            kind="domain",
            parent_id=parent_comp,
            name=name,
            display_order=order,
            content=f"{name} intent.",
        ),
    )
    return sid


def _set_comp_content(session, comp_id, content):
    node = session.get(Node, comp_id)
    assert node is not None
    node.content = content
    session.commit()


def _arch_doc(
    *,
    sub_token_id: str,
    sub_retry_id: str,
    sibling_comp_id: str,
    with_policy: bool = False,
) -> str:
    policy_block = ""
    if with_policy:
        policy_block = (
            "<policy>"
            "<name>Telemetry</name>"
            "<trigger>any LLM call</trigger>"
            f"<required>{sub_token_id}</required>"
            "<rationale>Record token refreshes for audit.</rationale>"
            "</policy>"
        )
    return (
        "<comparch>"
        "<technical-specification>Python + PostgreSQL.</technical-specification>"
        "<public-surface>get_billing_state(id).</public-surface>"
        "<private-surface>Internal helpers.</private-surface>"
        f"<policies>{policy_block}</policies>"
        f'<dependencies><dep to="{sibling_comp_id}"/></dependencies>'
        "<subcomponents>"
        '<subcomponent alias="token_store">'
        "<name>TokenStore</name>"
        "<role>Owns tokenization.</role>"
        "<api-intent>tokenize(raw).</api-intent>"
        f'<responsibilities><resp id="{sub_token_id}"/></responsibilities>'
        "</subcomponent>"
        '<subcomponent alias="foundation">'
        "<name>Foundation</name>"
        "<role>Component root + retry.</role>"
        "<api-intent>init(); schedule_retry(ctx).</api-intent>"
        f'<responsibilities><resp id="{sub_retry_id}"/></responsibilities>'
        "<foundation/>"
        "</subcomponent>"
        "</subcomponents>"
        "<sub-dependencies>"
        '<dep from="token_store" to="foundation"/>'
        "</sub-dependencies>"
        "</comparch>"
    )


@pytest.fixture()
def seeded(shared_session_factory):
    factory = shared_session_factory
    s: Session = factory()
    try:
        project_id = str(uuid.uuid4())
        s.add(Project(id=project_id, name="T", git_repo_path="/tmp/t"))
        s.flush()

        resp_bill = _seed_top_resp(s, project_id, "Billing", 0)
        resp_auth = _seed_top_resp(s, project_id, "Auth", 1)

        comp_billing = _seed_comp(s, project_id, "BillingService", 0, [resp_bill])
        comp_auth = _seed_comp(s, project_id, "AuthService", 1, [resp_auth])

        sub_token = _seed_subresp(s, project_id, comp_billing, "Tokenization", 0)
        sub_retry = _seed_subresp(s, project_id, comp_billing, "RetryScheduling", 1)

        s.commit()
        yield {
            "project_id": project_id,
            "comp_billing": comp_billing,
            "comp_auth": comp_auth,
            "sub_token": sub_token,
            "sub_retry": sub_retry,
        }
    finally:
        s.close()


class TestHappyPath:
    def test_mints_subcomponents_fragments_deps(self, shared_session_factory, seeded):
        factory = shared_session_factory
        s = factory()
        try:
            _set_comp_content(
                s,
                seeded["comp_billing"],
                _arch_doc(
                    sub_token_id=seeded["sub_token"],
                    sub_retry_id=seeded["sub_retry"],
                    sibling_comp_id=seeded["comp_auth"],
                ),
            )
        finally:
            s.close()

        asyncio.run(
            mint_comparch(
                {
                    "project_id": seeded["project_id"],
                    "component_id": seeded["comp_billing"],
                }
            )
        )

        s = factory()
        try:
            # Subcomponents exist under billing
            subs = list(
                s.execute(
                    select(Node)
                    .where(
                        Node.project_id == seeded["project_id"],
                        Node.tier == "comp",
                        Node.parent_id == seeded["comp_billing"],
                    )
                    .order_by(Node.display_order)
                ).scalars()
            )
            assert [sub.name for sub in subs] == ["TokenStore", "Foundation"]
            assert all(sub.kind == "domain" for sub in subs)
            # The <foundation/> marker in the comparch XML must
            # be persisted on the minted subcomponent node, same
            # as sysarch_mint does at the top tier. Phase 5's
            # subcomparch pass reads this flag to apply the
            # "foundations don't nest" carve-out if it ever runs
            # on a foundation subcomponent.
            sub_by_name = {sub.name: sub for sub in subs}
            assert sub_by_name["Foundation"].is_foundation is True
            assert sub_by_name["TokenStore"].is_foundation is False

            # Each sub has techspec + pubapi fragments with skeletal content
            for sub in subs:
                ts = s.get(Fragment, fragment_id(sub.id, FragmentKind.TECHSPEC))
                pa = s.get(Fragment, fragment_id(sub.id, FragmentKind.PUBAPI))
                assert ts is not None
                assert pa is not None
                assert ts.content  # non-empty
                assert pa.content

            # Billing itself got 5 updated fragments
            billing_id = seeded["comp_billing"]
            for kind in (
                FragmentKind.TECHSPEC,
                FragmentKind.PUBAPI,
                FragmentKind.PRIVAPI,
                FragmentKind.POLICIES,
                FragmentKind.DEPS,
            ):
                frag = s.get(Fragment, fragment_id(billing_id, kind))
                assert frag is not None, f"missing {kind}"
                assert frag.content

            # External dep edge billing → auth
            dep_edges = list(
                s.execute(
                    select(Edge).where(
                        Edge.project_id == seeded["project_id"],
                        Edge.edge_type == "dependency",
                        Edge.source_id == billing_id,
                    )
                ).scalars()
            )
            assert len(dep_edges) == 1
            assert dep_edges[0].target_id == seeded["comp_auth"]

            # Sub-dep edge token_store → foundation (real IDs)
            sub_by_name = {sub.name: sub for sub in subs}
            sub_dep_edges = list(
                s.execute(
                    select(Edge).where(
                        Edge.project_id == seeded["project_id"],
                        Edge.edge_type == "dependency",
                        Edge.source_id == sub_by_name["TokenStore"].id,
                    )
                ).scalars()
            )
            assert len(sub_dep_edges) == 1
            assert sub_dep_edges[0].target_id == sub_by_name["Foundation"].id

            # Decomposition edges: subresp → sub
            decomp_edges = list(
                s.execute(
                    select(Edge).where(
                        Edge.project_id == seeded["project_id"],
                        Edge.edge_type == "decomposition",
                        Edge.target_id.in_([s.id for s in subs]),
                    )
                ).scalars()
            )
            pairs = {(e.source_id, e.target_id) for e in decomp_edges}
            assert (seeded["sub_token"], sub_by_name["TokenStore"].id) in pairs
            assert (seeded["sub_retry"], sub_by_name["Foundation"].id) in pairs
        finally:
            s.close()

    def test_mints_component_local_policy(self, shared_session_factory, seeded):
        factory = shared_session_factory
        s = factory()
        try:
            _set_comp_content(
                s,
                seeded["comp_billing"],
                _arch_doc(
                    sub_token_id=seeded["sub_token"],
                    sub_retry_id=seeded["sub_retry"],
                    sibling_comp_id=seeded["comp_auth"],
                    with_policy=True,
                ),
            )
        finally:
            s.close()

        asyncio.run(
            mint_comparch(
                {
                    "project_id": seeded["project_id"],
                    "component_id": seeded["comp_billing"],
                }
            )
        )

        s = factory()
        try:
            policies = list(
                s.execute(
                    select(Node).where(
                        Node.project_id == seeded["project_id"],
                        Node.tier == "policy",
                        Node.parent_id == seeded["comp_billing"],
                    )
                ).scalars()
            )
            assert len(policies) == 1
            assert policies[0].name == "Telemetry"
            assert "<trigger>any LLM call</trigger>" in policies[0].content
        finally:
            s.close()

    def test_enqueues_policy_application_fan_out(self, shared_session_factory, seeded):
        factory = shared_session_factory
        s = factory()
        try:
            _set_comp_content(
                s,
                seeded["comp_billing"],
                _arch_doc(
                    sub_token_id=seeded["sub_token"],
                    sub_retry_id=seeded["sub_retry"],
                    sibling_comp_id=seeded["comp_auth"],
                ),
            )
        finally:
            s.close()

        asyncio.run(
            mint_comparch(
                {
                    "project_id": seeded["project_id"],
                    "component_id": seeded["comp_billing"],
                }
            )
        )

        s = factory()
        try:
            jobs = list(
                s.execute(
                    select(Job).where(
                        Job.job_type.in_(
                            [
                                "v2.apply_top_level_policies",
                                "v2.apply_component_local_policies",
                            ]
                        )
                    )
                ).scalars()
            )
            job_types = {j.job_type for j in jobs}
            assert job_types == {
                "v2.apply_top_level_policies",
                "v2.apply_component_local_policies",
            }
            for job in jobs:
                assert job.payload["project_id"] == seeded["project_id"]
                assert job.payload["component_id"] == seeded["comp_billing"]
        finally:
            s.close()


class TestIdempotency:
    def test_second_run_skips(self, shared_session_factory, seeded):
        factory = shared_session_factory
        s = factory()
        try:
            _set_comp_content(
                s,
                seeded["comp_billing"],
                _arch_doc(
                    sub_token_id=seeded["sub_token"],
                    sub_retry_id=seeded["sub_retry"],
                    sibling_comp_id=seeded["comp_auth"],
                ),
            )
        finally:
            s.close()

        asyncio.run(
            mint_comparch(
                {
                    "project_id": seeded["project_id"],
                    "component_id": seeded["comp_billing"],
                }
            )
        )
        asyncio.run(
            mint_comparch(
                {
                    "project_id": seeded["project_id"],
                    "component_id": seeded["comp_billing"],
                }
            )
        )

        s = factory()
        try:
            subs = list(
                s.execute(
                    select(Node).where(
                        Node.project_id == seeded["project_id"],
                        Node.tier == "comp",
                        Node.parent_id == seeded["comp_billing"],
                    )
                ).scalars()
            )
            assert len(subs) == 2  # not 4
        finally:
            s.close()


class TestFailureModes:
    def test_missing_project_id_raises(self, shared_session_factory):
        with pytest.raises(ComparchMintHandlerError, match="project_id"):
            asyncio.run(mint_comparch({}))

    def test_missing_component_id_raises(self, shared_session_factory):
        with pytest.raises(ComparchMintHandlerError, match="component_id"):
            asyncio.run(mint_comparch({"project_id": "p"}))

    def test_empty_content_raises(self, shared_session_factory, seeded):
        with pytest.raises(ComparchMintHandlerError, match="empty content"):
            asyncio.run(
                mint_comparch(
                    {
                        "project_id": seeded["project_id"],
                        "component_id": seeded["comp_billing"],
                    }
                )
            )

    def test_malformed_content_raises(self, shared_session_factory, seeded):
        s = shared_session_factory()
        try:
            _set_comp_content(s, seeded["comp_billing"], "not xml")
        finally:
            s.close()

        with pytest.raises(ComparchMintHandlerError, match="could not parse"):
            asyncio.run(
                mint_comparch(
                    {
                        "project_id": seeded["project_id"],
                        "component_id": seeded["comp_billing"],
                    }
                )
            )


class TestSubreqsMintFanOut:
    """The subreqs mint handler was extended in stage 4 to enqueue
    v2.generate_comparch after committing. Verify that fan-out
    fires from the real subreqs_mint handler."""

    def test_subreqs_mint_enqueues_comparch_generation(self, shared_session_factory):
        from backend.graph.handlers.subreqs_mint import mint_subreqs
        from backend.graph.subrequirements import bootstrap_subreqs_node

        factory = shared_session_factory

        # Need to monkeypatch SessionLocal for the subreqs_mint handler
        import backend.graph.handlers.subreqs_mint as _sr_handler

        s = factory()
        try:
            project_id = str(uuid.uuid4())
            s.add(Project(id=project_id, name="T2", git_repo_path="/tmp/t2"))
            s.flush()
            resp = _seed_top_resp(s, project_id, "Billing", 0)
            comp = _seed_comp(s, project_id, "BillingService", 0, [resp])
            bootstrap_subreqs_node(s, project_id, comp)

            # Simulate approved content
            subreqs_node = s.execute(
                select(Node).where(
                    Node.project_id == project_id,
                    Node.tier == "subreqs",
                    Node.parent_id == comp,
                )
            ).scalar_one()
            subreqs_node.content = (
                "<subrequirements>"
                "<subresponsibility>"
                "<name>Tokenize</name>"
                "<intent>Tokenize cards.</intent>"
                f'<derived-from><resp id="{resp}"/></derived-from>'
                "</subresponsibility>"
                "</subrequirements>"
            )
            s.commit()
        finally:
            s.close()

        # Monkeypatch SessionLocal in subreqs_mint too
        orig_session_local = _sr_handler.SessionLocal
        _sr_handler.SessionLocal = factory
        try:
            asyncio.run(mint_subreqs({"project_id": project_id, "component_id": comp}))
        finally:
            _sr_handler.SessionLocal = orig_session_local

        s = factory()
        try:
            jobs = list(
                s.execute(select(Job).where(Job.job_type == "v2.generate_comparch")).scalars()
            )
            assert any(j.payload.get("component_id") == comp for j in jobs)
        finally:
            s.close()
