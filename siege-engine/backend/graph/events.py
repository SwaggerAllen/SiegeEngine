"""Pydantic event models — the v2 structured-model event vocabulary.

Every write to the structured model goes through
:func:`backend.graph.reducer.append_event`, which expects one of the
models in this file. Events describe intent; the reducer decides how
projections change. None of these events call regen — they only mutate
projections.

Each event subclass sets its own ``event_type`` literal matching the
class name. The reducer uses ``event_type`` to dispatch to the correct
apply branch and to route round-trips from the event log back into the
right Pydantic class.
"""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field

from backend.graph.fragments import FragmentKind

# Keep this in sync with ``backend.models.node.NODE_TIERS`` and the
# ``Kind`` enum in ``backend.graph.ids``. Listed inline as a Literal
# so Pydantic validates at model-construction time.
NodeTier = Literal[
    "feat",
    "resp",
    "comp",
    "impl",
    "plan",
    "policy",
    "expansion",
    "reqs",
    "subreqs",
    "sysarch",
    "manifest",
    "fanin",
]


class _EventBase(BaseModel):
    """Shared config for all event models: strict, extra-forbidden.

    Subclasses override ``event_type`` with a ``Literal`` matching the
    class name; it is declared here so the reducer can dispatch on it
    without mypy complaining about a missing attribute on the base.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    event_type: str


# ── Structural events ────────────────────────────────────────────────


class NodeCreated(_EventBase):
    event_type: Literal["NodeCreated"] = "NodeCreated"
    node_id: str
    tier: NodeTier
    kind: Literal["domain", "presentational"]
    parent_id: str | None = None
    name: str
    display_order: int = 0


class NodeRenamed(_EventBase):
    event_type: Literal["NodeRenamed"] = "NodeRenamed"
    node_id: str
    new_name: str


class NodeReparented(_EventBase):
    event_type: Literal["NodeReparented"] = "NodeReparented"
    node_id: str
    new_parent_id: str | None


class NodePromoted(_EventBase):
    event_type: Literal["NodePromoted"] = "NodePromoted"
    node_id: str
    new_tier: NodeTier


class NodeDemoted(_EventBase):
    event_type: Literal["NodeDemoted"] = "NodeDemoted"
    node_id: str
    new_tier: NodeTier


class NodesMerged(_EventBase):
    event_type: Literal["NodesMerged"] = "NodesMerged"
    source_ids: list[str] = Field(..., min_length=2)
    dest_id: str
    dest_name: str


class NodeSplit(_EventBase):
    event_type: Literal["NodeSplit"] = "NodeSplit"
    source_id: str
    dest_ids: list[str] = Field(..., min_length=2)
    dest_names: list[str] = Field(..., min_length=2)


class NodeDeleted(_EventBase):
    event_type: Literal["NodeDeleted"] = "NodeDeleted"
    node_id: str


class EdgeCreated(_EventBase):
    event_type: Literal["EdgeCreated"] = "EdgeCreated"
    edge_id: str
    edge_type: Literal["dependency", "domain_parent", "policy_application"]
    source_id: str
    target_id: str


class EdgeDeleted(_EventBase):
    event_type: Literal["EdgeDeleted"] = "EdgeDeleted"
    edge_id: str


# ── Fragment events ──────────────────────────────────────────────────


class FragmentUpdated(_EventBase):
    """A fragment's approved content is replaced.

    Only fired when an approved draft lands on a fragment, or during
    cold-start initial generation.
    """

    event_type: Literal["FragmentUpdated"] = "FragmentUpdated"
    fragment_id: str
    owner_id: str
    fragment_kind: FragmentKind
    new_content: str


# ── Draft lifecycle ──────────────────────────────────────────────────


class DraftGenerated(_EventBase):
    event_type: Literal["DraftGenerated"] = "DraftGenerated"
    draft_id: str
    target_type: Literal["node", "fragment"]
    target_id: str
    content: str
    batch_id: str


class DraftEdited(_EventBase):
    """A draft's content is replaced by a regeneration.

    Prose feedback that triggers the regen is *not* stored as an event;
    only the generation output round-trips through the log.
    """

    event_type: Literal["DraftEdited"] = "DraftEdited"
    draft_id: str
    new_content: str


class DraftApproved(_EventBase):
    """Approve a draft, committing its content to the target.

    The reducer expands this into a status flip on the draft *and* a
    projection write to the target (``nodes.name``, a fragment's
    ``content``, etc.).
    """

    event_type: Literal["DraftApproved"] = "DraftApproved"
    draft_id: str


class DraftDiscarded(_EventBase):
    event_type: Literal["DraftDiscarded"] = "DraftDiscarded"
    draft_id: str


# ── View events ──────────────────────────────────────────────────────


class ViewRecorded(_EventBase):
    event_type: Literal["ViewRecorded"] = "ViewRecorded"
    user_id: str
    batch_id: str
    event_offset: int


# ── Discriminated union ──────────────────────────────────────────────

Event = Annotated[
    Union[
        NodeCreated,
        NodeRenamed,
        NodeReparented,
        NodePromoted,
        NodeDemoted,
        NodesMerged,
        NodeSplit,
        NodeDeleted,
        EdgeCreated,
        EdgeDeleted,
        FragmentUpdated,
        DraftGenerated,
        DraftEdited,
        DraftApproved,
        DraftDiscarded,
        ViewRecorded,
    ],
    Field(discriminator="event_type"),
]


_EVENT_TYPES: dict[str, type[_EventBase]] = {
    "NodeCreated": NodeCreated,
    "NodeRenamed": NodeRenamed,
    "NodeReparented": NodeReparented,
    "NodePromoted": NodePromoted,
    "NodeDemoted": NodeDemoted,
    "NodesMerged": NodesMerged,
    "NodeSplit": NodeSplit,
    "NodeDeleted": NodeDeleted,
    "EdgeCreated": EdgeCreated,
    "EdgeDeleted": EdgeDeleted,
    "FragmentUpdated": FragmentUpdated,
    "DraftGenerated": DraftGenerated,
    "DraftEdited": DraftEdited,
    "DraftApproved": DraftApproved,
    "DraftDiscarded": DraftDiscarded,
    "ViewRecorded": ViewRecorded,
}


def event_from_row(event_type: str, payload: dict) -> _EventBase:
    """Rehydrate a Pydantic event from a ``graph_events`` row.

    Raises ``KeyError`` if the event type is unknown and whatever
    ``model_validate`` raises on schema mismatch.
    """
    cls = _EVENT_TYPES[event_type]
    return cls.model_validate(payload)
