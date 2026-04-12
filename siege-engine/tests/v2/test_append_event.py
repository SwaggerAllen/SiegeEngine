"""Tests for append_event: offset assignment and rollback."""

from __future__ import annotations

import pytest

from backend.graph import events as ev
from backend.graph.reducer import ReducerError, append_event
from backend.models import Project
from backend.models.graph_event import GraphEvent
from backend.models.node import Node


class TestOffsetAssignment:
    def test_monotonic_within_project(self, db, project):
        offsets = []
        for i in range(5):
            offset = append_event(
                db,
                project.id,
                ev.NodeCreated(
                    node_id=f"comp_NN{i:06d}", tier="comp", kind="domain", name=f"N{i}"
                ),
            )
            offsets.append(offset)
        assert offsets == [1, 2, 3, 4, 5]

    def test_independent_across_projects(self, db, project):
        other = Project(
            id=project.id + "-x", name="Other", git_repo_path="/tmp/other"
        )
        db.add(other)
        db.flush()

        a1 = append_event(
            db, project.id,
            ev.NodeCreated(node_id="comp_AAAAAAAA", tier="comp", kind="domain", name="A"),
        )
        b1 = append_event(
            db, other.id,
            ev.NodeCreated(node_id="comp_BBBBBBBB", tier="comp", kind="domain", name="B"),
        )
        a2 = append_event(
            db, project.id,
            ev.NodeRenamed(node_id="comp_AAAAAAAA", new_name="A2"),
        )
        b2 = append_event(
            db, other.id,
            ev.NodeRenamed(node_id="comp_BBBBBBBB", new_name="B2"),
        )
        assert a1 == 1 and b1 == 1
        assert a2 == 2 and b2 == 2


class TestTransactionalRollback:
    def test_failed_apply_does_not_leave_event_row(self, db, project):
        # DraftEdited against a non-existent draft raises ReducerError,
        # which should roll back the just-written graph_events row too.
        before_count = (
            db.query(GraphEvent).filter(GraphEvent.project_id == project.id).count()
        )
        with pytest.raises(ReducerError):
            append_event(
                db, project.id,
                ev.DraftEdited(draft_id="ghost", new_content="x"),
            )
        after_count = (
            db.query(GraphEvent).filter(GraphEvent.project_id == project.id).count()
        )
        assert after_count == before_count


class TestReadYourWrites:
    def test_session_sees_new_node_immediately(self, db, project):
        append_event(
            db, project.id,
            ev.NodeCreated(node_id="comp_YYYYYYYY", tier="comp", kind="domain", name="Y"),
        )
        # No commit — same session should still see it.
        assert db.get(Node, "comp_YYYYYYYY") is not None
