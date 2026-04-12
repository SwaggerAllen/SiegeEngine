"""Regression tests for the subcomponent depth-cap invariant.

Per ``docs/architecture/v2-rearchitecture.md`` §Subcomponent depth
cap, the structural component tree is hard-capped at two levels:

    top-level comp → subcomponent comp → impl

A subcomponent (``comp_*`` whose parent is another ``comp_*``)
cannot itself be the parent of a third ``comp_*``. The reducer
enforces this on every event whose target tier is ``comp``:
``NodeCreated``, ``NodeReparented``, ``NodePromoted``,
``NodeDemoted``.

Non-comp tiers and top-level comps (attached to a responsibility
or no parent at all) are unaffected by the cap.
"""

from __future__ import annotations

import pytest

from backend.graph import events as ev
from backend.graph.reducer import ReducerError, append_event
from backend.models.node import Node


def _mk_node(db, project_id, node_id, tier, parent_id=None):
    append_event(
        db,
        project_id,
        ev.NodeCreated(
            node_id=node_id,
            tier=tier,
            kind="domain",
            parent_id=parent_id,
            name=node_id,
        ),
    )
    db.flush()


class TestNodeCreated:
    def test_top_level_comp_allowed(self, db, project):
        """A comp with no parent — the common case — is fine."""
        _mk_node(db, project.id, "comp_TOP00001", "comp")

    def test_comp_under_responsibility_allowed(self, db, project):
        """A top-level comp attached to a resp is fine (resp isn't a comp)."""
        _mk_node(db, project.id, "resp_RESP0001", "resp")
        _mk_node(db, project.id, "comp_TOP00002", "comp", parent_id="resp_RESP0001")

    def test_subcomponent_allowed(self, db, project):
        """Two-level chain: top comp → subcomp — allowed."""
        _mk_node(db, project.id, "comp_PAR00001", "comp")
        _mk_node(db, project.id, "comp_SUB00001", "comp", parent_id="comp_PAR00001")

    def test_three_level_comp_chain_rejected(self, db, project):
        """Three-level chain: top comp → subcomp → subsubcomp — rejected."""
        _mk_node(db, project.id, "comp_PAR00002", "comp")
        _mk_node(db, project.id, "comp_SUB00002", "comp", parent_id="comp_PAR00002")
        with pytest.raises(ReducerError, match="Subcomponent depth cap"):
            _mk_node(
                db,
                project.id,
                "comp_SSB00001",
                "comp",
                parent_id="comp_SUB00002",
            )

    def test_impl_under_subcomponent_allowed(self, db, project):
        """An impl child of a subcomponent is fine — only comp children trigger the cap."""
        _mk_node(db, project.id, "comp_PAR00003", "comp")
        _mk_node(db, project.id, "comp_SUB00003", "comp", parent_id="comp_PAR00003")
        _mk_node(db, project.id, "impl_IMPL0001", "impl", parent_id="comp_SUB00003")


class TestNodeReparented:
    def test_moving_comp_under_subcomponent_rejected(self, db, project):
        """Reparent that would make a comp three-deep is rejected."""
        _mk_node(db, project.id, "comp_P0000001", "comp")
        _mk_node(db, project.id, "comp_S0000001", "comp", parent_id="comp_P0000001")
        _mk_node(db, project.id, "comp_X0000001", "comp")  # top-level, will be moved

        with pytest.raises(ReducerError, match="Subcomponent depth cap"):
            append_event(
                db,
                project.id,
                ev.NodeReparented(node_id="comp_X0000001", new_parent_id="comp_S0000001"),
            )

    def test_moving_comp_under_top_level_comp_allowed(self, db, project):
        """Reparenting into a two-level chain is still allowed."""
        _mk_node(db, project.id, "comp_P0000002", "comp")
        _mk_node(db, project.id, "comp_X0000002", "comp")
        append_event(
            db,
            project.id,
            ev.NodeReparented(node_id="comp_X0000002", new_parent_id="comp_P0000002"),
        )
        db.flush()
        node = db.get(Node, "comp_X0000002")
        assert node is not None
        assert node.parent_id == "comp_P0000002"


class TestNodePromoted:
    def test_promoting_to_comp_under_subcomponent_rejected(self, db, project):
        """Promoting an impl to a comp under a subcomponent is rejected."""
        _mk_node(db, project.id, "comp_P0000003", "comp")
        _mk_node(db, project.id, "comp_S0000003", "comp", parent_id="comp_P0000003")
        _mk_node(db, project.id, "impl_I0000001", "impl", parent_id="comp_S0000003")

        with pytest.raises(ReducerError, match="Subcomponent depth cap"):
            append_event(
                db,
                project.id,
                ev.NodePromoted(node_id="impl_I0000001", new_tier="comp"),
            )

    def test_promoting_to_resp_under_anything_allowed(self, db, project):
        """Promoting to a non-comp tier never triggers the cap."""
        _mk_node(db, project.id, "resp_R0000001", "resp")
        _mk_node(db, project.id, "feat_F0000001", "feat", parent_id="resp_R0000001")
        append_event(
            db,
            project.id,
            ev.NodePromoted(node_id="feat_F0000001", new_tier="resp"),
        )
        db.flush()  # no exception


class TestNodeDemoted:
    def test_demoting_to_comp_respects_cap(self, db, project):
        """Demoting a resp to a comp under a subcomponent parent is rejected."""
        _mk_node(db, project.id, "comp_P0000004", "comp")
        _mk_node(db, project.id, "comp_S0000004", "comp", parent_id="comp_P0000004")
        # Create a resp node that's (unusually) parented to the subcomponent.
        # This isn't a normal graph shape but it's what's needed to test the
        # demote-to-comp path in isolation.
        _mk_node(db, project.id, "resp_R0000002", "resp", parent_id="comp_S0000004")

        with pytest.raises(ReducerError, match="Subcomponent depth cap"):
            append_event(
                db,
                project.id,
                ev.NodeDemoted(node_id="resp_R0000002", new_tier="comp"),
            )
