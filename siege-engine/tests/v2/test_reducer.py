"""Reducer tests — projection deltas and rebuild correctness."""

from __future__ import annotations

import pytest

from backend.graph import events as ev
from backend.graph.reducer import (
    ReducerError,
    append_event,
    rebuild_projections,
)
from backend.models.node import Draft, Edge, Fragment, Node

# ── Per-event projection-delta tests ─────────────────────────────────


class TestNodeEvents:
    def test_node_created_inserts_row(self, db, project):
        append_event(
            db,
            project.id,
            ev.NodeCreated(node_id="comp_NNNNNNNN", tier="comp", kind="domain", name="X"),
        )
        row = db.get(Node, "comp_NNNNNNNN")
        assert row is not None
        assert row.name == "X"
        assert row.project_id == project.id
        assert row.tier == "comp"
        assert row.kind == "domain"

    def test_node_renamed_updates_name(self, db, project):
        append_event(
            db,
            project.id,
            ev.NodeCreated(node_id="comp_NNNNNNNN", tier="comp", kind="domain", name="Old"),
        )
        append_event(db, project.id, ev.NodeRenamed(node_id="comp_NNNNNNNN", new_name="New"))
        assert db.get(Node, "comp_NNNNNNNN").name == "New"

    def test_node_reparented(self, db, project):
        append_event(
            db,
            project.id,
            ev.NodeCreated(node_id="feat_PPPPPPPP", tier="feat", kind="domain", name="P"),
        )
        append_event(
            db,
            project.id,
            ev.NodeCreated(node_id="resp_CCCCCCCC", tier="resp", kind="domain", name="C"),
        )
        append_event(
            db,
            project.id,
            ev.NodeReparented(node_id="resp_CCCCCCCC", new_parent_id="feat_PPPPPPPP"),
        )
        assert db.get(Node, "resp_CCCCCCCC").parent_id == "feat_PPPPPPPP"

    def test_node_promoted_changes_tier(self, db, project):
        append_event(
            db,
            project.id,
            ev.NodeCreated(node_id="resp_XXXXXXXX", tier="resp", kind="domain", name="X"),
        )
        append_event(db, project.id, ev.NodePromoted(node_id="resp_XXXXXXXX", new_tier="feat"))
        assert db.get(Node, "resp_XXXXXXXX").tier == "feat"

    def test_node_deleted_removes_row(self, db, project):
        append_event(
            db,
            project.id,
            ev.NodeCreated(node_id="comp_YYYYYYYY", tier="comp", kind="domain", name="Y"),
        )
        append_event(db, project.id, ev.NodeDeleted(node_id="comp_YYYYYYYY"))
        assert db.get(Node, "comp_YYYYYYYY") is None

    def test_nodes_merged_deletes_others(self, db, project):
        for nid, name in [("comp_MMMMMMMM", "M"), ("comp_NNNNNNNN", "N")]:
            append_event(
                db,
                project.id,
                ev.NodeCreated(node_id=nid, tier="comp", kind="domain", name=name),
            )
        append_event(
            db,
            project.id,
            ev.NodesMerged(
                source_ids=["comp_MMMMMMMM", "comp_NNNNNNNN"],
                dest_id="comp_MMMMMMMM",
                dest_name="Merged",
            ),
        )
        assert db.get(Node, "comp_MMMMMMMM").name == "Merged"
        assert db.get(Node, "comp_NNNNNNNN") is None


class TestEdgeEvents:
    def test_edge_created(self, db, project):
        _add_two_nodes(db, project.id, "comp_AAAAAAAA", "comp_BBBBBBBB")
        append_event(
            db,
            project.id,
            ev.EdgeCreated(
                edge_id="edge_EEEEEEEE",
                edge_type="dependency",
                source_id="comp_AAAAAAAA",
                target_id="comp_BBBBBBBB",
            ),
        )
        row = db.get(Edge, "edge_EEEEEEEE")
        assert row is not None
        assert row.edge_type == "dependency"

    def test_edge_deleted(self, db, project):
        _add_two_nodes(db, project.id, "comp_AAAAAAAA", "comp_BBBBBBBB")
        append_event(
            db,
            project.id,
            ev.EdgeCreated(
                edge_id="edge_EEEEEEEE",
                edge_type="dependency",
                source_id="comp_AAAAAAAA",
                target_id="comp_BBBBBBBB",
            ),
        )
        append_event(db, project.id, ev.EdgeDeleted(edge_id="edge_EEEEEEEE"))
        assert db.get(Edge, "edge_EEEEEEEE") is None


