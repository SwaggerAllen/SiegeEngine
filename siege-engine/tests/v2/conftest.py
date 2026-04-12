"""Fixtures for v2 foundation tests."""

from __future__ import annotations

import os

import pytest

from backend.graph import events as ev
from backend.graph.reducer import append_event

# Gate the background pipeline worker loop for every v2 test — we
# drive handlers inline (via asyncio.run) and don't want a real
# worker racing against fixture commits.
os.environ.setdefault("SIEGE_DISABLE_WORKER_LOOP", "1")


@pytest.fixture()
def canonical_events() -> list[ev._EventBase]:
    """A self-consistent event sequence that touches every event type.

    The sequence is designed so it can be replayed end-to-end without
    any reducer errors. Reused by reducer and debug-route tests.
    """
    feat_id = "feat_FEAT1111"
    resp_id = "resp_RESP1111"
    comp_a = "comp_CMPA1111"
    comp_b = "comp_CMPB1111"
    comp_c = "comp_CMPC1111"
    sub_id = "comp_SUBX1111"
    edge_dep = "edge_EDGED111"
    edge_dom = "edge_EDGEM111"
    frag_id = f"{comp_a}_pubapi"

    return [
        ev.NodeCreated(node_id=feat_id, tier="feat", kind="domain", name="Identity"),
        ev.NodeCreated(
            node_id=resp_id,
            tier="resp",
            kind="domain",
            parent_id=feat_id,
            name="Authenticate users",
        ),
        ev.NodeCreated(
            node_id=comp_a,
            tier="comp",
            kind="domain",
            parent_id=resp_id,
            name="IdentityService",
        ),
        ev.NodeCreated(
            node_id=comp_b,
            tier="comp",
            kind="presentational",
            parent_id=resp_id,
            name="LoginView",
        ),
        ev.NodeCreated(
            node_id=comp_c,
            tier="comp",
            kind="domain",
            parent_id=resp_id,
            name="AuxiliaryThing",
        ),
        ev.NodeRenamed(node_id=comp_a, new_name="AuthService"),
        ev.NodeCreated(
            node_id=sub_id,
            tier="comp",
            kind="domain",
            parent_id=comp_a,
            name="TokenStore",
        ),
        ev.NodeReparented(node_id=sub_id, new_parent_id=comp_a),
        ev.NodePromoted(node_id=sub_id, new_tier="comp"),
        ev.NodeDemoted(node_id=sub_id, new_tier="comp"),
        ev.EdgeCreated(
            edge_id=edge_dep,
            edge_type="dependency",
            source_id=comp_b,
            target_id=comp_a,
        ),
        ev.EdgeCreated(
            edge_id=edge_dom,
            edge_type="domain_parent",
            source_id=comp_b,
            target_id=comp_a,
        ),
        ev.FragmentUpdated(
            fragment_id=frag_id,
            owner_id=comp_a,
            fragment_kind=ev.FragmentKind.PUBAPI,
            new_content="initial pubapi",
        ),
        ev.DraftGenerated(
            draft_id="draft_node_01",
            target_type="node",
            target_id=comp_a,
            content="new AuthService content",
            batch_id="batch_01",
        ),
        ev.DraftEdited(
            draft_id="draft_node_01",
            new_content="revised AuthService content",
        ),
        ev.DraftApproved(draft_id="draft_node_01"),
        ev.DraftGenerated(
            draft_id="draft_frag_01",
            target_type="fragment",
            target_id=frag_id,
            content="updated pubapi via draft",
            batch_id="batch_01",
        ),
        ev.DraftApproved(draft_id="draft_frag_01"),
        ev.DraftGenerated(
            draft_id="draft_discard",
            target_type="node",
            target_id=comp_b,
            content="to-be-discarded",
            batch_id="batch_01",
        ),
        ev.DraftDiscarded(draft_id="draft_discard"),
        ev.EdgeDeleted(edge_id=edge_dom),
        ev.NodesMerged(
            source_ids=[comp_a, comp_c],
            dest_id=comp_a,
            dest_name="AuthService",
        ),
        ev.NodeDeleted(node_id=sub_id),
        ev.ViewRecorded(user_id="user_01", batch_id="batch_01", event_offset=10),
    ]


@pytest.fixture()
def populated_project(db, project, canonical_events):
    """Append the canonical event sequence into ``project`` and return it."""
    for event in canonical_events:
        append_event(db, project.id, event)
    db.flush()
    return project
