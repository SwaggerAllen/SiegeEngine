"""Tests for backend.graph.handlers.subcomparch_mint.

Mint handler is deterministic (no LLM call) and idempotent. Each
test seeds a project + approved subcomparch draft content on the
target subcomponent, runs the mint, and asserts the downstream
events: four fragments updated, dep edges emitted for every
``<dep to="comp_..."/>`` entry (targets are always real comp_*
IDs at this tier — no alias indirection).

Also includes a TestComparchMintFanOut class that runs the real
comparch_mint handler end-to-end and asserts it enqueues a
v2.generate_subcomparch job for every minted subcomponent.
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
from backend.graph.handlers.comparch_mint import mint_comparch
from backend.graph.handlers.subcomparch_mint import (
    SubcomparchMintHandlerError,
    mint_subcomparch,
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
    import backend.graph.handlers.comparch_mint as _comparch_mint_mod
    import backend.graph.handlers.subcomparch_mint as _handler_mod

    monkeypatch.setattr(_database_mod, "SessionLocal", factory)
    monkeypatch.setattr(_handler_mod, "SessionLocal", factory)
    monkeypatch.setattr(_comparch_mint_mod, "SessionLocal", factory)
    yield factory
    engine.dispose()


def _seed_top_comp(
    session: Session,
    project_id: str,
    name: str,
    order: int,
    *,
    content: str = "",
) -> str:
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
    return cid


def _seed_sub_comp(
    session: Session,
    project_id: str,
    parent_comp_id: str,
    name: str,
    order: int,
    *,
    content: str = "",
) -> str:
    sub_id = mint(session, Kind.COMP)
    append_event(
        session,
        project_id,
        ev.NodeCreated(
            node_id=sub_id,
            tier="comp",
            kind="domain",
            parent_id=parent_comp_id,
            name=name,
            display_order=order,
            content=content,
        ),
    )
    # Comparch_mint would have seeded these at subcomponent creation
    for kind, body in (
        (FragmentKind.TECHSPEC, f"Skeletal role for {name}"),
        (FragmentKind.PUBAPI, f"Skeletal api for {name}"),
    ):
        append_event(
            session,
            project_id,
            ev.FragmentUpdated(
                fragment_id=fragment_id(sub_id, kind),
                owner_id=sub_id,
                fragment_kind=kind,
                new_content=body,
            ),
        )
    return sub_id


def _set_content(session: Session, node_id: str, content: str) -> None:
    n = session.get(Node, node_id)
    assert n is not None
    n.content = content
    session.commit()


def _sub_doc(*, deps: str = "") -> str:
    return (
        "<subcomparch>"
        "<technical-specification>Real techspec for tokenization.</technical-specification>"
        "<public-surface>tokenize(raw) -> Token.</public-surface>"
        "<private-surface>_rotate_keys(cutoff).</private-surface>"
        f"<dependencies>{deps}</dependencies>"
        "</subcomparch>"
    )


@pytest.fixture()
def seeded(shared_session_factory):
    """Project with one top-level comp (billing), one parent sibling
    (auth), and two subcomponents under billing."""
    factory = shared_session_factory
    s: Session = factory()
    try:
        project_id = str(uuid.uuid4())
        s.add(Project(id=project_id, name="T", git_repo_path="/tmp/t"))
        s.flush()

        comp_billing = _seed_top_comp(s, project_id, "BillingService", 0)
        comp_auth = _seed_top_comp(s, project_id, "AuthService", 1)

        sub_store = _seed_sub_comp(s, project_id, comp_billing, "TokenStore", 0)
        sub_found = _seed_sub_comp(s, project_id, comp_billing, "Foundation", 1)
        s.commit()
        yield {
            "project_id": project_id,
            "comp_billing": comp_billing,
            "comp_auth": comp_auth,
            "sub_store": sub_store,
            "sub_found": sub_found,
        }
    finally:
        s.close()


class TestHappyPath:
    def test_overwrites_fragments_and_emits_dep_edges(self, shared_session_factory, seeded):
        factory = shared_session_factory
        s = factory()
        try:
            _set_content(
                s,
                seeded["sub_store"],
                _sub_doc(deps=f'<dep to="{seeded["sub_found"]}"/>'),
            )
        finally:
            s.close()

        asyncio.run(
            mint_subcomparch(
                {
                    "project_id": seeded["project_id"],
                    "component_id": seeded["sub_store"],
                }
            )
        )

        s = factory()
        try:
            # Four fragments updated
            for kind in (
                FragmentKind.TECHSPEC,
                FragmentKind.PUBAPI,
                FragmentKind.PRIVAPI,
                FragmentKind.DEPS,
            ):
                frag = s.get(Fragment, fragment_id(seeded["sub_store"], kind))
                assert frag is not None, f"missing {kind}"
                assert frag.content
            # techspec overwritten (not skeletal anymore)
            ts = s.get(Fragment, fragment_id(seeded["sub_store"], FragmentKind.TECHSPEC))
            assert ts is not None
            assert "Real techspec" in ts.content
            assert "Skeletal" not in ts.content
            # deps fragment is the serialized XML with the real sibling id
            deps_frag = s.get(Fragment, fragment_id(seeded["sub_store"], FragmentKind.DEPS))
            assert deps_frag is not None
            assert seeded["sub_found"] in deps_frag.content

            # One dep edge from sub_store to sub_found
            edges = list(
                s.execute(
                    select(Edge).where(
                        Edge.project_id == seeded["project_id"],
                        Edge.edge_type == "dependency",
                        Edge.source_id == seeded["sub_store"],
                    )
                ).scalars()
            )
            assert len(edges) == 1
            assert edges[0].target_id == seeded["sub_found"]
        finally:
            s.close()

    def test_parent_sibling_dep_emitted(self, shared_session_factory, seeded):
        """A <dep to="comp_X"/> pointing at a parent sibling emits
        a dep edge with the parent's sibling as the target."""
        factory = shared_session_factory
        s = factory()
        try:
            _set_content(
                s,
                seeded["sub_store"],
                _sub_doc(deps=f'<dep to="{seeded["comp_auth"]}"/>'),
            )
        finally:
            s.close()

        asyncio.run(
            mint_subcomparch(
                {
                    "project_id": seeded["project_id"],
                    "component_id": seeded["sub_store"],
                }
            )
        )

        s = factory()
        try:
            edges = list(
                s.execute(
                    select(Edge).where(
                        Edge.project_id == seeded["project_id"],
                        Edge.edge_type == "dependency",
                        Edge.source_id == seeded["sub_store"],
                    )
                ).scalars()
            )
            assert len(edges) == 1
            assert edges[0].target_id == seeded["comp_auth"]
        finally:
            s.close()

    def test_mixed_deps(self, shared_session_factory, seeded):
        factory = shared_session_factory
        s = factory()
        try:
            _set_content(
                s,
                seeded["sub_store"],
                _sub_doc(
                    deps=(f'<dep to="{seeded["sub_found"]}"/><dep to="{seeded["comp_auth"]}"/>')
                ),
            )
        finally:
            s.close()

        asyncio.run(
            mint_subcomparch(
                {
                    "project_id": seeded["project_id"],
                    "component_id": seeded["sub_store"],
                }
            )
        )

        s = factory()
        try:
            edges = list(
                s.execute(
                    select(Edge).where(
                        Edge.project_id == seeded["project_id"],
                        Edge.edge_type == "dependency",
                        Edge.source_id == seeded["sub_store"],
                    )
                ).scalars()
            )
            assert len(edges) == 2
            targets = {e.target_id for e in edges}
            assert seeded["sub_found"] in targets  # same-parent sibling
            assert seeded["comp_auth"] in targets  # parent's sibling
        finally:
            s.close()

    def test_leaf_no_deps(self, shared_session_factory, seeded):
        """Empty <dependencies> → fragments emitted, no edges."""
        factory = shared_session_factory
        s = factory()
        try:
            _set_content(s, seeded["sub_found"], _sub_doc())
        finally:
            s.close()

        asyncio.run(
            mint_subcomparch(
                {
                    "project_id": seeded["project_id"],
                    "component_id": seeded["sub_found"],
                }
            )
        )

        s = factory()
        try:
            edges = list(
                s.execute(
                    select(Edge).where(
                        Edge.project_id == seeded["project_id"],
                        Edge.edge_type == "dependency",
                        Edge.source_id == seeded["sub_found"],
                    )
                ).scalars()
            )
            assert edges == []
            deps_frag = s.get(Fragment, fragment_id(seeded["sub_found"], FragmentKind.DEPS))
            assert deps_frag is not None
            assert deps_frag.content == "<dependencies></dependencies>"
        finally:
            s.close()


