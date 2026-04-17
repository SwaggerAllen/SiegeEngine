"""Tests for ``format_regen_context_for_impl`` (Phase 8).

Verifies the impl-prompt kwargs shape for both owner flavors:
top-level comp (no parent_summary) and subcomponent (parent_summary
populated from the owning comp's fragments).
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
    format_regen_context_for_impl,
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
    session = factory()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def project(db):
    p = Project(id=str(uuid.uuid4()), name="T", git_repo_path="/tmp/t")
    db.add(p)
    db.commit()
    return p


def _seed_comp(db: Session, project_id: str, parent_id: str | None, name: str) -> str:
    comp_id = mint(db, Kind.COMP)
    append_event(
        db,
        project_id,
        ev.NodeCreated(
            node_id=comp_id,
            tier="comp",
            kind="domain",
            parent_id=parent_id,
            name=name,
        ),
    )
    return comp_id


def _seed_fragment(db, project_id, owner_id, kind: FragmentKind, content: str) -> None:
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


class TestFormatForTopLevelOwner:
    def test_returns_expected_keys(self, db, project):
        comp_id = _seed_comp(db, project.id, None, "TopComp")
        _seed_fragment(db, project.id, comp_id, FragmentKind.TECHSPEC, "top techspec")
        _seed_fragment(db, project.id, comp_id, FragmentKind.PUBAPI, "top pubapi")
        _seed_fragment(db, project.id, comp_id, FragmentKind.PRIVAPI, "top privapi")

        ctx = build_regen_context(db, comp_id)
        kwargs = format_regen_context_for_impl(ctx)

        expected_keys = {
            "owner_summary",
            "parent_summary",
            "dep_pubapi_summary",
            "vocab_summary",
            "referenced_content_summary",
        }
        assert set(kwargs.keys()) == expected_keys

    def test_owner_summary_contains_own_fragments(self, db, project):
        comp_id = _seed_comp(db, project.id, None, "TopComp")
        _seed_fragment(db, project.id, comp_id, FragmentKind.TECHSPEC, "OWN_TS")
        _seed_fragment(db, project.id, comp_id, FragmentKind.PUBAPI, "OWN_PUB")
        _seed_fragment(db, project.id, comp_id, FragmentKind.PRIVAPI, "OWN_PRIV")

        ctx = build_regen_context(db, comp_id)
        kwargs = format_regen_context_for_impl(ctx)

        assert "TopComp" in kwargs["owner_summary"]
        assert "OWN_TS" in kwargs["owner_summary"]
        assert "OWN_PUB" in kwargs["owner_summary"]
        assert "OWN_PRIV" in kwargs["owner_summary"]

    def test_parent_summary_empty_for_top_level(self, db, project):
        comp_id = _seed_comp(db, project.id, None, "TopComp")
        ctx = build_regen_context(db, comp_id)
        kwargs = format_regen_context_for_impl(ctx)
        assert kwargs["parent_summary"] == ""


class TestFormatForSubcomponentOwner:
    def test_parent_summary_populated_from_parent_fragments(self, db, project):
        top_id = _seed_comp(db, project.id, None, "Parent")
        _seed_fragment(db, project.id, top_id, FragmentKind.TECHSPEC, "PARENT_TS")
        _seed_fragment(db, project.id, top_id, FragmentKind.PUBAPI, "PARENT_PUB")
        _seed_fragment(db, project.id, top_id, FragmentKind.PRIVAPI, "PARENT_PRIV")
        sub_id = _seed_comp(db, project.id, top_id, "Sub")
        _seed_fragment(db, project.id, sub_id, FragmentKind.TECHSPEC, "SUB_TS")
        _seed_fragment(db, project.id, sub_id, FragmentKind.PUBAPI, "SUB_PUB")

        ctx = build_regen_context(db, sub_id)
        kwargs = format_regen_context_for_impl(ctx)

        # Owner summary shows the subcomponent's own fragments.
        assert "Sub" in kwargs["owner_summary"]
        assert "SUB_TS" in kwargs["owner_summary"]
        assert "SUB_PUB" in kwargs["owner_summary"]
        # Parent summary shows the owning top-level's fragments.
        assert "Parent" in kwargs["parent_summary"]
        assert "PARENT_TS" in kwargs["parent_summary"]
        assert "PARENT_PUB" in kwargs["parent_summary"]
        assert "PARENT_PRIV" in kwargs["parent_summary"]

    def test_referenced_content_sentinel_when_empty(self, db, project):
        top_id = _seed_comp(db, project.id, None, "Parent")
        sub_id = _seed_comp(db, project.id, top_id, "Sub")
        ctx = build_regen_context(db, sub_id)
        kwargs = format_regen_context_for_impl(ctx)
        assert kwargs["referenced_content_summary"] == "(no external references)"
