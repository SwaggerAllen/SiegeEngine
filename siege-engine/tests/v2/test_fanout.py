"""Phase 9 — central staleness fanout dispatcher.

Tests the classification rules, destructive-op halt, auto-enqueue
behavior, and the fragment_changed helper. These tests exercise
``append_event`` end-to-end because the fanout runs as part of it,
and rely on the StalenessLedger projection + the job queue for
observation.
"""

from __future__ import annotations

from sqlalchemy import select

from backend.graph import events as ev
from backend.graph.fanout import (
    StalenessChanges,
    apply_staleness_changes,
    compute_staleness_changes,
    is_destructive,
    regen_job_for_node,
)
from backend.graph.fragments import fragment_changed
from backend.graph.reducer import append_event
from backend.models.job import Job
from backend.models.node import Node, StalenessLedger


def _queued_job_types(db, project_id: str) -> list[str]:
    """Return every queued/running job's type filtered to this project."""
    rows = db.execute(select(Job).where(Job.status == "queued")).scalars().all()
    return sorted(j.job_type for j in rows if (j.payload or {}).get("project_id") == project_id)


def _count_stale(db, project_id: str) -> int:
    return db.query(StalenessLedger).filter(StalenessLedger.project_id == project_id).count()


# ── is_destructive classifier ────────────────────────────────────────


class TestIsDestructive:
    def test_structural_ops_are_destructive(self):
        assert is_destructive(ev.NodeDeleted(node_id="comp_XXXXXXXX"))
        assert is_destructive(ev.NodePromoted(node_id="comp_XXXXXXXX", new_tier="comp"))
        assert is_destructive(ev.NodeDemoted(node_id="comp_XXXXXXXX", new_tier="comp"))
        assert is_destructive(ev.NodeReparented(node_id="comp_XXXXXXXX", new_parent_id=None))
        assert is_destructive(
            ev.NodesMerged(
                source_ids=["comp_AAAAAAAA", "comp_BBBBBBBB"],
                dest_id="comp_AAAAAAAA",
                dest_name="merged",
            )
        )
        assert is_destructive(
            ev.NodeSplit(
                source_id="comp_AAAAAAAA",
                dest_ids=["comp_BBBBBBBB", "comp_CCCCCCCC"],
                dest_names=["x", "y"],
            )
        )

    def test_non_structural_ops_are_not_destructive(self):
        assert not is_destructive(ev.NodeRenamed(node_id="comp_XXXXXXXX", new_name="x"))
        assert not is_destructive(ev.DraftApproved(draft_id="draft_1"))
        assert not is_destructive(ev.DraftDiscarded(draft_id="draft_1"))
        assert not is_destructive(
            ev.EdgeCreated(
                edge_id="edge_EEEEEEE1",
                edge_type="dependency",
                source_id="comp_AAAAAAAA",
                target_id="comp_BBBBBBBB",
            )
        )


# ── fragment_changed helper ──────────────────────────────────────────


class TestFragmentChanged:
    def test_identical_returns_false(self):
        assert fragment_changed("hello", "hello") is False

    def test_whitespace_only_diff_returns_false(self):
        assert fragment_changed("hello", "  hello  \n") is False
        assert fragment_changed("\nhello\n", "hello") is False

    def test_material_diff_returns_true(self):
        assert fragment_changed("hello", "hello world") is True

    def test_none_and_empty_treated_equivalently(self):
        assert fragment_changed("", "") is False
        assert fragment_changed(None, "") is False  # type: ignore[arg-type]
        assert fragment_changed("", None) is False  # type: ignore[arg-type]
        assert fragment_changed(None, "x") is True  # type: ignore[arg-type]


# ── Content-commit fanout (inbound edge walk) ────────────────────────


