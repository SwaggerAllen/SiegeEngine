"""Phase 9 — StalenessLedger projection + query helpers.

Covers the ledger table itself (insert/clear round-trip, the unique
constraint on (project, stale, source, reason)), the three query
helpers (is_stale, stale_dependents_of, staleness_entries_for), and
the rebuild_projections invariant: replay wipes the ledger back to
empty because staleness is derived state, not event-sourced.
"""

from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy.exc import IntegrityError

from backend.graph import events as ev
from backend.graph.queries import is_stale, stale_dependents_of, staleness_entries_for
from backend.graph.reducer import append_event, rebuild_projections
from backend.models.node import Node, StalenessLedger


def _mk_nodes(db, project_id: str, ids: list[str]) -> None:
    """Append NodeCreated events for a list of comp-tier node ids."""
    for nid in ids:
        append_event(
            db,
            project_id,
            ev.NodeCreated(node_id=nid, tier="comp", kind="domain", name=nid),
        )


class TestLedgerSchema:
    def test_insert_and_round_trip(self, db, project):
        _mk_nodes(db, project.id, ["comp_AAAA1111", "comp_BBBB2222"])
        db.add(
            StalenessLedger(
                project_id=project.id,
                stale_node_id="comp_AAAA1111",
                source_node_id="comp_BBBB2222",
                source_offset=42,
                reason="content_changed",
                created_at=datetime.utcnow(),
            )
        )
        db.flush()

        rows = db.query(StalenessLedger).all()
        assert len(rows) == 1
        assert rows[0].stale_node_id == "comp_AAAA1111"
        assert rows[0].source_node_id == "comp_BBBB2222"
        assert rows[0].source_offset == 42
        assert rows[0].reason == "content_changed"

    def test_unique_constraint_on_triple(self, db, project):
        _mk_nodes(db, project.id, ["comp_AAAA1111", "comp_BBBB2222"])
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
        db.add(
            StalenessLedger(
                project_id=project.id,
                stale_node_id="comp_AAAA1111",
                source_node_id="comp_BBBB2222",
                source_offset=2,
                reason="content_changed",
            )
        )
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()

    def test_different_reasons_coexist(self, db, project):
        _mk_nodes(db, project.id, ["comp_AAAA1111", "comp_BBBB2222"])
        db.add(
            StalenessLedger(
                project_id=project.id,
                stale_node_id="comp_AAAA1111",
                source_node_id="comp_BBBB2222",
                source_offset=1,
                reason="content_changed",
            )
        )
        db.add(
            StalenessLedger(
                project_id=project.id,
                stale_node_id="comp_AAAA1111",
                source_node_id="comp_BBBB2222",
                source_offset=1,
                reason="structural_change",
            )
        )
        db.flush()
        assert db.query(StalenessLedger).count() == 2

    def test_reason_check_constraint_rejects_unknown(self, db, project):
        _mk_nodes(db, project.id, ["comp_AAAA1111", "comp_BBBB2222"])
        db.add(
            StalenessLedger(
                project_id=project.id,
                stale_node_id="comp_AAAA1111",
                source_node_id="comp_BBBB2222",
                source_offset=1,
                reason="bogus",
            )
        )
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()


