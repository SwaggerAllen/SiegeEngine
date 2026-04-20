"""Tests for the Phase 11 rename prose-rewrite handler.

Exercises ``v2.rename_rewrite`` directly — sets up a renamed node,
a consumer wired via a reference edge, and asserts the handler
rewrites both nodes' content + fragments before emitting
``NodeRenamed``.
"""

from __future__ import annotations

import asyncio

import pytest

from backend.graph import events as ev
from backend.graph.fragments import FragmentKind, fragment_id
from backend.graph.handlers import rename_rewrite as rr
from backend.graph.ids import Kind, mint
from backend.graph.reducer import append_event
from backend.models.graph_event import GraphEvent
from backend.models.node import Fragment, Node


class _NoCloseProxy:
    def __init__(self, s):
        self._s = s

    def __getattr__(self, k):
        return getattr(self._s, k)

    def close(self):
        return None


def _patch_session(monkeypatch, db):
    monkeypatch.setattr(rr, "SessionLocal", lambda: _NoCloseProxy(db))


def _make_node(db, project_id, nid=None, tier="comp", name="X", content=""):
    nid = nid or mint(db, Kind.COMP)
    append_event(
        db,
        project_id,
        ev.NodeCreated(
            node_id=nid,
            tier=tier,
            kind="domain",
            parent_id=None,
            name=name,
            content=content,
        ),
    )
    return nid


def _add_fragment(db, project_id, owner_id, kind, content):
    fid = fragment_id(owner_id, kind)
    append_event(
        db,
        project_id,
        ev.FragmentUpdated(
            fragment_id=fid,
            owner_id=owner_id,
            fragment_kind=kind,
            new_content=content,
        ),
    )
    return fid


def _add_edge(db, project_id, source_id, target_id, edge_type="reference"):
    eid = mint(db, Kind.EDGE)
    append_event(
        db,
        project_id,
        ev.EdgeCreated(
            edge_id=eid,
            edge_type=edge_type,
            source_id=source_id,
            target_id=target_id,
        ),
    )
    return eid


def _event_types(db, project_id):
    return [r.event_type for r in db.query(GraphEvent).filter_by(project_id=project_id).all()]


