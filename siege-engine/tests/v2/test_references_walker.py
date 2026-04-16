"""Tests for ``references.referenced_content_for_node`` walker.

The walker is source-tier-agnostic: it follows outgoing
``reference`` edges from ANY source node and dispatches on each
target's tier to pull the right chunk (ref → rendered XML,
comp → pubapi fragment, policy/feat/resp → Node.content).
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database import Base
from backend.graph import events as ev
from backend.graph.fragments import FragmentKind
from backend.graph.ids import Kind, mint
from backend.graph.reducer import append_event
from backend.graph.references import (
    format_referenced_content_summary,
    referenced_content_for_node,
    render_referenced_content_summary,
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
    project = Project(id=str(uuid.uuid4()), name="T", git_repo_path="/tmp/t")
    db.add(project)
    db.commit()
    return project


def _seed_node(
    db: Session,
    project_id: str,
    tier: str,
    kind_enum: Kind,
    name: str,
    content: str = "",
    parent_id: str | None = None,
) -> str:
    node_id = mint(db, kind_enum)
    append_event(
        db,
        project_id,
        ev.NodeCreated(
            node_id=node_id,
            tier=tier,
            kind="domain",
            parent_id=parent_id,
            name=name,
            content=content,
        ),
    )
    return node_id


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


def _seed_pubapi_fragment(db: Session, project_id: str, owner_id: str, content: str) -> None:
    from backend.graph.fragments import fragment_id

    append_event(
        db,
        project_id,
        ev.FragmentUpdated(
            fragment_id=fragment_id(owner_id, FragmentKind.PUBAPI),
            owner_id=owner_id,
            fragment_kind=FragmentKind.PUBAPI,
            new_content=content,
        ),
    )


class TestReferencedContentForNode:
    def test_empty_when_no_outgoing_edges(self, db, project):
        ref_id = _seed_node(db, project.id, "ref", Kind.REF, "Runbook")
        result = referenced_content_for_node(db, project.id, ref_id)
        assert result == {}

    def test_dispatches_to_ref_xml_rendering(self, db, project):
        ref_a = _seed_node(db, project.id, "ref", Kind.REF, "A")
        ref_b = _seed_node(
            db,
            project.id,
            "ref",
            Kind.REF,
            "B",
            content="<reference><title>Ref B</title><body>Body of B.</body></reference>",
        )
        _add_ref_edge(db, project.id, ref_a, ref_b)
        result = referenced_content_for_node(db, project.id, ref_a)
        assert ref_b in result
        assert "Body of B" in result[ref_b]
        # Renderer includes title in rendered output
        assert "Ref B" in result[ref_b]

    def test_dispatches_to_comp_pubapi(self, db, project):
        ref_id = _seed_node(db, project.id, "ref", Kind.REF, "Runbook")
        comp_id = _seed_node(db, project.id, "comp", Kind.COMP, "BillingService")
        _seed_pubapi_fragment(db, project.id, comp_id, "public API contract here")
        _add_ref_edge(db, project.id, ref_id, comp_id)
        result = referenced_content_for_node(db, project.id, ref_id)
        assert result[comp_id] == "public API contract here"

    def test_dispatches_to_feat_content(self, db, project):
        ref_id = _seed_node(db, project.id, "ref", Kind.REF, "Runbook")
        feat_id = _seed_node(
            db, project.id, "feat", Kind.FEAT, "Billing", content="feature intent text"
        )
        _add_ref_edge(db, project.id, ref_id, feat_id)
        result = referenced_content_for_node(db, project.id, ref_id)
        assert result[feat_id] == "feature intent text"

    def test_dispatches_to_policy_content(self, db, project):
        ref_id = _seed_node(db, project.id, "ref", Kind.REF, "Runbook")
        policy_id = _seed_node(
            db,
            project.id,
            "policy",
            Kind.POLICY,
            "LLM Telemetry",
            content="policy rationale text",
        )
        _add_ref_edge(db, project.id, ref_id, policy_id)
        result = referenced_content_for_node(db, project.id, ref_id)
        assert result[policy_id] == "policy rationale text"

    def test_dispatches_to_resp_content(self, db, project):
        ref_id = _seed_node(db, project.id, "ref", Kind.REF, "Runbook")
        resp_id = _seed_node(
            db,
            project.id,
            "resp",
            Kind.RESP,
            "Authenticate users",
            content="handles auth",
        )
        _add_ref_edge(db, project.id, ref_id, resp_id)
        result = referenced_content_for_node(db, project.id, ref_id)
        assert result[resp_id] == "handles auth"

    def test_walker_works_for_comp_source(self, db, project):
        """Walker is source-tier-agnostic — comp can reference a ref."""
        comp_id = _seed_node(db, project.id, "comp", Kind.COMP, "BillingService")
        ref_id = _seed_node(
            db,
            project.id,
            "ref",
            Kind.REF,
            "R",
            content="<reference><title>R</title><body>ref body</body></reference>",
        )
        _add_ref_edge(db, project.id, comp_id, ref_id)
        result = referenced_content_for_node(db, project.id, comp_id)
        assert ref_id in result

    def test_multiple_edges_collected(self, db, project):
        ref_src = _seed_node(db, project.id, "ref", Kind.REF, "Src")
        feat_a = _seed_node(db, project.id, "feat", Kind.FEAT, "A", content="feat A content")
        feat_b = _seed_node(db, project.id, "feat", Kind.FEAT, "B", content="feat B content")
        _add_ref_edge(db, project.id, ref_src, feat_a)
        _add_ref_edge(db, project.id, ref_src, feat_b)
        result = referenced_content_for_node(db, project.id, ref_src)
        assert set(result.keys()) == {feat_a, feat_b}

    def test_dangling_target_skipped_silently(self, db, project):
        ref_id = _seed_node(db, project.id, "ref", Kind.REF, "Runbook")
        feat_id = _seed_node(db, project.id, "feat", Kind.FEAT, "F", content="content")
        _add_ref_edge(db, project.id, ref_id, feat_id)
        # Delete the target node
        append_event(db, project.id, ev.NodeDeleted(node_id=feat_id))
        result = referenced_content_for_node(db, project.id, ref_id)
        assert result == {}

    def test_empty_content_targets_skipped(self, db, project):
        """Target nodes with empty content produce no entry."""
        ref_id = _seed_node(db, project.id, "ref", Kind.REF, "Runbook")
        feat_id = _seed_node(db, project.id, "feat", Kind.FEAT, "F", content="")
        _add_ref_edge(db, project.id, ref_id, feat_id)
        result = referenced_content_for_node(db, project.id, ref_id)
        assert result == {}


class TestFormatReferencedContentSummary:
    def test_empty_dict_returns_sentinel(self):
        assert format_referenced_content_summary({}) == "(no external references)"

    def test_single_entry_renders_header(self):
        out = format_referenced_content_summary({"ref_ABCDEFGH": "content here"})
        assert "# References" in out
        assert "## ref_ABCDEFGH" in out
        assert "content here" in out

    def test_sorted_by_target_id(self):
        out = format_referenced_content_summary({"ref_BB": "b", "ref_AA": "a"})
        idx_a = out.index("ref_AA")
        idx_b = out.index("ref_BB")
        assert idx_a < idx_b


class TestRenderReferencedContentSummary:
    def test_end_to_end_via_session(self, db, project):
        ref_src = _seed_node(db, project.id, "ref", Kind.REF, "Src")
        feat_id = _seed_node(db, project.id, "feat", Kind.FEAT, "F", content="feature body")
        _add_ref_edge(db, project.id, ref_src, feat_id)
        out = render_referenced_content_summary(db, project.id, ref_src)
        assert "# References" in out
        assert feat_id in out
        assert "feature body" in out

    def test_sentinel_when_no_edges(self, db, project):
        ref_id = _seed_node(db, project.id, "ref", Kind.REF, "Isolated")
        out = render_referenced_content_summary(db, project.id, ref_id)
        assert out == "(no external references)"
