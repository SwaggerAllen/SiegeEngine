"""Reducer tests for the Phase 7 FanInContentUpdated event.

The event:
- Overwrites Node.content for a tier="fanin" node.
- Asserts the target is on the fanin tier.
- Does NOT touch Draft rows (fanin has no draft lifecycle).
- Rebuilds identically via rebuild_projections.
"""

from __future__ import annotations

import pytest

from backend.graph import events as ev
from backend.graph.reducer import ReducerError, append_event, rebuild_projections
from backend.models.node import Draft, Node


class TestFanInContentUpdated:
    def test_overwrites_empty_shell_content(self, db, project):
        # Mint the owning comp + a fanin shell under it.
        append_event(
            db,
            project.id,
            ev.NodeCreated(
                node_id="comp_OWNER111",
                tier="comp",
                kind="domain",
                parent_id=None,
                name="Owner",
            ),
        )
        append_event(
            db,
            project.id,
            ev.NodeCreated(
                node_id="fanin_FIN00001",
                tier="fanin",
                kind="domain",
                parent_id="comp_OWNER111",
                name="Owner fan-in",
                content="",
            ),
        )
        assert db.get(Node, "fanin_FIN00001").content == ""

        new_xml = (
            "<fanin>"
            "<summary>Built.</summary>"
            "<exposed-surface>E.</exposed-surface>"
            "<realized-behavior>R.</realized-behavior>"
            "</fanin>"
        )
        append_event(
            db,
            project.id,
            ev.FanInContentUpdated(node_id="fanin_FIN00001", new_content=new_xml),
        )
        assert db.get(Node, "fanin_FIN00001").content == new_xml

    def test_overwrites_existing_content(self, db, project):
        append_event(
            db,
            project.id,
            ev.NodeCreated(
                node_id="comp_OWNER222",
                tier="comp",
                kind="domain",
                parent_id=None,
                name="Owner",
            ),
        )
        append_event(
            db,
            project.id,
            ev.NodeCreated(
                node_id="fanin_FIN00002",
                tier="fanin",
                kind="domain",
                parent_id="comp_OWNER222",
                name="Owner fan-in",
                content="<fanin>old</fanin>",
            ),
        )
        append_event(
            db,
            project.id,
            ev.FanInContentUpdated(
                node_id="fanin_FIN00002",
                new_content="<fanin>new</fanin>",
            ),
        )
        assert db.get(Node, "fanin_FIN00002").content == "<fanin>new</fanin>"

    def test_rejects_non_fanin_tier(self, db, project):
        # Target a comp node (tier="comp") instead of fanin.
        append_event(
            db,
            project.id,
            ev.NodeCreated(
                node_id="comp_WRONG111",
                tier="comp",
                kind="domain",
                parent_id=None,
                name="W",
            ),
        )
        with pytest.raises(ReducerError, match=r"expected tier='fanin'"):
            append_event(
                db,
                project.id,
                ev.FanInContentUpdated(node_id="comp_WRONG111", new_content="<fanin/>"),
            )

    def test_unknown_node_rolls_back(self, db, project):
        with pytest.raises(ReducerError, match="not found"):
            append_event(
                db,
                project.id,
                ev.FanInContentUpdated(
                    node_id="fanin_NOPEXXXX",
                    new_content="<fanin/>",
                ),
            )

    def test_no_draft_row_created(self, db, project):
        """Fan-in has no draft lifecycle — event writes Node.content directly."""
        append_event(
            db,
            project.id,
            ev.NodeCreated(
                node_id="comp_OWNER333",
                tier="comp",
                kind="domain",
                parent_id=None,
                name="O",
            ),
        )
        append_event(
            db,
            project.id,
            ev.NodeCreated(
                node_id="fanin_FIN00003",
                tier="fanin",
                kind="domain",
                parent_id="comp_OWNER333",
                name="O fan-in",
            ),
        )
        append_event(
            db,
            project.id,
            ev.FanInContentUpdated(
                node_id="fanin_FIN00003",
                new_content="<fanin>body</fanin>",
            ),
        )
        drafts = list(db.query(Draft).filter(Draft.project_id == project.id).all())
        assert drafts == []

    def test_rebuild_preserves_fanin_content(self, db, project):
        append_event(
            db,
            project.id,
            ev.NodeCreated(
                node_id="comp_OWNER444",
                tier="comp",
                kind="domain",
                parent_id=None,
                name="O",
            ),
        )
        append_event(
            db,
            project.id,
            ev.NodeCreated(
                node_id="fanin_FIN00004",
                tier="fanin",
                kind="domain",
                parent_id="comp_OWNER444",
                name="O fan-in",
            ),
        )
        append_event(
            db,
            project.id,
            ev.FanInContentUpdated(
                node_id="fanin_FIN00004",
                new_content="<fanin>rebuilt</fanin>",
            ),
        )
        # Rebuild from the log and confirm the content re-lands.
        rebuild_projections(db, project.id)
        assert db.get(Node, "fanin_FIN00004").content == "<fanin>rebuilt</fanin>"