class TestContentCommitFanout:
    """FragmentUpdated / FanInContentUpdated / DraftApproved on a node
    should mark every inbound-edge source as stale w.r.t. that node."""

    def test_fragment_update_marks_inbound_sources_stale(self, db, project):
        # src --dependency--> dst
        append_event(
            db,
            project.id,
            ev.NodeCreated(node_id="comp_SRC00001", tier="comp", kind="domain", name="Src"),
        )
        append_event(
            db,
            project.id,
            ev.NodeCreated(node_id="comp_DST00001", tier="comp", kind="domain", name="Dst"),
        )
        append_event(
            db,
            project.id,
            ev.EdgeCreated(
                edge_id="edge_DEP00001",
                edge_type="dependency",
                source_id="comp_SRC00001",
                target_id="comp_DST00001",
            ),
        )
        # Baseline: edge creation itself already staled src w.r.t. dst
        # (via the edge_created reason). Clear for a focused fragment
        # assertion.
        db.query(StalenessLedger).filter_by(project_id=project.id).delete()
        db.flush()

        frag_id = "comp_DST00001_pubapi"
        append_event(
            db,
            project.id,
            ev.FragmentUpdated(
                fragment_id=frag_id,
                owner_id="comp_DST00001",
                fragment_kind=ev.FragmentKind.PUBAPI,
                new_content="new content",
            ),
        )
        db.flush()

        rows = (
            db.query(StalenessLedger)
            .filter_by(project_id=project.id, stale_node_id="comp_SRC00001")
            .all()
        )
        assert len(rows) == 1
        assert rows[0].source_node_id == "comp_DST00001"
        assert rows[0].reason == "fragment_changed"

    def test_content_commit_on_stale_node_clears_its_own_entries(self, db, project):
        """Source regenerating clears its staleness w.r.t. every upstream.

        Not testing the "stale node commits new content" full cycle —
        that's integration territory. This verifies the
        `_fanout_content_change` clear half by inserting a ledger row
        directly and then firing a content event on that same stale
        node.
        """
        append_event(
            db,
            project.id,
            ev.NodeCreated(node_id="comp_AAAA1111", tier="comp", kind="domain", name="A"),
        )
        append_event(
            db,
            project.id,
            ev.NodeCreated(node_id="comp_BBBB2222", tier="comp", kind="domain", name="B"),
        )
        db.add(
            StalenessLedger(
                project_id=project.id,
                stale_node_id="comp_AAAA1111",
                source_node_id="comp_BBBB2222",
                source_offset=1,
                reason="content_changed",
            )
        )
        db.flush()
        assert _count_stale(db, project.id) == 1

        # Fire a content commit on comp_AAAA1111 (the stale node):
        # its ledger entries clear. No inbound edges → no new marks.
        frag_id = "comp_AAAA1111_pubapi"
        append_event(
            db,
            project.id,
            ev.FragmentUpdated(
                fragment_id=frag_id,
                owner_id="comp_AAAA1111",
                fragment_kind=ev.FragmentKind.PUBAPI,
                new_content="caught up",
            ),
        )
        db.flush()
        assert _count_stale(db, project.id) == 0

    def test_no_inbound_edges_no_marks(self, db, project):
        append_event(
            db,
            project.id,
            ev.NodeCreated(node_id="comp_SXNKYX01", tier="comp", kind="domain", name="Lonely"),
        )
        frag_id = "comp_SXNKYX01_pubapi"
        append_event(
            db,
            project.id,
            ev.FragmentUpdated(
                fragment_id=frag_id,
                owner_id="comp_SXNKYX01",
                fragment_kind=ev.FragmentKind.PUBAPI,
                new_content="hi",
            ),
        )
        assert _count_stale(db, project.id) == 0


# ── Edge-change fanout ───────────────────────────────────────────────


class TestEdgeCreatedFanout:
    def test_edge_created_marks_source_stale(self, db, project):
        append_event(
            db,
            project.id,
            ev.NodeCreated(node_id="comp_SRC00002", tier="comp", kind="domain", name="Src"),
        )
        append_event(
            db,
            project.id,
            ev.NodeCreated(node_id="comp_TGT00002", tier="comp", kind="domain", name="Tgt"),
        )
        append_event(
            db,
            project.id,
            ev.EdgeCreated(
                edge_id="edge_DEPD0002",
                edge_type="dependency",
                source_id="comp_SRC00002",
                target_id="comp_TGT00002",
            ),
        )
        rows = db.query(StalenessLedger).filter_by(project_id=project.id).all()
        assert len(rows) == 1
        assert rows[0].stale_node_id == "comp_SRC00002"
        assert rows[0].source_node_id == "comp_TGT00002"
        assert rows[0].reason == "edge_created"


# ── Destructive structural fanout + auto-enqueue halt ────────────────