class TestIdempotency:
    def test_second_run_skips(self, shared_session_factory, seeded):
        factory = shared_session_factory
        s = factory()
        try:
            _set_content(
                s,
                seeded["sub_store"],
                _sub_doc(deps=f'<dep to="{seeded["sub_found"]}"/>'),
            )
        finally:
            s.close()

        asyncio.run(
            mint_subcomparch(
                {
                    "project_id": seeded["project_id"],
                    "component_id": seeded["sub_store"],
                }
            )
        )
        asyncio.run(
            mint_subcomparch(
                {
                    "project_id": seeded["project_id"],
                    "component_id": seeded["sub_store"],
                }
            )
        )

        s = factory()
        try:
            edges = list(
                s.execute(
                    select(Edge).where(
                        Edge.project_id == seeded["project_id"],
                        Edge.edge_type == "dependency",
                        Edge.source_id == seeded["sub_store"],
                    )
                ).scalars()
            )
            assert len(edges) == 1  # not 2
        finally:
            s.close()


class TestFailureModes:
    def test_missing_project_id_raises(self, shared_session_factory):
        with pytest.raises(SubcomparchMintHandlerError, match="project_id"):
            asyncio.run(mint_subcomparch({}))

    def test_missing_component_id_raises(self, shared_session_factory):
        with pytest.raises(SubcomparchMintHandlerError, match="component_id"):
            asyncio.run(mint_subcomparch({"project_id": "p"}))

    def test_empty_content_raises(self, shared_session_factory, seeded):
        with pytest.raises(SubcomparchMintHandlerError, match="empty content"):
            asyncio.run(
                mint_subcomparch(
                    {
                        "project_id": seeded["project_id"],
                        "component_id": seeded["sub_store"],
                    }
                )
            )

    def test_top_level_comp_rejected(self, shared_session_factory, seeded):
        s = shared_session_factory()
        try:
            _set_content(s, seeded["comp_billing"], _sub_doc())
        finally:
            s.close()
        with pytest.raises(SubcomparchMintHandlerError, match="top-level component"):
            asyncio.run(
                mint_subcomparch(
                    {
                        "project_id": seeded["project_id"],
                        "component_id": seeded["comp_billing"],
                    }
                )
            )

    def test_malformed_content_raises(self, shared_session_factory, seeded):
        s = shared_session_factory()
        try:
            _set_content(s, seeded["sub_store"], "<not-subcomparch/>")
        finally:
            s.close()
        with pytest.raises(SubcomparchMintHandlerError, match="could not parse"):
            asyncio.run(
                mint_subcomparch(
                    {
                        "project_id": seeded["project_id"],
                        "component_id": seeded["sub_store"],
                    }
                )
            )