class TestFragmentEvents:
    def test_fragment_updated_creates_row_first_time(self, db, project):
        append_event(
            db,
            project.id,
            ev.NodeCreated(node_id="comp_FFFFFFFF", tier="comp", kind="domain", name="F"),
        )
        append_event(
            db,
            project.id,
            ev.FragmentUpdated(
                fragment_id="comp_FFFFFFFF_pubapi",
                owner_id="comp_FFFFFFFF",
                fragment_kind=ev.FragmentKind.PUBAPI,
                new_content="hello",
            ),
        )
        row = db.get(Fragment, "comp_FFFFFFFF_pubapi")
        assert row is not None
        assert row.content == "hello"

    def test_fragment_updated_overwrites(self, db, project):
        append_event(
            db,
            project.id,
            ev.NodeCreated(node_id="comp_FFFFFFFF", tier="comp", kind="domain", name="F"),
        )
        for content in ["first", "second"]:
            append_event(
                db,
                project.id,
                ev.FragmentUpdated(
                    fragment_id="comp_FFFFFFFF_pubapi",
                    owner_id="comp_FFFFFFFF",
                    fragment_kind=ev.FragmentKind.PUBAPI,
                    new_content=content,
                ),
            )
        assert db.get(Fragment, "comp_FFFFFFFF_pubapi").content == "second"

    def test_fragment_id_mismatch_rolls_back(self, db, project):
        append_event(
            db,
            project.id,
            ev.NodeCreated(node_id="comp_FFFFFFFF", tier="comp", kind="domain", name="F"),
        )
        with pytest.raises(ReducerError, match="does not match"):
            append_event(
                db,
                project.id,
                ev.FragmentUpdated(
                    fragment_id="comp_FFFFFFFF_deps",  # wrong kind for pubapi
                    owner_id="comp_FFFFFFFF",
                    fragment_kind=ev.FragmentKind.PUBAPI,
                    new_content="x",
                ),
            )


class TestDraftLifecycle:
    def test_draft_generated_then_edited(self, db, project):
        append_event(
            db,
            project.id,
            ev.NodeCreated(node_id="comp_DDDDDDDD", tier="comp", kind="domain", name="D"),
        )
        append_event(
            db,
            project.id,
            ev.DraftGenerated(
                draft_id="draft1",
                target_type="node",
                target_id="comp_DDDDDDDD",
                content="v1",
                batch_id="b",
            ),
        )
        append_event(
            db,
            project.id,
            ev.DraftEdited(draft_id="draft1", new_content="v2"),
        )
        row = db.get(Draft, "draft1")
        assert row.content == "v2"
        assert row.status == "pending"

    def test_draft_approved_writes_to_target(self, db, project):
        append_event(
            db,
            project.id,
            ev.NodeCreated(node_id="comp_DDDDDDDD", tier="comp", kind="domain", name="D"),
        )
        append_event(
            db,
            project.id,
            ev.DraftGenerated(
                draft_id="draft1",
                target_type="node",
                target_id="comp_DDDDDDDD",
                content="approved-content",
                batch_id="b",
            ),
        )
        append_event(db, project.id, ev.DraftApproved(draft_id="draft1"))
        assert db.get(Node, "comp_DDDDDDDD").content == "approved-content"
        assert db.get(Draft, "draft1").status == "approved"

    def test_draft_approved_on_cold_fragment(self, db, project):
        append_event(
            db,
            project.id,
            ev.NodeCreated(node_id="comp_DDDDDDDD", tier="comp", kind="domain", name="D"),
        )
        append_event(
            db,
            project.id,
            ev.DraftGenerated(
                draft_id="draft1",
                target_type="fragment",
                target_id="comp_DDDDDDDD_pubapi",
                content="first content",
                batch_id="b",
            ),
        )
        append_event(db, project.id, ev.DraftApproved(draft_id="draft1"))
        frag = db.get(Fragment, "comp_DDDDDDDD_pubapi")
        assert frag is not None
        assert frag.content == "first content"

    def test_draft_discarded(self, db, project):
        append_event(
            db,
            project.id,
            ev.NodeCreated(node_id="comp_DDDDDDDD", tier="comp", kind="domain", name="D"),
        )
        append_event(
            db,
            project.id,
            ev.DraftGenerated(
                draft_id="draft1",
                target_type="node",
                target_id="comp_DDDDDDDD",
                content="x",
                batch_id="b",
            ),
        )
        append_event(db, project.id, ev.DraftDiscarded(draft_id="draft1"))
        assert db.get(Draft, "draft1").status == "discarded"

    def test_cannot_edit_non_pending(self, db, project):
        append_event(
            db,
            project.id,
            ev.NodeCreated(node_id="comp_DDDDDDDD", tier="comp", kind="domain", name="D"),
        )
        append_event(
            db,
            project.id,
            ev.DraftGenerated(
                draft_id="draft1",
                target_type="node",
                target_id="comp_DDDDDDDD",
                content="x",
                batch_id="b",
            ),
        )
        append_event(db, project.id, ev.DraftApproved(draft_id="draft1"))
        with pytest.raises(ReducerError, match="cannot edit"):
            append_event(db, project.id, ev.DraftEdited(draft_id="draft1", new_content="y"))


# ── Rebuild correctness ──────────────────────────────────────────────