class TestQueryHelpers:
    def test_is_stale_false_when_no_rows(self, db, project):
        _mk_nodes(db, project.id, ["comp_AAAA1111"])
        assert is_stale(db, project.id, "comp_AAAA1111") is False

    def test_is_stale_true_with_any_row(self, db, project):
        _mk_nodes(db, project.id, ["comp_AAAA1111", "comp_BBBB2222"])
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
        assert is_stale(db, project.id, "comp_AAAA1111") is True

    def test_is_stale_project_scoped(self, db, project):
        _mk_nodes(db, project.id, ["comp_AAAA1111", "comp_BBBB2222"])
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
        assert is_stale(db, "other-project", "comp_AAAA1111") is False

    def test_stale_dependents_of_returns_distinct_dependents(self, db, project):
        _mk_nodes(
            db,
            project.id,
            ["comp_AAAA1111", "comp_BBBB2222", "comp_CCCC3333", "comp_DDDD4444"],
        )
        # Two reasons against the same dependent — must collapse to one.
        db.add_all(
            [
                StalenessLedger(
                    project_id=project.id,
                    stale_node_id="comp_AAAA1111",
                    source_node_id="comp_DDDD4444",
                    source_offset=1,
                    reason="content_changed",
                ),
                StalenessLedger(
                    project_id=project.id,
                    stale_node_id="comp_AAAA1111",
                    source_node_id="comp_DDDD4444",
                    source_offset=1,
                    reason="structural_change",
                ),
                StalenessLedger(
                    project_id=project.id,
                    stale_node_id="comp_BBBB2222",
                    source_node_id="comp_DDDD4444",
                    source_offset=1,
                    reason="content_changed",
                ),
                StalenessLedger(
                    project_id=project.id,
                    stale_node_id="comp_CCCC3333",
                    source_node_id="comp_AAAA1111",
                    source_offset=1,
                    reason="content_changed",
                ),
            ]
        )
        db.flush()
        dependents = stale_dependents_of(db, project.id, "comp_DDDD4444")
        assert sorted(dependents) == ["comp_AAAA1111", "comp_BBBB2222"]

    def test_staleness_entries_for_returns_all_rows(self, db, project):
        _mk_nodes(db, project.id, ["comp_AAAA1111", "comp_BBBB2222", "comp_CCCC3333"])
        db.add_all(
            [
                StalenessLedger(
                    project_id=project.id,
                    stale_node_id="comp_AAAA1111",
                    source_node_id="comp_BBBB2222",
                    source_offset=1,
                    reason="content_changed",
                ),
                StalenessLedger(
                    project_id=project.id,
                    stale_node_id="comp_AAAA1111",
                    source_node_id="comp_CCCC3333",
                    source_offset=2,
                    reason="structural_change",
                ),
            ]
        )
        db.flush()
        rows = staleness_entries_for(db, project.id, "comp_AAAA1111")
        assert len(rows) == 2
        pairs = sorted((r.source_node_id, r.reason) for r in rows)
        assert pairs == [
            ("comp_BBBB2222", "content_changed"),
            ("comp_CCCC3333", "structural_change"),
        ]


class TestRebuildWipesLedger:
    """Replay from the event log must wipe the ledger.

    Staleness is derived state, not primary state — a freshly-rebuilt
    projection has an empty ledger because nothing has happened after
    rebuild yet. This preserves the canonical-sequence replay identity
    invariant: rebuilding from the log doesn't need to know anything
    about staleness because the log itself doesn't carry staleness
    events.
    """

    def test_rebuild_wipes_ledger_entries(self, db, project):
        # Create two nodes with an inbound edge so a content commit
        # produces a real staleness mark via fanout.
        append_event(
            db,
            project.id,
            ev.NodeCreated(
                node_id="comp_SRC00001",
                tier="comp",
                kind="domain",
                name="Src",
            ),
        )
        append_event(
            db,
            project.id,
            ev.NodeCreated(
                node_id="comp_DST00001",
                tier="comp",
                kind="domain",
                name="Dst",
            ),
        )
        # src --dependency--> dst
        append_event(
            db,
            project.id,
            ev.EdgeCreated(
                edge_id="edge_E0000001",
                edge_type="dependency",
                source_id="comp_SRC00001",
                target_id="comp_DST00001",
            ),
        )
        # Commit new content to dst — src becomes stale.
        frag_id = "comp_DST00001_pubapi"
        append_event(
            db,
            project.id,
            ev.FragmentUpdated(
                fragment_id=frag_id,
                owner_id="comp_DST00001",
                fragment_kind=ev.FragmentKind.PUBAPI,
                new_content="hello",
            ),
        )
        db.flush()

        before = db.query(StalenessLedger).filter_by(project_id=project.id).count()
        assert before >= 1, "fanout should have produced at least one mark"

        rebuild_projections(db, project.id)

        after = db.query(StalenessLedger).filter_by(project_id=project.id).count()
        assert after == 0

        # Nodes survived the rebuild (primary projection intact).
        assert db.get(Node, "comp_SRC00001") is not None
        assert db.get(Node, "comp_DST00001") is not None
