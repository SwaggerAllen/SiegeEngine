"""Tests for the Phase 12 walker backend: stale-node query + diffs.

``stale_nodes_at_offset`` + the :mod:`backend.graph.diff` helpers
are exercised against a project with staleness ledger rows and
fragment edits, to ensure the walker lists what it should and the
diff routes surface the right before/after bodies.
"""

from __future__ import annotations

from datetime import datetime

from backend.graph import events as ev
from backend.graph.diff import (
    fragment_diff,
    node_content_diff,
    node_diff_payload,
)
from backend.graph.fragments import FragmentKind, fragment_id
from backend.graph.queries import stale_nodes_at_offset
from backend.graph.reducer import append_event
from backend.models.node import StalenessLedger


def _mk_node(db, project_id, node_id, tier="comp", parent_id=None, name=None):
    append_event(
        db,
        project_id,
        ev.NodeCreated(
            node_id=node_id,
            tier=tier,
            kind="domain",
            parent_id=parent_id,
            name=name or node_id,
            display_order=0,
            content=f"{name or node_id} content.",
        ),
    )


def _mk_ledger(db, project_id, stale_id, source_id, reason, source_offset):
    db.add(
        StalenessLedger(
            project_id=project_id,
            stale_node_id=stale_id,
            source_node_id=source_id,
            source_offset=source_offset,
            reason=reason,
            created_at=datetime.utcnow(),
        )
    )
    db.flush()


class TestStaleNodesAtOffset:
    def test_returns_one_entry_per_stale_node_with_collapsed_reasons(self, db, project):
        _mk_node(db, project.id, "comp_AAAA1111")
        _mk_node(db, project.id, "comp_BBBB2222")
        _mk_node(db, project.id, "comp_CCCC3333")
        _mk_ledger(
            db,
            project.id,
            "comp_AAAA1111",
            "comp_BBBB2222",
            "content_changed",
            2,
        )
        _mk_ledger(
            db,
            project.id,
            "comp_AAAA1111",
            "comp_CCCC3333",
            "edge_created",
            3,
        )

        items = stale_nodes_at_offset(db, project.id, 10)
        assert len(items) == 1
        assert items[0].node_id == "comp_AAAA1111"
        assert items[0].reasons == ["content_changed", "edge_created"]
        assert items[0].is_destructive is False

    def test_marks_destructive_when_any_reason_is_structural(self, db, project):
        _mk_node(db, project.id, "comp_AAAA1111")
        _mk_node(db, project.id, "comp_BBBB2222")
        _mk_ledger(
            db,
            project.id,
            "comp_AAAA1111",
            "comp_BBBB2222",
            "structural_change",
            2,
        )
        items = stale_nodes_at_offset(db, project.id, 10)
        assert items[0].is_destructive is True

    def test_filters_markers_after_pinned_offset(self, db, project):
        _mk_node(db, project.id, "comp_AAAA1111")
        _mk_node(db, project.id, "comp_BBBB2222")
        _mk_ledger(
            db,
            project.id,
            "comp_AAAA1111",
            "comp_BBBB2222",
            "content_changed",
            5,
        )
        _mk_ledger(
            db,
            project.id,
            "comp_AAAA1111",
            "comp_BBBB2222",
            "edge_created",
            15,
        )
        # Pin at offset 10 — only the source_offset=5 marker is in
        # scope, not the later edge_created marker.
        items = stale_nodes_at_offset(db, project.id, 10)
        assert items[0].reasons == ["content_changed"]

    def test_excludes_fanin_tier(self, db, project):
        _mk_node(db, project.id, "comp_AAAA1111")
        _mk_node(db, project.id, "fanin_XXXX1111", tier="fanin", parent_id="comp_AAAA1111")
        _mk_ledger(
            db,
            project.id,
            "fanin_XXXX1111",
            "comp_AAAA1111",
            "content_changed",
            3,
        )
        items = stale_nodes_at_offset(db, project.id, 10)
        assert items == []

    def test_orders_upstream_tiers_first(self, db, project):
        _mk_node(db, project.id, "impl_II00AAAA", tier="impl", parent_id=None)
        _mk_node(db, project.id, "feat_FF00AAAA", tier="feat", parent_id=None)
        _mk_node(db, project.id, "comp_CC00AAAA", tier="comp", parent_id=None)
        source = "feat_SRCXXXXX"
        _mk_node(db, project.id, source, tier="feat", parent_id=None)
        for sid in ("impl_II00AAAA", "feat_FF00AAAA", "comp_CC00AAAA"):
            _mk_ledger(db, project.id, sid, source, "content_changed", 2)

        items = stale_nodes_at_offset(db, project.id, 10)
        tier_order = [it.tier for it in items]
        assert tier_order == ["feat", "comp", "impl"]

    def test_top_level_nodes_precede_sub_nodes(self, db, project):
        # Top-level comp + a subcomp under it; both stale.
        _mk_node(db, project.id, "comp_TOPXXXXX")
        _mk_node(
            db,
            project.id,
            "comp_SUBXXXXX",
            tier="comp",
            parent_id="comp_TOPXXXXX",
        )
        source = "feat_SRCXXXXX"
        _mk_node(db, project.id, source, tier="feat")
        _mk_ledger(db, project.id, "comp_TOPXXXXX", source, "content_changed", 1)
        _mk_ledger(db, project.id, "comp_SUBXXXXX", source, "content_changed", 1)

        items = stale_nodes_at_offset(db, project.id, 10)
        names = [it.node_id for it in items]
        assert names == ["comp_TOPXXXXX", "comp_SUBXXXXX"]

    def test_empty_ledger_returns_empty(self, db, project):
        assert stale_nodes_at_offset(db, project.id, 100) == []


