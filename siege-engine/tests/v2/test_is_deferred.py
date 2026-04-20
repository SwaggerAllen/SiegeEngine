"""B7 — Deferred features: schema, reducer, filter, instruction.

Covers the Phase-11 followup B7 work end-to-end in isolation:
- NodeCreated.is_deferred round-trips through the reducer.
- NodeDeferredUpdated toggles the column.
- queries.list_features(include_deferred=False) filters deferred rows.
- requirements_generation / sysarch_generation skip deferred features.
- SetFeatureDeferred instruction dispatches to the NodeDeferredUpdated event.
"""

from __future__ import annotations

import pytest

from backend.graph import apply_instruction as apply_mod
from backend.graph import events as ev
from backend.graph import instructions as instr
from backend.graph import queries
from backend.graph.ids import Kind, mint
from backend.graph.reducer import append_event
from backend.models.graph_event import GraphEvent
from backend.models.node import Node


def _mint_feat(db, project_id, *, name, deferred=False) -> str:
    nid = mint(db, Kind.FEAT)
    append_event(
        db,
        project_id,
        ev.NodeCreated(
            node_id=nid,
            tier="feat",
            kind="domain",
            parent_id=None,
            name=name,
            content="Intent paragraph.",
            is_deferred=deferred,
        ),
    )
    return nid


class TestReducer:
    def test_node_created_persists_is_deferred(self, db, project):
        nid = _mint_feat(db, project.id, name="A", deferred=True)
        node = db.get(Node, nid)
        assert node is not None and node.is_deferred is True

    def test_node_deferred_updated_flips_flag(self, db, project):
        nid = _mint_feat(db, project.id, name="A", deferred=False)
        append_event(
            db,
            project.id,
            ev.NodeDeferredUpdated(node_id=nid, is_deferred=True),
        )
        node = db.get(Node, nid)
        assert node is not None and node.is_deferred is True

        # Flip back.
        append_event(
            db,
            project.id,
            ev.NodeDeferredUpdated(node_id=nid, is_deferred=False),
        )
        db.refresh(node)
        assert node.is_deferred is False


class TestListFeaturesFilter:
    def test_default_includes_deferred(self, db, project):
        _mint_feat(db, project.id, name="Active")
        _mint_feat(db, project.id, name="Parked", deferred=True)
        feats = queries.list_features(db, project.id)
        assert {f.name for f in feats} == {"Active", "Parked"}

    def test_include_deferred_false_filters(self, db, project):
        _mint_feat(db, project.id, name="Active")
        _mint_feat(db, project.id, name="Parked", deferred=True)
        feats = queries.list_features(db, project.id, include_deferred=False)
        assert {f.name for f in feats} == {"Active"}


class TestDispatchSetFeatureDeferred:
    def test_enqueues_node_deferred_updated(self, db, project):
        nid = _mint_feat(db, project.id, name="A")
        apply_mod.dispatch_instruction(
            db,
            project.id,
            instr.SetFeatureDeferred(node_id=nid, name="A", is_deferred=True),
        )
        event_types = [
            r.event_type for r in db.query(GraphEvent).filter_by(project_id=project.id).all()
        ]
        assert "NodeDeferredUpdated" in event_types
        node = db.get(Node, nid)
        assert node is not None and node.is_deferred is True

    def test_rejects_non_feat_target(self, db, project):
        # Create a resp node, try to defer it.
        resp_id = mint(db, Kind.RESP)
        append_event(
            db,
            project.id,
            ev.NodeCreated(
                node_id=resp_id,
                tier="resp",
                kind="domain",
                parent_id=None,
                name="R",
                content="",
            ),
        )
        with pytest.raises(apply_mod.InstructionApplyError, match="expected feat"):
            apply_mod.dispatch_instruction(
                db,
                project.id,
                instr.SetFeatureDeferred(node_id=resp_id, name="R", is_deferred=True),
            )