class TestDestructiveStructural:
    def test_node_deleted_marks_neighbors_with_structural_change(self, db, project):
        # A --dependency--> B; delete B, A gets a structural_change mark.
        append_event(
            db,
            project.id,
            ev.NodeCreated(node_id="comp_SRC00003", tier="comp", kind="domain", name="Src"),
        )
        append_event(
            db,
            project.id,
            ev.NodeCreated(node_id="comp_TGT00003", tier="comp", kind="domain", name="Tgt"),
        )
        append_event(
            db,
            project.id,
            ev.EdgeCreated(
                edge_id="edge_DEPD0003",
                edge_type="dependency",
                source_id="comp_SRC00003",
                target_id="comp_TGT00003",
            ),
        )
        # Drop any prior marks to focus the assertion.
        db.query(StalenessLedger).filter_by(project_id=project.id).delete()
        db.flush()

        append_event(
            db,
            project.id,
            ev.NodeDeleted(node_id="comp_TGT00003"),
        )
        rows = db.query(StalenessLedger).filter_by(project_id=project.id).all()
        # SRC was the edge's source so it's marked as stale w.r.t.
        # the deleted node.
        stale_ids = {(r.stale_node_id, r.reason) for r in rows}
        assert ("comp_SRC00003", "structural_change") in stale_ids

    def test_destructive_trigger_halts_auto_enqueue(self, db, project):
        """Deleting a node must not auto-enqueue a regen for neighbors.

        The ledger entry stays for UI visibility, but the user kicks
        regen manually after reviewing what the destructive change
        means.
        """
        # A (top-level comp) --dependency--> B. B is the one being
        # deleted. A is top-level so its tier maps to
        # ``v2.generate_comparch`` — if fanout didn't halt the cascade,
        # we'd see that job queued.
        append_event(
            db,
            project.id,
            ev.NodeCreated(node_id="comp_SRCTPK01", tier="comp", kind="domain", name="Src"),
        )
        append_event(
            db,
            project.id,
            ev.NodeCreated(node_id="comp_TGTTPK01", tier="comp", kind="domain", name="Tgt"),
        )
        append_event(
            db,
            project.id,
            ev.EdgeCreated(
                edge_id="edge_DEPD9999",
                edge_type="dependency",
                source_id="comp_SRCTPK01",
                target_id="comp_TGTTPK01",
            ),
        )
        # Drain any jobs that fired from the non-destructive edge mark.
        db.query(Job).delete()
        db.flush()

        append_event(db, project.id, ev.NodeDeleted(node_id="comp_TGTTPK01"))
        db.flush()

        # The SRC node got a structural_change mark.
        assert _count_stale(db, project.id) >= 1
        # But no comparch regen job was enqueued for it.
        assert "v2.generate_comparch" not in _queued_job_types(db, project.id)


# ── Auto-enqueue on non-destructive triggers ─────────────────────────


class TestAutoEnqueue:
    def test_fragment_commit_on_dep_target_enqueues_regen_for_source(self, db, project):
        # src is top-level comp (has a comparch regen job). Fragment
        # commit on dst should fanout-enqueue src's comparch regen.
        append_event(
            db,
            project.id,
            ev.NodeCreated(node_id="comp_SRCTPK02", tier="comp", kind="domain", name="Src"),
        )
        append_event(
            db,
            project.id,
            ev.NodeCreated(node_id="comp_TGTTPK02", tier="comp", kind="domain", name="Tgt"),
        )
        append_event(
            db,
            project.id,
            ev.EdgeCreated(
                edge_id="edge_DEPD8888",
                edge_type="dependency",
                source_id="comp_SRCTPK02",
                target_id="comp_TGTTPK02",
            ),
        )
        # Drain jobs from the edge_created mark.
        db.query(Job).delete()
        db.flush()

        frag_id = "comp_TGTTPK02_pubapi"
        append_event(
            db,
            project.id,
            ev.FragmentUpdated(
                fragment_id=frag_id,
                owner_id="comp_TGTTPK02",
                fragment_kind=ev.FragmentKind.PUBAPI,
                new_content="new",
            ),
        )
        db.flush()

        job_types = _queued_job_types(db, project.id)
        assert "v2.generate_comparch" in job_types


# ── regen_job_for_node mapping ───────────────────────────────────────


class TestRegenJobForNode:
    def test_top_level_comp_maps_to_comparch(self):
        node = Node(
            id="comp_AAAAAAA1",
            project_id="p",
            tier="comp",
            kind="domain",
            parent_id=None,
            name="A",
        )
        result = regen_job_for_node("p", node)
        assert result is not None
        job_type, payload = result
        assert job_type == "v2.generate_comparch"
        assert payload == {"project_id": "p", "component_id": "comp_AAAAAAA1", "feedback": None}

    def test_sub_comp_maps_to_subcomparch(self):
        node = Node(
            id="comp_BBBBBBB1",
            project_id="p",
            tier="comp",
            kind="domain",
            parent_id="comp_AAAAAAA1",
            name="B",
        )
        result = regen_job_for_node("p", node)
        assert result is not None
        job_type, payload = result
        assert job_type == "v2.generate_subcomparch"
        assert payload == {"project_id": "p", "component_id": "comp_BBBBBBB1", "feedback": None}

    def test_fanin_maps_with_owner_comp_id(self):
        node = Node(
            id="fanin_FFFFFF01",
            project_id="p",
            tier="fanin",
            kind="domain",
            parent_id="comp_OWNER001",
            name="Owner fan-in",
        )
        result = regen_job_for_node("p", node)
        assert result is not None
        job_type, payload = result
        assert job_type == "v2.generate_fanin"
        assert payload == {"project_id": "p", "owner_comp_id": "comp_OWNER001"}

    def test_unminted_tiers_return_none(self):
        # feat / resp / policy / vocab / plan / manifest regenerate
        # via their owning bootstrap tier, not independently.
        for tier in ("feat", "resp", "policy", "vocab", "plan", "manifest"):
            node = Node(
                id=f"{tier}_ZZZZZZZ1",
                project_id="p",
                tier=tier,
                kind="domain",
                parent_id=None,
                name="x",
            )
            assert regen_job_for_node("p", node) is None, f"{tier} should return None"