class TestRebuild:
    def test_canonical_sequence_rebuilds_identically(self, db, project, canonical_events):
        for event in canonical_events:
            append_event(db, project.id, event)
        incremental = _snapshot(db, project.id)

        rebuild_projections(db, project.id)
        after_rebuild = _snapshot(db, project.id)
        assert after_rebuild == incremental

    def test_rebuild_at_every_prefix(self, db, project, canonical_events):
        # For each prefix length, capture the incremental state after the
        # Nth event, then rebuild from zero up to that offset and compare.
        # Node IDs are globally unique (PK), so we can't use a second
        # project for cross-check — the prefix comparison is the one
        # that matters for correctness anyway.
        prefix_snapshots: list[dict] = []
        for event in canonical_events:
            append_event(db, project.id, event)
            db.flush()
            prefix_snapshots.append(_snapshot(db, project.id))

        for offset, expected in enumerate(prefix_snapshots, start=1):
            rebuild_projections(db, project.id, up_to_offset=offset)
            assert _snapshot(db, project.id) == expected, (
                f"rebuild at offset {offset} diverged from incremental state"
            )

    def test_rebuild_covers_phase_3_event_shapes(self, db, project, canonical_events):
        """Explicit assertions that sysarch / policy / subreqs / subresp
        / decomposition edge / sysarch-fragment events all round-trip
        through reducer + rebuild without loss.

        Guards against a regression where someone adds a new tier or
        edge type dispatch in the reducer and forgets to update the
        rebuild path. The ``test_rebuild_at_every_prefix`` test above
        catches divergence but not "this row was never written" —
        this test names each Phase 3 row explicitly.
        """
        from backend.models.node import Edge, Fragment, Node

        for event in canonical_events:
            append_event(db, project.id, event)
        rebuild_projections(db, project.id)

        # Sysarch singleton exists after rebuild
        sysarch_node = db.get(Node, "sysarch_SYSR1111")
        assert sysarch_node is not None
        assert sysarch_node.tier == "sysarch"
        assert sysarch_node.name == "System Architecture"

        # Policy node exists with its inline blob content
        policy_node = db.get(Node, "policy_POLY1111")
        assert policy_node is not None
        assert policy_node.tier == "policy"
        assert "<trigger>any LLM call</trigger>" in policy_node.content

        # Top-level resp (parent_id=None) and subresp (parent_id=comp) both exist
        top_resp = db.get(Node, "resp_TOPR1111")
        assert top_resp is not None
        assert top_resp.parent_id is None
        subresp = db.get(Node, "resp_SUBRP111")
        assert subresp is not None
        assert subresp.tier == "resp"
        assert subresp.parent_id == "comp_CMPA1111"

        # Subreqs node under comp_a
        subreqs_node = db.get(Node, "subreqs_SUBR1111")
        assert subreqs_node is not None
        assert subreqs_node.tier == "subreqs"
        assert subreqs_node.parent_id == "comp_CMPA1111"

        # Decomposition edges
        decomp_edges = (
            db.query(Edge)
            .filter(Edge.project_id == project.id, Edge.edge_type == "decomposition")
            .all()
        )
        decomp_pairs = {(e.source_id, e.target_id) for e in decomp_edges}
        assert ("resp_TOPR1111", "comp_CMPA1111") in decomp_pairs
        assert ("resp_TOPR1111", "resp_SUBRP111") in decomp_pairs

        # Sysarch techspec fragment landed
        frag = db.get(Fragment, "sysarch_SYSR1111_techspec")
        assert frag is not None
        assert frag.owner_id == "sysarch_SYSR1111"
        assert "Python + React" in frag.content


# ── Helpers ──────────────────────────────────────────────────────────


def _add_two_nodes(db, project_id: str, a: str, b: str) -> None:
    append_event(
        db,
        project_id,
        ev.NodeCreated(node_id=a, tier="comp", kind="domain", name=a),
    )
    append_event(
        db,
        project_id,
        ev.NodeCreated(node_id=b, tier="comp", kind="domain", name=b),
    )


def _snapshot(db, project_id: str) -> dict:
    """Deterministic dict representation of projection state."""

    def _node(n: Node) -> tuple:
        return (n.id, n.tier, n.kind, n.parent_id, n.name, n.display_order, n.content)

    def _edge(e: Edge) -> tuple:
        return (e.id, e.edge_type, e.source_id, e.target_id)

    def _frag(f: Fragment) -> tuple:
        return (f.id, f.owner_id, f.fragment_kind, f.content)

    def _draft(d: Draft) -> tuple:
        return (d.id, d.target_type, d.target_id, d.content, d.status, d.batch_id)

    return {
        "nodes": sorted(
            _node(n) for n in db.query(Node).filter(Node.project_id == project_id).all()
        ),
        "edges": sorted(
            _edge(e) for e in db.query(Edge).filter(Edge.project_id == project_id).all()
        ),
        "fragments": sorted(
            _frag(f) for f in db.query(Fragment).filter(Fragment.project_id == project_id).all()
        ),
        "drafts": sorted(
            _draft(d) for d in db.query(Draft).filter(Draft.project_id == project_id).all()
        ),
    }
