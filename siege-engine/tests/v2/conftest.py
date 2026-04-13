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

    Additions tracker — bump the Phase 3 addendum whenever a new
    event shape lands so reducer round-trip coverage stays honest:

    - Phase 2 core: NodeCreated/Renamed/Reparented/Promoted/Demoted,
      EdgeCreated/Deleted, FragmentUpdated, DraftGenerated/Edited/
      Approved/Discarded, NodesMerged, NodeDeleted, ViewRecorded.
    - Phase 3 stage 2 (sysarch): NodeCreated with tier="sysarch",
      tier="policy", EdgeCreated with edge_type="decomposition",
      sysarch techspec FragmentUpdated.
    - Phase 3 stage 3 (subreqs): NodeCreated with tier="subreqs",
      NodeCreated with tier="resp" and parent_id=comp (subresp
      variant), decomposition edge parent_resp → subresp.
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
    # Phase 3 additions
    sysarch_id = "sysarch_SYSR1111"
    policy_id = "policy_POLY1111"
    subreqs_id = "subreqs_SUBR1111"
    top_resp_id = "resp_TOPR1111"  # top-level resp (parent_id=None)
    subresp_id = "resp_SUBRP111"  # subresp (parent_id=comp_a)
    edge_decomp_resp_to_comp = "edge_EDCR1111"
    edge_decomp_resp_to_sub = "edge_EDCS1111"
    sysarch_techspec_frag = f"{sysarch_id}_techspec"

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
        # ── Phase 3 stage 2 additions (sysarch, policy, decomposition edges) ──
        ev.NodeCreated(
            node_id=sysarch_id,
            tier="sysarch",
            kind="domain",
            parent_id=None,
            name="System Architecture",
        ),
        ev.NodeCreated(
            node_id=policy_id,
            tier="policy",
            kind="domain",
            parent_id=None,
            name="LLM Telemetry",
            content=(
                "<policy><name>LLM Telemetry</name>"
                "<trigger>any LLM call</trigger>"
                "<required>resp_TOPR1111</required>"
                "<rationale>Audit cost.</rationale></policy>"
            ),
        ),
        ev.NodeCreated(
            node_id=top_resp_id,
            tier="resp",
            kind="domain",
            parent_id=None,
            name="SessionManagement",
            content="Own session state.",
        ),
        ev.EdgeCreated(
            edge_id=edge_decomp_resp_to_comp,
            edge_type="decomposition",
            source_id=top_resp_id,
            target_id=comp_a,
        ),
        ev.FragmentUpdated(
            fragment_id=sysarch_techspec_frag,
            owner_id=sysarch_id,
            fragment_kind=ev.FragmentKind.TECHSPEC,
            new_content="Python + React + PostgreSQL stack.",
        ),
        # ── Phase 3 stage 3 additions (subreqs, subresps, decomp edges) ──
        ev.NodeCreated(
            node_id=subreqs_id,
            tier="subreqs",
            kind="domain",
            parent_id=comp_a,
            name="Subrequirements",
        ),
        ev.NodeCreated(
            node_id=subresp_id,
            tier="resp",
            kind="domain",
            parent_id=comp_a,
            name="Tokenization",
            content="Convert raw cards to tokens.",
        ),
        ev.EdgeCreated(
            edge_id=edge_decomp_resp_to_sub,
            edge_type="decomposition",
            source_id=top_resp_id,
            target_id=subresp_id,
        ),
        ev.ViewRecorded(user_id="user_01", batch_id="batch_01", event_offset=10),
    ]


@pytest.fixture()
def populated_project(db, project, canonical_events):
    """Append the canonical event sequence into ``project`` and return it."""
    for event in canonical_events:
        append_event(db, project.id, event)
    db.flush()
    return project
