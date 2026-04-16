"""Phase 6.6 — referenced_content threading tests.

Covers:

- ``RegenContext.referenced_content`` populated by
  ``build_regen_context`` via outgoing ``reference`` edges.
- ``format_regen_context`` / ``format_regen_context_for_sub``
  produce ``referenced_content_summary``.
- The rendered summary is present in the comparch / subcomparch
  user prompts when non-empty and absent when it's the sentinel.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database import Base
from backend.graph import events as ev
from backend.graph.ids import Kind, mint
from backend.graph.prompts.comparch import render_user_prompt as comparch_prompt
from backend.graph.prompts.requirements import render_user_prompt as reqs_prompt
from backend.graph.prompts.subcomparch import render_user_prompt as subcomparch_prompt
from backend.graph.prompts.sysarch import render_user_prompt as sysarch_prompt
from backend.graph.reducer import append_event
from backend.graph.regen_context import (
    build_regen_context,
    format_regen_context,
    format_regen_context_for_sub,
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


def _seed_comp(db: Session, project_id: str, name: str) -> str:
    comp_id = mint(db, Kind.COMP)
    append_event(
        db,
        project_id,
        ev.NodeCreated(
            node_id=comp_id,
            tier="comp",
            kind="domain",
            parent_id=None,
            name=name,
        ),
    )
    return comp_id


def _seed_sub(db: Session, project_id: str, parent_id: str, name: str) -> str:
    sub_id = mint(db, Kind.COMP)
    append_event(
        db,
        project_id,
        ev.NodeCreated(
            node_id=sub_id,
            tier="comp",
            kind="domain",
            parent_id=parent_id,
            name=name,
        ),
    )
    return sub_id


def _seed_ref(db: Session, project_id: str, name: str, body: str) -> str:
    ref_id = mint(db, Kind.REF)
    content = f"<reference><title>{name}</title><body>{body}</body></reference>"
    append_event(
        db,
        project_id,
        ev.NodeCreated(
            node_id=ref_id,
            tier="ref",
            kind="domain",
            parent_id=None,
            name=name,
            content=content,
        ),
    )
    return ref_id


def _add_ref_edge(db: Session, project_id: str, source_id: str, target_id: str) -> str:
    edge_id = mint(db, Kind.EDGE)
    append_event(
        db,
        project_id,
        ev.EdgeCreated(
            edge_id=edge_id,
            edge_type="reference",
            source_id=source_id,
            target_id=target_id,
        ),
    )
    return edge_id


class TestRegenContextReferencedContent:
    def test_build_populates_referenced_content(self, db, project):
        comp_id = _seed_comp(db, project.id, "BillingService")
        ref_id = _seed_ref(db, project.id, "Runbook", "Deploy steps.")
        _add_ref_edge(db, project.id, comp_id, ref_id)

        ctx = build_regen_context(db, comp_id)
        assert ref_id in ctx.referenced_content
        assert "Deploy steps" in ctx.referenced_content[ref_id]

    def test_build_empty_when_no_edges(self, db, project):
        comp_id = _seed_comp(db, project.id, "BillingService")
        ctx = build_regen_context(db, comp_id)
        assert ctx.referenced_content == {}

    def test_format_regen_context_emits_summary_key(self, db, project):
        comp_id = _seed_comp(db, project.id, "BillingService")
        ref_id = _seed_ref(db, project.id, "Runbook", "Deploy steps.")
        _add_ref_edge(db, project.id, comp_id, ref_id)
        ctx = build_regen_context(db, comp_id)
        formatted = format_regen_context(ctx)
        assert "referenced_content_summary" in formatted
        assert "# References" in formatted["referenced_content_summary"]
        assert ref_id in formatted["referenced_content_summary"]

    def test_format_regen_context_sentinel_when_empty(self, db, project):
        comp_id = _seed_comp(db, project.id, "BillingService")
        ctx = build_regen_context(db, comp_id)
        formatted = format_regen_context(ctx)
        assert formatted["referenced_content_summary"] == "(no external references)"

    def test_format_regen_context_for_sub_emits_summary_key(self, db, project):
        parent_id = _seed_comp(db, project.id, "Parent")
        sub_id = _seed_sub(db, project.id, parent_id, "Child")
        ref_id = _seed_ref(db, project.id, "SubRef", "sub body.")
        _add_ref_edge(db, project.id, sub_id, ref_id)
        ctx = build_regen_context(db, sub_id)
        formatted = format_regen_context_for_sub(ctx)
        assert "referenced_content_summary" in formatted
        assert "# References" in formatted["referenced_content_summary"]


class TestPromptsThreadReferencedContent:
    """The prompt rendering helpers include the summary block when non-empty."""

    def test_comparch_prompt_includes_references_section(self):
        summary = "# References\n\n## ref_X\n\nfoo content"
        prompt = comparch_prompt(
            component_summary="Comp",
            parent_resps_summary="Resps",
            subresps_summary="Subresps",
            sibling_comps_summary="Siblings",
            dep_pubapi_summary="",
            top_level_policy_candidates_summary="",
            related_features_summary="",
            prior_approved=None,
            prior_pending=None,
            feedback=None,
            referenced_content_summary=summary,
        )
        assert "# References" in prompt
        assert "foo content" in prompt

    def test_comparch_prompt_sentinel_omits_section(self):
        prompt = comparch_prompt(
            component_summary="Comp",
            parent_resps_summary="Resps",
            subresps_summary="Subresps",
            sibling_comps_summary="Siblings",
            dep_pubapi_summary="",
            top_level_policy_candidates_summary="",
            related_features_summary="",
            prior_approved=None,
            prior_pending=None,
            feedback=None,
            referenced_content_summary="(no external references)",
        )
        assert "# References" not in prompt

    def test_subcomparch_prompt_includes_references(self):
        prompt = subcomparch_prompt(
            subcomponent_summary="Sub",
            parent_component_summary="Parent",
            subresps_summary="",
            sibling_subcomps_summary="",
            parent_sibling_comps_summary="",
            dep_pubapi_summary="",
            prior_approved=None,
            prior_pending=None,
            feedback=None,
            referenced_content_summary="# References\n\n## ref_Q\n\nqux body",
        )
        assert "qux body" in prompt

    def test_sysarch_prompt_includes_references(self):
        prompt = sysarch_prompt(
            features_summary="f",
            reqs_summary="r",
            prior_approved=None,
            prior_pending=None,
            feedback=None,
            referenced_content_summary="# References\n\n## ref_Z\n\nzzz",
        )
        assert "zzz" in prompt

    def test_requirements_prompt_includes_references(self):
        prompt = reqs_prompt(
            features_summary="f",
            prior_approved=None,
            prior_pending=None,
            feedback=None,
            referenced_content_summary="# References\n\n## ref_R\n\nrrr",
        )
        assert "rrr" in prompt

    def test_requirements_prompt_sentinel_omits(self):
        prompt = reqs_prompt(
            features_summary="f",
            prior_approved=None,
            prior_pending=None,
            feedback=None,
            referenced_content_summary="(no external references)",
        )
        assert "# References" not in prompt
