"""Tests for backend.graph.expansion helpers."""

from __future__ import annotations

import uuid

import pytest

from backend.graph import events as ev
from backend.graph.expansion import (
    EXPANSION_NODE_NAME,
    EXPANSION_TIER,
    bootstrap_expansion_node,
    get_expansion_node,
    has_been_approved,
    pending_expansion_draft,
)
from backend.graph.reducer import append_event
from backend.models import Project


@pytest.fixture()
def project_b(db):
    p = Project(
        id=str(uuid.uuid4()),
        name="Project B",
        git_repo_path="/tmp/test-repo-b",
    )
    db.add(p)
    db.flush()
    return p


class TestBootstrapExpansionNode:
    def test_creates_expansion_node(self, db, project):
        node_id = bootstrap_expansion_node(db, project.id)
        db.flush()

        assert node_id.startswith("expansion_")
        node = get_expansion_node(db, project.id)
        assert node is not None
        assert node.id == node_id
        assert node.tier == EXPANSION_TIER
        assert node.kind == "domain"
        assert node.parent_id is None
        assert node.name == EXPANSION_NODE_NAME
        assert node.content == ""

    def test_scoped_per_project(self, db, project, project_b):
        a_id = bootstrap_expansion_node(db, project.id)
        b_id = bootstrap_expansion_node(db, project_b.id)
        db.flush()

        assert a_id != b_id
        a_node = get_expansion_node(db, project.id)
        b_node = get_expansion_node(db, project_b.id)
        assert a_node is not None
        assert b_node is not None
        assert a_node.id == a_id
        assert b_node.id == b_id


class TestGetExpansionNode:
    def test_missing_returns_none(self, db, project):
        assert get_expansion_node(db, project.id) is None


class TestPendingExpansionDraft:
    def test_missing_node_returns_none(self, db, project):
        assert pending_expansion_draft(db, project.id) is None

    def test_no_pending_draft_returns_none(self, db, project):
        bootstrap_expansion_node(db, project.id)
        db.flush()
        assert pending_expansion_draft(db, project.id) is None

    def test_returns_pending_draft(self, db, project):
        exp_id = bootstrap_expansion_node(db, project.id)
        append_event(
            db,
            project.id,
            ev.DraftGenerated(
                draft_id="draft_DEADBEEF",
                target_type="node",
                target_id=exp_id,
                content="hello",
                batch_id="batch_01",
            ),
        )
        db.flush()

        draft = pending_expansion_draft(db, project.id)
        assert draft is not None
        assert draft.id == "draft_DEADBEEF"
        assert draft.content == "hello"
        assert draft.status == "pending"

    def test_scoped_per_project(self, db, project, project_b):
        a_id = bootstrap_expansion_node(db, project.id)
        bootstrap_expansion_node(db, project_b.id)
        append_event(
            db,
            project.id,
            ev.DraftGenerated(
                draft_id="draft_AAAA1111",
                target_type="node",
                target_id=a_id,
                content="a",
                batch_id="batch_01",
            ),
        )
        db.flush()

        assert pending_expansion_draft(db, project.id) is not None
        assert pending_expansion_draft(db, project_b.id) is None


class TestHasBeenApproved:
    def test_no_node_returns_false(self, db, project):
        assert has_been_approved(db, project.id) is False

    def test_bootstrap_only_returns_false(self, db, project):
        bootstrap_expansion_node(db, project.id)
        db.flush()
        assert has_been_approved(db, project.id) is False

    def test_pending_draft_only_returns_false(self, db, project):
        exp_id = bootstrap_expansion_node(db, project.id)
        append_event(
            db,
            project.id,
            ev.DraftGenerated(
                draft_id="draft_PENDING1",
                target_type="node",
                target_id=exp_id,
                content="draft content",
                batch_id="batch_01",
            ),
        )
        db.flush()
        assert has_been_approved(db, project.id) is False

    def test_after_approval_returns_true(self, db, project):
        exp_id = bootstrap_expansion_node(db, project.id)
        append_event(
            db,
            project.id,
            ev.DraftGenerated(
                draft_id="draft_APPROVE1",
                target_type="node",
                target_id=exp_id,
                content="approved prose",
                batch_id="batch_01",
            ),
        )
        append_event(
            db,
            project.id,
            ev.DraftApproved(draft_id="draft_APPROVE1"),
        )
        db.flush()
        assert has_been_approved(db, project.id) is True
