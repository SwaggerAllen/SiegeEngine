"""Tests for the Pydantic event vocabulary — schema + roundtrip."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.graph import events as ev
from backend.graph.fragments import FragmentKind

_ALL_EVENTS: list[ev._EventBase] = [
    ev.NodeCreated(node_id="comp_ABCDEFGH", tier="comp", kind="domain", name="X"),
    ev.NodeRenamed(node_id="comp_ABCDEFGH", new_name="Y"),
    ev.NodeReparented(node_id="comp_ABCDEFGH", new_parent_id="resp_ABCDEFGH"),
    ev.NodeReparented(node_id="comp_ABCDEFGH", new_parent_id=None),
    ev.NodePromoted(node_id="comp_ABCDEFGH", new_tier="feat"),
    ev.NodeDemoted(node_id="feat_ABCDEFGH", new_tier="resp"),
    ev.NodesMerged(
        source_ids=["comp_AAAAAAAA", "comp_BBBBBBBB"],
        dest_id="comp_AAAAAAAA",
        dest_name="Merged",
    ),
    ev.NodeSplit(
        source_id="comp_AAAAAAAA",
        dest_ids=["comp_CCCCCCCC", "comp_DDDDDDDD"],
        dest_names=["C", "D"],
    ),
    ev.NodeDeleted(node_id="comp_ABCDEFGH"),
    ev.EdgeCreated(
        edge_id="edge_EEEEEEEE",
        edge_type="dependency",
        source_id="comp_AAAAAAAA",
        target_id="comp_BBBBBBBB",
    ),
    ev.EdgeDeleted(edge_id="edge_EEEEEEEE"),
    ev.FragmentUpdated(
        fragment_id="comp_ABCDEFGH_pubapi",
        owner_id="comp_ABCDEFGH",
        fragment_kind=FragmentKind.PUBAPI,
        new_content="x",
    ),
    ev.DraftGenerated(
        draft_id="d1",
        target_type="node",
        target_id="comp_ABCDEFGH",
        content="x",
        batch_id="b1",
    ),
    ev.DraftEdited(draft_id="d1", new_content="y"),
    ev.DraftApproved(draft_id="d1"),
    ev.DraftDiscarded(draft_id="d1"),
    ev.ViewRecorded(user_id="u1", batch_id="b1", event_offset=5),
]


@pytest.mark.parametrize("event", _ALL_EVENTS, ids=lambda e: e.event_type)
def test_event_roundtrip(event):
    # dump → validate should return an equal object on every event class.
    dumped = event.model_dump(mode="json")
    cls = type(event)
    rehydrated = cls.model_validate(dumped)
    assert rehydrated == event


def test_event_from_row_unknown_type():
    with pytest.raises(KeyError):
        ev.event_from_row("NotAnEvent", {})


def test_event_from_row_routes_correctly():
    original = ev.NodeRenamed(node_id="comp_ABCDEFGH", new_name="X")
    row_payload = original.model_dump(mode="json")
    rehydrated = ev.event_from_row("NodeRenamed", row_payload)
    assert isinstance(rehydrated, ev.NodeRenamed)
    assert rehydrated == original


class TestRejectsBadShape:
    def test_missing_required_field(self):
        with pytest.raises(ValidationError):
            ev.NodeCreated(node_id="x", tier="comp", kind="domain")  # type: ignore[call-arg]

    def test_extra_field_rejected(self):
        with pytest.raises(ValidationError):
            ev.NodeDeleted(node_id="x", extra="nope")  # type: ignore[call-arg]

    def test_invalid_literal(self):
        with pytest.raises(ValidationError):
            ev.NodeCreated(node_id="x", tier="invalid", kind="domain", name="X")  # type: ignore[arg-type]

    def test_merge_needs_two_sources(self):
        with pytest.raises(ValidationError):
            ev.NodesMerged(source_ids=["only_one"], dest_id="only_one", dest_name="X")