class TestDiffHelpers:
    def test_node_content_diff_across_pin(self, db, project):
        _mk_node(db, project.id, "comp_XXX11111", name="Auth")
        # Content at offset 1: "Auth content." Now edit it.
        append_event(
            db,
            project.id,
            ev.NodeRenamed(node_id="comp_XXX11111", new_name="AuthService"),
        )
        db.flush()

        # Renames don't touch content. Use FragmentUpdated to cover
        # content scenarios separately; just verify the node's
        # content survives the pin-vs-live read path.
        diff = node_content_diff(db, project.id, "comp_XXX11111", 1)
        assert diff.before == "Auth content."
        assert diff.after == "Auth content."

    def test_fragment_diff_captures_edit(self, db, project):
        _mk_node(db, project.id, "comp_XXX11111", name="Auth")
        frag = fragment_id("comp_XXX11111", FragmentKind.TECHSPEC)
        append_event(
            db,
            project.id,
            ev.FragmentUpdated(
                fragment_id=frag,
                owner_id="comp_XXX11111",
                fragment_kind=FragmentKind.TECHSPEC,
                new_content="Original techspec.",
            ),
        )
        db.flush()
        pin = 2  # snapshot should capture "Original techspec."
        append_event(
            db,
            project.id,
            ev.FragmentUpdated(
                fragment_id=frag,
                owner_id="comp_XXX11111",
                fragment_kind=FragmentKind.TECHSPEC,
                new_content="Revised techspec.",
            ),
        )
        db.flush()

        diffs = fragment_diff(db, project.id, "comp_XXX11111", pin)
        assert len(diffs) == 1
        assert diffs[0].fragment_kind == FragmentKind.TECHSPEC
        assert diffs[0].before == "Original techspec."
        assert diffs[0].after == "Revised techspec."

    def test_fragment_diff_handles_newly_created_fragment(self, db, project):
        _mk_node(db, project.id, "comp_XXX11111", name="Auth")
        # Pin before any fragment lands.
        pin = 1
        frag = fragment_id("comp_XXX11111", FragmentKind.PUBAPI)
        append_event(
            db,
            project.id,
            ev.FragmentUpdated(
                fragment_id=frag,
                owner_id="comp_XXX11111",
                fragment_kind=FragmentKind.PUBAPI,
                new_content="NEW pubapi",
            ),
        )
        db.flush()

        diffs = fragment_diff(db, project.id, "comp_XXX11111", pin)
        assert len(diffs) == 1
        assert diffs[0].before is None
        assert diffs[0].after == "NEW pubapi"

    def test_node_diff_payload_bundles_content_plus_fragments(self, db, project):
        _mk_node(db, project.id, "comp_XXX11111", name="Auth")
        frag = fragment_id("comp_XXX11111", FragmentKind.TECHSPEC)
        append_event(
            db,
            project.id,
            ev.FragmentUpdated(
                fragment_id=frag,
                owner_id="comp_XXX11111",
                fragment_kind=FragmentKind.TECHSPEC,
                new_content="a",
            ),
        )
        db.flush()
        pin = 2
        append_event(
            db,
            project.id,
            ev.FragmentUpdated(
                fragment_id=frag,
                owner_id="comp_XXX11111",
                fragment_kind=FragmentKind.TECHSPEC,
                new_content="b",
            ),
        )
        db.flush()

        payload = node_diff_payload(db, project.id, "comp_XXX11111", pin)
        assert payload["node_content"]["before"] == "Auth content."
        assert payload["node_content"]["after"] == "Auth content."
        assert payload["fragments"][0]["before"] == "a"
        assert payload["fragments"][0]["after"] == "b"
