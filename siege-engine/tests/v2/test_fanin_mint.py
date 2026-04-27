"""Tests for Phase 7 fan-in shell minting inside comparch_mint.

Verifies:
- A fanned-out domain comp mints one fan-in shell under itself.
- An un-fanned-out domain comp mints NO fan-in shell.
- A fanned-out presentational comp mints NO fan-in shell.
- Re-running mint_comparch does not re-mint a fan-in shell.
- Mint alone does NOT enqueue generate_fanin — that trigger
  lives on the impl-approval hook (covered in
  test_impl_approval_fanin_enqueue).
- Shell shape: tier="fanin", kind="domain", parent_id=comp_id,
  content="".
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
from backend.models.job import Job
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
    import backend.pipeline.queue as _queue_mod

    monkeypatch.setattr(_database_mod, "SessionLocal", factory)
    monkeypatch.setattr(_handler_mod, "SessionLocal", factory)
    monkeypatch.setattr(_queue_mod, "SessionLocal", factory)
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

    ``owns`` is a list of ``(resp_id, [feat_ids])`` pairs; an empty
    list yields the legal self-closing ``<owns/>`` form.
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
    factory,
    comparch_content: str,
    *,
    fanned_out: bool = True,
    comp_kind: str = "domain",
) -> tuple[str, str]:
    """Seed project + top-level comp + (optional) one parent resp + feat.

    Wires ``feat → resp`` and ``resp → comp`` decomposition edges
    so the new comparch_mint validator can read parent resps + their
    feat slices and accept the ``<owns>`` block. Pass
    ``fanned_out=False`` to skip the resp/feat seeds and the
    template ``.format(...)`` call — the caller is expected to
    pass the un-fanned-out template that has no placeholders.
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
                kind=comp_kind,  # type: ignore[arg-type]
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
                    kind=comp_kind,  # type: ignore[arg-type]
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
                    kind=comp_kind,  # type: ignore[arg-type]
                    parent_id=None,
                    name="ParentFeat",
                    content="Feat.",
                ),
            )
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


def _fanin_children(session: Session, project_id: str, comp_id: str) -> list[Node]:
    return list(
        session.execute(
            select(Node).where(
                Node.project_id == project_id,
                Node.tier == "fanin",
                Node.parent_id == comp_id,
            )
        ).scalars()
    )


class TestFannedOutDomain:
    def test_mints_one_fanin_shell_under_comp(self, shared_session_factory):
        project_id, comp_id = _seed_project_with_comp(
            shared_session_factory, _fanned_out_comparch()
        )
        asyncio.run(mint_comparch({"project_id": project_id, "component_id": comp_id}))

        session = shared_session_factory()
        try:
            fanins = _fanin_children(session, project_id, comp_id)
            assert len(fanins) == 1
            fanin = fanins[0]
            assert fanin.tier == "fanin"
            assert fanin.kind == "domain"
            assert fanin.parent_id == comp_id
            assert fanin.content == ""
            assert fanin.name.endswith("fan-in")
            assert fanin.id.startswith("fanin_")
        finally:
            session.close()

    def test_does_not_enqueue_generate_fanin(self, shared_session_factory):
        project_id, comp_id = _seed_project_with_comp(
            shared_session_factory, _fanned_out_comparch()
        )
        asyncio.run(mint_comparch({"project_id": project_id, "component_id": comp_id}))

        session = shared_session_factory()
        try:
            jobs = list(
                session.execute(select(Job).where(Job.job_type == "v2.generate_fanin")).scalars()
            )
            # Fan-in generation must be triggered by the first
            # impl approval, not at mint time. No jobs here.
            assert jobs == []
        finally:
            session.close()


class TestUnFannedOutDomain:
    def test_does_not_mint_fanin_shell(self, shared_session_factory):
        project_id, comp_id = _seed_project_with_comp(
            shared_session_factory,
            _un_fanned_out_comparch(),
            fanned_out=False,
        )
        asyncio.run(mint_comparch({"project_id": project_id, "component_id": comp_id}))

        session = shared_session_factory()
        try:
            fanins = _fanin_children(session, project_id, comp_id)
            assert fanins == []
        finally:
            session.close()


class TestPresentational:
    def test_fanned_out_presentational_mints_no_fanin(self, shared_session_factory):
        project_id, comp_id = _seed_project_with_comp(
            shared_session_factory,
            _fanned_out_comparch(),
            comp_kind="presentational",
        )
        asyncio.run(mint_comparch({"project_id": project_id, "component_id": comp_id}))

        session = shared_session_factory()
        try:
            fanins = _fanin_children(session, project_id, comp_id)
            # Presentational comps present domain comps; they don't
            # get their own fan-in synthesis.
            assert fanins == []
        finally:
            session.close()


class TestIdempotency:
    def test_repeated_mint_does_not_create_duplicate_fanin(self, shared_session_factory):
        project_id, comp_id = _seed_project_with_comp(
            shared_session_factory, _fanned_out_comparch()
        )
        asyncio.run(mint_comparch({"project_id": project_id, "component_id": comp_id}))
        # Second call hits the existing-subcomponents guard and
        # returns early; the fan-in shell should still be exactly
        # one.
        asyncio.run(mint_comparch({"project_id": project_id, "component_id": comp_id}))

        session = shared_session_factory()
        try:
            fanins = _fanin_children(session, project_id, comp_id)
            assert len(fanins) == 1
        finally:
            session.close()


class TestShellShape:
    def test_fanin_id_prefix_is_fanin(self, shared_session_factory):
        project_id, comp_id = _seed_project_with_comp(
            shared_session_factory, _fanned_out_comparch()
        )
        asyncio.run(mint_comparch({"project_id": project_id, "component_id": comp_id}))

        session = shared_session_factory()
        try:
            fanin = _fanin_children(session, project_id, comp_id)[0]
            assert fanin.id.startswith("fanin_")
            assert len(fanin.id) == len("fanin_") + 8
        finally:
            session.close()
