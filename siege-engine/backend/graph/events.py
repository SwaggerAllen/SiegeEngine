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
    "vocab",
    "ref",
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
    # Initial content for the node. Empty by default — bootstrap
    # nodes (expansion, reqs, sysarch, subreqs) are minted as
    # shells and get their content later via DraftApproved.
    # Nodes minted from an already-approved structured source
    # (e.g. feat_* nodes minted from an approved expansion) carry
    # their content at creation time, so rebuild-from-log replays
    # back to the same state.
    content: str = ""
    # Optional grouping label, used only by feat_* nodes minted
    # from a <features> expansion that includes <group> blocks.
    # Null for ungrouped features and for all non-feature tiers.
    group_label: str | None = None
    # Whether a feature was marked <implicit/> in the expansion —
    # inferred as obviously-necessary rather than pulled from the
    # input doc. Defaults false; non-feature tiers ignore it.
    is_implicit: bool = False
    # Whether a comp_* node was minted with the foundation role
    # (from the ``<foundation/>`` marker in the parsed sysarch /
    # comparch output). Defaults false; non-comp tiers ignore it.
    # See ``docs/architecture/v2-rearchitecture.md`` §Foundation
    # components for why this is persisted.
    is_foundation: bool = False
    # Phase-11 followup B7. Whether a feat_* node is deferred —
    # visible in the expansion and DAG but skipped by reqs and
    # sysarch generation (``list_features(include_deferred=False)``).
    # Defaults false; non-feat tiers leave it false and ignore it.
    is_deferred: bool = False


class NodeRenamed(_EventBase):
    event_type: Literal["NodeRenamed"] = "NodeRenamed"
    node_id: str
    new_name: str


class NodeReparented(_EventBase):
    event_type: Literal["NodeReparented"] = "NodeReparented"
    node_id: str
    new_parent_id: str | None


class NodeDeferredUpdated(_EventBase):
    """Toggle a feat_* node's ``is_deferred`` flag.

    Phase-11 followup B7. Deferred features stay in the expansion
    + DAG but are filtered out of the reqs / sysarch generation
    inputs — used for "design-toward but skip for now" items.
    Non-destructive and reversible; the reducer just flips the
    column.
    """

    event_type: Literal["NodeDeferredUpdated"] = "NodeDeferredUpdated"
    node_id: str
    is_deferred: bool


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
    edge_type: Literal[
        "dependency",
        "domain_parent",
        "policy_application",
        "decomposition",
        "reference",
    ]
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
    # Why the draft was discarded. ``user_regen`` is a user-initiated
    # Reject & Regenerate on a pending draft. ``auto_revision`` is
    # an intermediate discard by the AI-driven auto-revision loop
    # (the draft was generated, AI-reviewed, and discarded without
    # the user ever seeing it as pending). ``None`` on legacy events
    # from before the field was added — those are all user-initiated
    # discards by construction (auto-revision didn't exist yet).
    #
    # The read-side diff helper filters on this: "previous-version"
    # baselines are drawn from ``user_regen`` / legacy discards only;
    # ``auto_revision`` intermediates are skipped so the default diff
    # shows the net change across the whole run, not each pass.
    reason: Literal["user_regen", "auto_revision"] | None = None


class DraftReviewUpdated(_EventBase):
    """AI self-review output landed for a draft-bearing tier.

    Phase 8 — one review pass runs after every draft commit.
    The review job re-assembles the same context the generator
    saw, calls the CLI, and emits this event with the review
    markdown.

    ``draft_id`` is the target Draft id for tiers that carry a
    draft row (everything except fanin); the reducer writes the
    review text to ``Draft.review_text``. ``None`` for fanin,
    which has no draft lifecycle — the reducer writes to
    ``Node.review_text`` instead.

    ``node_id`` is always populated — the owning tier node whose
    detail query needs invalidating when this event lands. The
    broadcaster uses it to compute SSE ``node_ids`` without a
    DB lookup at publish time.

    Failures don't emit this event — review jobs that exhaust
    their retry budget mark their Job row ``failed``; the tier
    detail response surfaces that via ``review_status ==
    "failed"`` + ``review_last_error``. Event-sourced state
    stays append-only: only successful reviews land.
    """

    event_type: Literal["DraftReviewUpdated"] = "DraftReviewUpdated"
    draft_id: str | None
    node_id: str
    review_text: str