# ── apply_staleness_changes idempotency ──────────────────────────────


class TestApplyChanges:
    def test_re_applying_same_mark_bumps_offset(self, db, project):
        from backend.graph.fanout import _Mark

        append_event(
            db,
            project.id,
            ev.NodeCreated(node_id="comp_STKX0001", tier="comp", kind="domain", name="A"),
        )
        append_event(
            db,
            project.id,
            ev.NodeCreated(node_id="comp_STKX0002", tier="comp", kind="domain", name="B"),
        )
        changes = StalenessChanges(
            marks=[
                _Mark(
                    stale_node_id="comp_STKX0001",
                    source_node_id="comp_STKX0002",
                    source_offset=5,
                    reason="content_changed",
                )
            ]
        )
        apply_staleness_changes(db, project.id, changes)
        db.flush()

        # Re-apply the same mark with a higher offset.
        changes2 = StalenessChanges(
            marks=[
                _Mark(
                    stale_node_id="comp_STKX0001",
                    source_node_id="comp_STKX0002",
                    source_offset=9,
                    reason="content_changed",
                )
            ]
        )
        apply_staleness_changes(db, project.id, changes2)
        db.flush()

        rows = db.query(StalenessLedger).filter_by(project_id=project.id).all()
        assert len(rows) == 1
        assert rows[0].source_offset == 9

    def test_clear_before_mark_is_no_op(self, db, project):
        from backend.graph.fanout import _Clear

        append_event(
            db,
            project.id,
            ev.NodeCreated(node_id="comp_STKX0003", tier="comp", kind="domain", name="A"),
        )
        append_event(
            db,
            project.id,
            ev.NodeCreated(node_id="comp_STKX0004", tier="comp", kind="domain", name="B"),
        )
        changes = StalenessChanges(
            clears=[_Clear(stale_node_id="comp_STKX0003", source_node_id="comp_STKX0004")]
        )
        # Shouldn't raise even though there's nothing to clear.
        apply_staleness_changes(db, project.id, changes)
        db.flush()
        assert _count_stale(db, project.id) == 0


# ── compute_staleness_changes direct ─────────────────────────────────


class TestComputeChangesDirect:
    def test_returns_empty_on_unknown_event_type(self, db, project):
        # NodeCreated has no fanout (new node has no inbound edges
        # and isn't a destructive op).
        trigger = ev.NodeCreated(
            node_id="comp_NEWMNT01",
            tier="comp",
            kind="domain",
            name="New",
        )
        changes = compute_staleness_changes(db, project.id, trigger, 1)
        assert changes.marks == []
        assert changes.clears == []

    def test_edge_deleted_is_a_noop(self, db, project):
        # EdgeDeleted carries only edge_id; by the time fanout runs
        # the row is gone, so MVP skips fanout for EdgeDeleted.
        append_event(
            db,
            project.id,
            ev.NodeCreated(node_id="comp_EDGD0001", tier="comp", kind="domain", name="A"),
        )
        append_event(
            db,
            project.id,
            ev.NodeCreated(node_id="comp_EDGD0002", tier="comp", kind="domain", name="B"),
        )
        append_event(
            db,
            project.id,
            ev.EdgeCreated(
                edge_id="edge_EDGD0003",
                edge_type="dependency",
                source_id="comp_EDGD0001",
                target_id="comp_EDGD0002",
            ),
        )
        db.query(StalenessLedger).filter_by(project_id=project.id).delete()
        db.flush()

        trigger = ev.EdgeDeleted(edge_id="edge_EDGD0003")
        changes = compute_staleness_changes(db, project.id, trigger, 10)
        assert changes.marks == []
        assert changes.clears == []