class TestRenameRewrite:
    def test_rewrites_renamed_node_content(self, db, project, monkeypatch):
        nid = _make_node(db, project.id, name="Billing", content="Billing handles invoices.")

        _patch_session(monkeypatch, db)
        asyncio.run(
            rr._handle(
                {
                    "project_id": project.id,
                    "node_id": nid,
                    "old_name": "Billing",
                    "new_name": "Payments",
                }
            )
        )

        node = db.get(Node, nid)
        assert node is not None
        assert node.name == "Payments"
        assert node.content == "Payments handles invoices."
        assert "NodeRenamed" in _event_types(db, project.id)

    def test_rewrites_owned_fragments_and_emits_events(self, db, project, monkeypatch):
        nid = _make_node(db, project.id, name="Billing")
        _add_fragment(
            db,
            project.id,
            nid,
            FragmentKind.TECHSPEC,
            "Billing owns the invoice pipeline.",
        )
        _add_fragment(
            db,
            project.id,
            nid,
            FragmentKind.PUBAPI,
            "Billing exposes create_invoice().",
        )
        # Snapshot existing events before the rewrite.
        pre_events = set(
            (r.event_type, r.offset)
            for r in db.query(GraphEvent).filter_by(project_id=project.id).all()
        )

        _patch_session(monkeypatch, db)
        asyncio.run(
            rr._handle(
                {
                    "project_id": project.id,
                    "node_id": nid,
                    "old_name": "Billing",
                    "new_name": "Payments",
                }
            )
        )

        # Both fragments got FragmentUpdated events.
        post_events = [
            (r.event_type, r.offset, r.payload)
            for r in db.query(GraphEvent).filter_by(project_id=project.id).all()
            if (r.event_type, r.offset) not in pre_events
        ]
        kinds_rewritten = {
            p.get("fragment_kind") for (t, _, p) in post_events if t == "FragmentUpdated"
        }
        assert kinds_rewritten == {"techspec", "pubapi"}

        # Fragment content reflects the rewrite.
        techspec = db.get(Fragment, fragment_id(nid, FragmentKind.TECHSPEC))
        assert techspec is not None and "Payments" in techspec.content
        assert "Billing" not in techspec.content

    def test_rewrites_direct_consumer_via_reference_edge(self, db, project, monkeypatch):
        renamed = _make_node(db, project.id, name="Billing", content="")
        consumer = _make_node(
            db,
            project.id,
            name="BillingDocs",
            content="BillingDocs describes Billing end-to-end.",
        )
        _add_edge(db, project.id, consumer, renamed, edge_type="reference")

        _patch_session(monkeypatch, db)
        asyncio.run(
            rr._handle(
                {
                    "project_id": project.id,
                    "node_id": renamed,
                    "old_name": "Billing",
                    "new_name": "Payments",
                }
            )
        )

        c = db.get(Node, consumer)
        assert c is not None
        # Word-boundary rewrite: "Billing" → "Payments", but
        # "BillingDocs" stays intact because of the word boundary.
        assert c.content == "BillingDocs describes Payments end-to-end."

    def test_skips_nodes_without_an_edge_to_renamed(self, db, project, monkeypatch):
        renamed = _make_node(db, project.id, name="Billing", content="")
        unrelated = _make_node(
            db,
            project.id,
            name="Other",
            content="Other also mentions Billing, but has no edge.",
        )

        _patch_session(monkeypatch, db)
        asyncio.run(
            rr._handle(
                {
                    "project_id": project.id,
                    "node_id": renamed,
                    "old_name": "Billing",
                    "new_name": "Payments",
                }
            )
        )

        u = db.get(Node, unrelated)
        assert u is not None
        # No edge → no rewrite scope; text untouched.
        assert u.content == "Other also mentions Billing, but has no edge."

    def test_word_boundary_avoids_false_positives(self, db, project, monkeypatch):
        nid = _make_node(
            db,
            project.id,
            name="Bill",
            content="Bill owns billing. Billing and Bill-boards are different.",
        )
        _patch_session(monkeypatch, db)
        asyncio.run(
            rr._handle(
                {
                    "project_id": project.id,
                    "node_id": nid,
                    "old_name": "Bill",
                    "new_name": "Invoice",
                }
            )
        )
        node = db.get(Node, nid)
        assert node is not None
        # "Bill" → "Invoice"; "billing" and "Billing" and
        # "Bill-boards" unchanged (different word boundaries
        # around dash vs. "ing" suffix).
        assert "Invoice owns billing" in node.content
        assert "Billing" in node.content
        # "Bill-boards" — Bill matches at \b so it DOES rewrite
        # before the hyphen. That's a known limitation of the
        # word-boundary heuristic; document it by asserting.
        assert "Invoice-boards" in node.content

    def test_missing_node_is_a_warning_not_a_raise(self, db, project, monkeypatch):
        _patch_session(monkeypatch, db)
        # No node_id match — handler logs + returns cleanly.
        asyncio.run(
            rr._handle(
                {
                    "project_id": project.id,
                    "node_id": "comp_DEADBEEF",
                    "old_name": "X",
                    "new_name": "Y",
                }
            )
        )
        # No events emitted.
        assert all(t != "NodeRenamed" for t in _event_types(db, project.id))

    def test_rejects_payload_missing_fields(self):
        with pytest.raises(ValueError, match="missing"):
            asyncio.run(rr._handle({}))

    def test_consumer_via_dependency_edge_also_rewritten(self, db, project, monkeypatch):
        renamed = _make_node(db, project.id, name="Billing", content="")
        dep_consumer = _make_node(
            db,
            project.id,
            name="Frontend",
            content="Frontend depends on Billing's pubapi.",
        )
        _add_edge(db, project.id, dep_consumer, renamed, edge_type="dependency")

        _patch_session(monkeypatch, db)
        asyncio.run(
            rr._handle(
                {
                    "project_id": project.id,
                    "node_id": renamed,
                    "old_name": "Billing",
                    "new_name": "Payments",
                }
            )
        )
        c = db.get(Node, dep_consumer)
        assert c is not None
        assert "Payments" in c.content and "Billing" not in c.content