class FanInContentUpdated(_EventBase):
    """A fan-in node's content is replaced by a new synthesis.

    Fan-in (``tier="fanin"``) has no draft lifecycle — the
    generation handler validates the LLM output and writes the
    serialized ``<fanin>`` block directly to ``Node.content``
    via this event. Reusing ``DraftApproved`` would create
    phantom ``Draft`` rows that have no review step; this
    dedicated event keeps the "draft row implies a reviewable
    artifact" invariant intact.

    Phase 7 counterpart to ``DraftApproved`` for the fan-in tier.
    The reducer asserts the target node's tier is ``"fanin"`` and
    overwrites its ``content`` field; the event itself carries
    only the node id and the new content.
    """

    event_type: Literal["FanInContentUpdated"] = "FanInContentUpdated"
    node_id: str
    new_content: str


class BootstrapNodeContentCleared(_EventBase):
    """Reset a bootstrap tier's approved content back to empty.

    Emitted by the destructive reset path on approved bootstrap nodes
    (currently sysarch only) so the user can regenerate against a
    new prompt without touching upstream state. The reducer sets
    ``node.content = ""`` (empty string rather than ``None``, since
    the column is ``nullable=False``) so the read-only post-approval
    UI state flips back to the pending / no-content state, which in
    turn unblocks the HTTP layer's freeze-on-approval 409 guard —
    ``has_been_approved`` evaluates ``bool(node.content)``, which is
    ``False`` for empty string.

    Carries only the node id — the reset route walks the downstream
    projection separately and emits ``NodeDeleted`` / ``DraftDiscarded``
    events for everything that was minted from the approval before
    appending this event, all in the same transaction. Replay of the
    event log therefore produces the same post-reset state
    deterministically.
    """

    event_type: Literal["BootstrapNodeContentCleared"] = "BootstrapNodeContentCleared"
    node_id: str


class FeedbackCleared(_EventBase):
    """Mark a cutoff past which the Feedback History panel ignores
    prior entries for ``node_id``.

    Emitted by the destructive reset path alongside
    ``BootstrapNodeContentCleared``. Feedback entries come from two
    append-only sources that the reset can't actually delete — user
    prose sits on immutable ``Job.payload`` rows, and AI review text
    sits on ``Draft.review_text`` for drafts whose ``DraftDiscarded``
    events have already been logged. Both predate the reset and aren't
    safe to mutate without breaking the event-log-is-the-truth
    invariant.

    The reducer records this event and nothing else (no projection
    mutation). :func:`backend.graph.queries.feedback_history` reads
    the most-recent ``FeedbackCleared`` row for ``node_id`` and filters
    jobs / drafts whose ``created_at`` is at or before that cutoff, so
    the panel shows only post-reset feedback and the user never has to
    parse "what came before from what came after".

    Every new reset emits a fresh ``FeedbackCleared`` whose timestamp
    becomes the new cutoff — multiple resets compose correctly.
    """

    event_type: Literal["FeedbackCleared"] = "FeedbackCleared"
    node_id: str


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
        NodeDeferredUpdated,
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
        FanInContentUpdated,
        BootstrapNodeContentCleared,
        FeedbackCleared,
        ViewRecorded,
    ],
    Field(discriminator="event_type"),
]


_EVENT_TYPES: dict[str, type[_EventBase]] = {
    "NodeCreated": NodeCreated,
    "NodeRenamed": NodeRenamed,
    "NodeReparented": NodeReparented,
    "NodeDeferredUpdated": NodeDeferredUpdated,
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
    "FanInContentUpdated": FanInContentUpdated,
    "BootstrapNodeContentCleared": BootstrapNodeContentCleared,
    "FeedbackCleared": FeedbackCleared,
    "ViewRecorded": ViewRecorded,
}


def event_from_row(event_type: str, payload: dict) -> _EventBase:
    """Rehydrate a Pydantic event from a ``graph_events`` row.

    Raises ``KeyError`` if the event type is unknown and whatever
    ``model_validate`` raises on schema mismatch.
    """
    cls = _EVENT_TYPES[event_type]
    return cls.model_validate(payload)
