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
    owns: list[tuple[str, list[str]]],
    *,
    foundation: bool = False,
) -> str:
    """Render a ``<subcomponent>`` in the micro-field grammar.

    ``owns`` is a list of ``(resp_id, [feat_ids])`` pairs; pass an
    empty list for the legal self-closing ``<owns/>`` form.
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
        f"<responsibilities>{name} prose describing what this subcomp does.</responsibilities>"
        f"{owns_xml}"
        f"{foundation_marker}"
        "</subcomponent>"
    )


def _fanned_out_comparch() -> str:
    """Minimal valid comparch with two subcomponents + no external deps.

    SubA claims the parent resp + its feat slice; SubB is the
    foundation with empty ``<owns/>``. The placeholders
    ``{resp_a}`` / ``{feat_a}`` are filled in at seed time with
    real ids.
    """
    return (
        "<comparch>"
        "<technical-specification>Python.</technical-specification>"
        "<public-surface>Exports foo().</public-surface>"
        "<private-surface>_bar()</private-surface>"
        "<failure-surface>foo bug corrupts owned state.</failure-surface>"
        "<policies></policies>"
        "<dependencies></dependencies>"
        "<subcomponents>"
        + _sub_xml("a", "SubA", [("{resp_a}", ["{feat_a}"])])
        + _sub_xml("b", "SubB", [], foundation=True)
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
    factory, comparch_content: str, *, fanned_out: bool = True
) -> tuple[str, str]:
    """Seed project + top-level comp + (optional) parent resp + feat.

    For the fanned-out case, seed one parent resp with one feat
    tagged on it, wire ``feat → resp`` and ``resp → comp``
    decomposition edges, and format the comparch template with
    those ids. For the un-fanned-out case, seed nothing extra —
    a comp with no parent resps + an empty ``<subcomponents>``
    block is the legal degenerate shape.
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
        if fanned_out:
            resp_id = mint(session, Kind.RESP)
            append_event(
                session,
                project_id,
                ev.NodeCreated(
                    node_id=resp_id,
                    tier="resp",
                    kind="domain",
                    parent_id=None,
                    name="ParentResp",
                    content="Intent",
                ),
            )
            feat_id = mint(session, Kind.FEAT)
            append_event(
                session,
                project_id,
                ev.NodeCreated(
                    node_id=feat_id,
                    tier="feat",
                    kind="domain",
                    parent_id=None,
                    name="ParentFeat",
                    content="Feat.",
                ),
            )
            # resp → comp + feat → resp decomposition edges; the
            # comparch validator reads these to build the parent-
            # resp allow-set and per-resp feat slice.
            for src, tgt in ((resp_id, comp_id), (feat_id, resp_id)):
                edge_id = mint(session, Kind.EDGE)
                append_event(
                    session,
                    project_id,
                    ev.EdgeCreated(
                        edge_id=edge_id,
                        edge_type="decomposition",
                        source_id=src,
                        target_id=tgt,
                    ),
                )
            filled = comparch_content.format(resp_a=resp_id, feat_a=feat_id)
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
            shared_session_factory, _un_fanned_out_comparch(), fanned_out=False
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
