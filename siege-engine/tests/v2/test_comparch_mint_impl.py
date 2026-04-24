"""Tests for Phase 8 impl fan-out inside comparch_mint.

Verifies the "mint one impl shell per subcomponent / per
un-fanned-out top-level" behavior. Calls ``mint_comparch``
directly with pre-seeded arch doc content; the handler's
existing fan-out + fan-in around impls is what we're checking.
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
from backend.graph.handlers.comparch_mint import mint_comparch
from backend.graph.ids import Kind, mint
from backend.graph.reducer import append_event
from backend.models import Project
from backend.models.node import Node


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


def _sub_xml(
    alias: str,
    name: str,
    resp_ids: tuple[str, ...],
    *,
    foundation: bool = False,
) -> str:
    """Render a ``<subcomponent>`` in the micro-field grammar."""
    resp_xml = "".join(f'<resp id="{rid}"/>' for rid in resp_ids)
    foundation_marker = "<foundation/>" if foundation else ""
    return (
        f'<subcomponent alias="{alias}">'
        f"<name>{name}</name>"
        f"<purpose>Owns {name} territory.</purpose>"
        f"<owned-invariants>"
        f"<invariant>{name} holds state</invariant>"
        f"<invariant>{name} is journaled</invariant>"
        f"</owned-invariants>"
        f"<primary-operations>"
        f"<operation>read {name}</operation>"
        f"<operation>mutate {name}</operation>"
        f"<operation>emit {name}</operation>"
        f"</primary-operations>"
        f"<responsibilities>{resp_xml}</responsibilities>"
        f"{foundation_marker}"
        "</subcomponent>"
    )


def _fanned_out_comparch() -> str:
    """Minimal valid comparch that mints two subcomponents + no external deps."""
    return (
        "<comparch>"
        "<technical-specification>Python.</technical-specification>"
        "<public-surface>Exports foo().</public-surface>"
        "<private-surface>_bar()</private-surface>"
        "<failure-surface>foo bug corrupts owned state.</failure-surface>"
        "<policies></policies>"
        "<dependencies></dependencies>"
        "<subcomponents>"
        + _sub_xml("a", "SubA", ("{resp_a}",))
        + _sub_xml("b", "SubB", ("{resp_b}",), foundation=True)
        + "</subcomponents>"
        # 'b' is the foundation; non-foundation subs must declare
        # a dep to the foundation per the arch-doc validator.
        '<sub-dependencies><dep from="a" to="b"/></sub-dependencies>'
        "</comparch>"
    )


def _un_fanned_out_comparch() -> str:
    return (
        "<comparch>"
        "<technical-specification>Python.</technical-specification>"
        "<public-surface>Exports foo().</public-surface>"
        "<private-surface>_bar()</private-surface>"
        "<failure-surface>foo bug corrupts owned state.</failure-surface>"
        "<policies></policies>"
        "<dependencies></dependencies>"
        "<subcomponents></subcomponents>"
        "<sub-dependencies></sub-dependencies>"
        "</comparch>"
    )


def _seed_project_with_comp(
    factory, comparch_content: str, *, num_subresps: int = 2
) -> tuple[str, str]:
    """Seed project + top-level comp + subresps (if any).

    For the fanned-out case, seed 2 subresps and format the
    comparch to assign them to subcomponents. For the
    un-fanned-out case, seed 0 subresps and use a template with
    no placeholders — a comp with no subresps plus an empty
    ``<subcomponents>`` block is the valid un-fanned-out shape.
    """
    session: Session = factory()
    try:
        project_id = str(uuid.uuid4())
        session.add(Project(id=project_id, name="T", git_repo_path="/tmp/t"))
        session.flush()
        comp_id = mint(session, Kind.COMP)
        append_event(
            session,
            project_id,
            ev.NodeCreated(
                node_id=comp_id,
                tier="comp",
                kind="domain",
                parent_id=None,
                name="TopComp",
            ),
        )
        resp_ids: list[str] = []
        for i in range(num_subresps):
            resp_id = mint(session, Kind.RESP)
            append_event(
                session,
                project_id,
                ev.NodeCreated(
                    node_id=resp_id,
                    tier="resp",
                    kind="domain",
                    parent_id=comp_id,
                    name=f"Subresp{i}",
                    content=f"Intent {i}",
                ),
            )
            resp_ids.append(resp_id)
        # Substitute placeholders if the template has any; no-op
        # otherwise (un-fanned-out case).
        if num_subresps >= 2:
            filled = comparch_content.format(resp_a=resp_ids[0], resp_b=resp_ids[1])
        else:
            filled = comparch_content
        append_event(
            session,
            project_id,
            ev.DraftGenerated(
                draft_id="d_comparch",
                target_type="node",
                target_id=comp_id,
                content=filled,
                batch_id="b1",
            ),
        )
        append_event(session, project_id, ev.DraftApproved(draft_id="d_comparch"))
        session.commit()
        return project_id, comp_id
    finally:
        session.close()


class TestFannedOutCase:
    def test_mints_one_impl_per_subcomponent(self, shared_session_factory):
        project_id, comp_id = _seed_project_with_comp(
            shared_session_factory, _fanned_out_comparch()
        )
        asyncio.run(mint_comparch({"project_id": project_id, "component_id": comp_id}))

        session = shared_session_factory()
        try:
            subs = list(
                session.execute(
                    select(Node).where(
                        Node.project_id == project_id,
                        Node.tier == "comp",
                        Node.parent_id == comp_id,
                    )
                ).scalars()
            )
            assert len(subs) == 2
            for sub in subs:
                impl = session.execute(
                    select(Node).where(
                        Node.project_id == project_id,
                        Node.tier == "impl",
                        Node.parent_id == sub.id,
                    )
                ).scalar_one_or_none()
                assert impl is not None, f"sub {sub.id} has no impl shell"
                assert impl.content == ""
                assert impl.name == f"{sub.name} impl"

            # No impl under the fanned-out top-level comp itself.
            top_impl = session.execute(
                select(Node).where(
                    Node.project_id == project_id,
                    Node.tier == "impl",
                    Node.parent_id == comp_id,
                )
            ).scalar_one_or_none()
            assert top_impl is None
        finally:
            session.close()


class TestUnFannedOutCase:
    def test_mints_single_impl_under_top_level(self, shared_session_factory):
        project_id, comp_id = _seed_project_with_comp(
            shared_session_factory, _un_fanned_out_comparch(), num_subresps=0
        )
        asyncio.run(mint_comparch({"project_id": project_id, "component_id": comp_id}))

        session = shared_session_factory()
        try:
            impls = list(
                session.execute(
                    select(Node).where(
                        Node.project_id == project_id,
                        Node.tier == "impl",
                    )
                ).scalars()
            )
            assert len(impls) == 1
            assert impls[0].parent_id == comp_id
            assert impls[0].content == ""

            # No subcomponents.
            subs = list(
                session.execute(
                    select(Node).where(
                        Node.project_id == project_id,
                        Node.tier == "comp",
                        Node.parent_id == comp_id,
                    )
                ).scalars()
            )
            assert subs == []
        finally:
            session.close()
