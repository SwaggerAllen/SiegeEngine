"""Tests for Phase 7 fan-in integration into regen_context.

Coverage:
- ``RegenContext.domain_parent_fanins`` populated for
  presentational top-level comps with fanin-bearing domain
  parents.
- Presentational subcomponents inherit the same fanin bundle
  via their parent's domain_parent edges.
- Domain comps (top-level or sub) get an empty fanin bundle.
- Domain parents whose fanin content is empty do NOT appear in
  the map — the presentational prompt falls back to the raw
  pubapi path unchanged.
- ``build_fanin_synthesis_context`` assembles the right inputs
  for the fan-in prompt.
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
    build_fanin_synthesis_context,
    build_regen_context,
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


def _mint_comp(
    db: Session,
    project_id: str,
    name: str,
    *,
    kind: str = "domain",
    parent_id: str | None = None,
) -> str:
    comp_id = mint(db, Kind.COMP)
    append_event(
        db,
        project_id,
        ev.NodeCreated(
            node_id=comp_id,
            tier="comp",
            kind=kind,  # type: ignore[arg-type]
            parent_id=parent_id,
            name=name,
            content="",
        ),
    )
    return comp_id


def _set_fragment(
    db: Session,
    project_id: str,
    owner_id: str,
    kind: FragmentKind,
    content: str,
) -> None:
    append_event(
        db,
        project_id,
        ev.FragmentUpdated(
            fragment_id=fragment_id(owner_id, kind),
            owner_id=owner_id,
            fragment_kind=kind,
            new_content=content,
        ),
    )


def _mint_fanin(
    db: Session,
    project_id: str,
    owner_comp_id: str,
    content: str = "",
) -> str:
    fanin_id = mint(db, Kind.FANIN)
    append_event(
        db,
        project_id,
        ev.NodeCreated(
            node_id=fanin_id,
            tier="fanin",
            kind="domain",
            parent_id=owner_comp_id,
            name="fan-in",
            content=content,
        ),
    )
    return fanin_id


def _mint_domain_parent_edge(
    db: Session,
    project_id: str,
    presentational_id: str,
    domain_id: str,
) -> str:
    edge_id = mint(db, Kind.EDGE)
    append_event(
        db,
        project_id,
        ev.EdgeCreated(
            edge_id=edge_id,
            edge_type="domain_parent",
            source_id=presentational_id,
            target_id=domain_id,
        ),
    )
    return edge_id


@pytest.fixture()
def project_id(db):
    pid = str(uuid.uuid4())
    db.add(Project(id=pid, name="T", git_repo_path="/tmp/t"))
    db.flush()
    return pid


class TestPresentationalPullsFanin:
    def test_fanin_with_content_surfaces_in_map(self, db, project_id):
        domain_id = _mint_comp(db, project_id, "Domain", kind="domain")
        _set_fragment(db, project_id, domain_id, FragmentKind.TECHSPEC, "DomainTS")
        _set_fragment(db, project_id, domain_id, FragmentKind.PUBAPI, "DomainPub")
        _mint_fanin(db, project_id, domain_id, content="<fanin>built</fanin>")

        pres_id = _mint_comp(db, project_id, "Pres", kind="presentational")
        _mint_domain_parent_edge(db, project_id, pres_id, domain_id)
        db.flush()

        ctx = build_regen_context(db, pres_id)
        assert domain_id in ctx.domain_parent_fanins
        assert ctx.domain_parent_fanins[domain_id] == "<fanin>built</fanin>"

    def test_empty_fanin_content_not_surfaced(self, db, project_id):
        domain_id = _mint_comp(db, project_id, "Domain", kind="domain")
        _set_fragment(db, project_id, domain_id, FragmentKind.PUBAPI, "DomainPub")
        _mint_fanin(db, project_id, domain_id, content="")

        pres_id = _mint_comp(db, project_id, "Pres", kind="presentational")
        _mint_domain_parent_edge(db, project_id, pres_id, domain_id)
        db.flush()

        ctx = build_regen_context(db, pres_id)
        # Empty content — no entry. Prompt falls back to raw pubapi.
        assert ctx.domain_parent_fanins == {}

    def test_missing_fanin_node_not_surfaced(self, db, project_id):
        """Un-fanned-out domain parent — no fanin child exists at all."""
        domain_id = _mint_comp(db, project_id, "Domain", kind="domain")
        _set_fragment(db, project_id, domain_id, FragmentKind.PUBAPI, "DomainPub")
        # NO _mint_fanin call.

        pres_id = _mint_comp(db, project_id, "Pres", kind="presentational")
        _mint_domain_parent_edge(db, project_id, pres_id, domain_id)
        db.flush()

        ctx = build_regen_context(db, pres_id)
        assert ctx.domain_parent_fanins == {}


class TestSubOfPresentationalInherits:
    def test_sub_of_presentational_sees_grandparent_fanin(self, db, project_id):
        domain_id = _mint_comp(db, project_id, "Domain", kind="domain")
        _set_fragment(db, project_id, domain_id, FragmentKind.PUBAPI, "DomainPub")
        _mint_fanin(db, project_id, domain_id, content="<fanin>built</fanin>")

        pres_id = _mint_comp(db, project_id, "Pres", kind="presentational")
        _mint_domain_parent_edge(db, project_id, pres_id, domain_id)

        sub_id = _mint_comp(
            db,
            project_id,
            "PresSub",
            kind="presentational",
            parent_id=pres_id,
        )
        db.flush()

        ctx = build_regen_context(db, sub_id)
        assert domain_id in ctx.domain_parent_fanins
        assert ctx.domain_parent_fanins[domain_id] == "<fanin>built</fanin>"


class TestDomainCompsDoNotSeeFanin:
    def test_domain_top_level_sees_no_fanin_map(self, db, project_id):
        """A domain comp has no ``domain_parent`` edges of its own, so
        it sees no fan-in even if a fan-in exists for itself."""
        domain_id = _mint_comp(db, project_id, "Domain", kind="domain")
        _mint_fanin(db, project_id, domain_id, content="<fanin>own</fanin>")
        db.flush()

        ctx = build_regen_context(db, domain_id)
        # Fan-in does not appear in the domain comp's own regen
        # context. It's bottom-up output only consumed by
        # presentational downstream.
        assert ctx.domain_parent_fanins == {}

    def test_domain_sub_sees_no_fanin_map(self, db, project_id):
        top_id = _mint_comp(db, project_id, "Top", kind="domain")
        sub_id = _mint_comp(db, project_id, "Sub", kind="domain", parent_id=top_id)
        _mint_fanin(db, project_id, top_id, content="<fanin>built</fanin>")
        db.flush()

        ctx = build_regen_context(db, sub_id)
        assert ctx.domain_parent_fanins == {}


class TestBuildFaninSynthesisContext:
    def test_assembles_sub_pubapis_and_impls(self, db, project_id):
        top_id = _mint_comp(db, project_id, "Top", kind="domain")
        sub_a = _mint_comp(db, project_id, "SubA", kind="domain", parent_id=top_id)
        sub_b = _mint_comp(db, project_id, "SubB", kind="domain", parent_id=top_id)
        _set_fragment(db, project_id, sub_a, FragmentKind.PUBAPI, "PubA")
        _set_fragment(db, project_id, sub_b, FragmentKind.PUBAPI, "PubB")

        # Each sub has an impl with distinct content.
        for sub_id, name, content in [(sub_a, "SubA", "ImplA"), (sub_b, "SubB", "ImplB")]:
            impl_id = mint(db, Kind.IMPL)
            append_event(
                db,
                project_id,
                ev.NodeCreated(
                    node_id=impl_id,
                    tier="impl",
                    kind="domain",
                    parent_id=sub_id,
                    name=f"{name} impl",
                    content=content,
                ),
            )
        db.flush()

        ctx = build_fanin_synthesis_context(db, top_id)

        # Owner summary is name + id.
        assert "Top" in ctx["owner_summary"]  # type: ignore[operator]
        assert top_id in ctx["owner_summary"]  # type: ignore[operator]

        pubapis = ctx["sub_pubapi_fragments"]
        assert len(pubapis) == 2  # type: ignore[arg-type]
        assert {entry["sub_name"] for entry in pubapis} == {"SubA", "SubB"}  # type: ignore[union-attr,attr-defined]
        assert {entry["pubapi"] for entry in pubapis} == {"PubA", "PubB"}  # type: ignore[union-attr,attr-defined]

        impls = ctx["impl_contents"]
        assert len(impls) == 2  # type: ignore[arg-type]
        assert {entry["content"] for entry in impls} == {"ImplA", "ImplB"}  # type: ignore[union-attr,attr-defined]

    def test_raises_on_unknown_owner(self, db, project_id):
        with pytest.raises(ValueError, match="not found"):
            build_fanin_synthesis_context(db, "comp_NOPEXXXX")

    def test_raises_on_non_comp_owner(self, db, project_id):
        feat_id = mint(db, Kind.FEAT)
        append_event(
            db,
            project_id,
            ev.NodeCreated(
                node_id=feat_id,
                tier="feat",
                kind="domain",
                parent_id=None,
                name="F",
            ),
        )
        db.flush()
        with pytest.raises(ValueError, match="expected 'comp'"):
            build_fanin_synthesis_context(db, feat_id)