class TestComparchMintFanOut:
    """Integration: comparch_mint should enqueue
    v2.generate_subcomparch for each minted sub post-commit."""

    def test_fans_out_per_minted_sub(self, shared_session_factory):
        factory = shared_session_factory
        s: Session = factory()
        try:
            project_id = str(uuid.uuid4())
            s.add(Project(id=project_id, name="T", git_repo_path="/tmp/t"))
            s.flush()

            # Two top-level resps + one sibling comp (auth) that
            # billing can depend on.
            resp_bill = mint(s, Kind.RESP)
            append_event(
                s,
                project_id,
                ev.NodeCreated(
                    node_id=resp_bill,
                    tier="resp",
                    kind="domain",
                    parent_id=None,
                    name="Billing",
                    display_order=0,
                    content="Billing.",
                ),
            )
            resp_auth = mint(s, Kind.RESP)
            append_event(
                s,
                project_id,
                ev.NodeCreated(
                    node_id=resp_auth,
                    tier="resp",
                    kind="domain",
                    parent_id=None,
                    name="Auth",
                    display_order=1,
                    content="Auth.",
                ),
            )

            comp_billing = mint(s, Kind.COMP)
            append_event(
                s,
                project_id,
                ev.NodeCreated(
                    node_id=comp_billing,
                    tier="comp",
                    kind="domain",
                    parent_id=None,
                    name="BillingService",
                    display_order=0,
                    content="",
                ),
            )
            # resp -> comp decomposition
            edge_id = mint(s, Kind.EDGE)
            append_event(
                s,
                project_id,
                ev.EdgeCreated(
                    edge_id=edge_id,
                    edge_type="decomposition",
                    source_id=resp_bill,
                    target_id=comp_billing,
                ),
            )
            comp_auth = mint(s, Kind.COMP)
            append_event(
                s,
                project_id,
                ev.NodeCreated(
                    node_id=comp_auth,
                    tier="comp",
                    kind="domain",
                    parent_id=None,
                    name="AuthService",
                    display_order=1,
                    content="<comparch>approved</comparch>",
                ),
            )
            edge_id = mint(s, Kind.EDGE)
            append_event(
                s,
                project_id,
                ev.EdgeCreated(
                    edge_id=edge_id,
                    edge_type="decomposition",
                    source_id=resp_auth,
                    target_id=comp_auth,
                ),
            )

            # Subresps under billing
            sub_token = mint(s, Kind.RESP)
            append_event(
                s,
                project_id,
                ev.NodeCreated(
                    node_id=sub_token,
                    tier="resp",
                    kind="domain",
                    parent_id=comp_billing,
                    name="Tokenization",
                    display_order=0,
                    content="Tokenization intent.",
                ),
            )
            sub_retry = mint(s, Kind.RESP)
            append_event(
                s,
                project_id,
                ev.NodeCreated(
                    node_id=sub_retry,
                    tier="resp",
                    kind="domain",
                    parent_id=comp_billing,
                    name="RetryScheduling",
                    display_order=1,
                    content="Retry intent.",
                ),
            )

            # Write approved comparch content on billing
            billing_doc = (
                "<comparch>"
                "<technical-specification>Python.</technical-specification>"
                "<public-surface>get_billing_state().</public-surface>"
                "<private-surface>helpers.</private-surface>"
                "<policies></policies>"
                f'<dependencies><dep to="{comp_auth}"/></dependencies>'
                "<subcomponents>"
                '<subcomponent alias="token_store">'
                "<name>TokenStore</name>"
                "<role>Owns tokenization.</role>"
                "<api-intent>tokenize(raw).</api-intent>"
                f'<responsibilities><resp id="{sub_token}"/></responsibilities>'
                "</subcomponent>"
                '<subcomponent alias="foundation">'
                "<name>Foundation</name>"
                "<role>Component root + retry.</role>"
                "<api-intent>init(); schedule_retry(ctx).</api-intent>"
                f'<responsibilities><resp id="{sub_retry}"/></responsibilities>'
                "<foundation/>"
                "</subcomponent>"
                "</subcomponents>"
                "<sub-dependencies>"
                '<dep from="token_store" to="foundation"/>'
                "</sub-dependencies>"
                "</comparch>"
            )
            node = s.get(Node, comp_billing)
            assert node is not None
            node.content = billing_doc
            s.commit()
        finally:
            s.close()

        asyncio.run(
            mint_comparch(
                {
                    "project_id": project_id,
                    "component_id": comp_billing,
                }
            )
        )

        s = factory()
        try:
            # Two subs were minted; two generate_subcomparch jobs
            # should have been enqueued.
            jobs = list(
                s.execute(select(Job).where(Job.job_type == "v2.generate_subcomparch")).scalars()
            )
            assert len(jobs) == 2
            subs = list(
                s.execute(
                    select(Node).where(
                        Node.project_id == project_id,
                        Node.tier == "comp",
                        Node.parent_id == comp_billing,
                    )
                ).scalars()
            )
            enqueued_ids = {j.payload["component_id"] for j in jobs}
            assert enqueued_ids == {sub.id for sub in subs}
            for job in jobs:
                assert job.payload["project_id"] == project_id
                assert job.payload["feedback"] is None
        finally:
            s.close()
