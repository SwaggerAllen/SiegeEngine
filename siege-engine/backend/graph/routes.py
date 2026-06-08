"""HTTP routes for the v2 structured model.

Two groups:

* ``GET /{project_id}/model`` — debug snapshot of the full projection.
  Used for development smoke tests.
* ``/{project_id}/expansion/*`` — the first vertical slice's feature-
  expansion flow: fetch current state, request a regeneration, or
  approve / discard a pending draft. Everything else v2 will bolt
  onto this same router.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.auth.routes import get_current_user
from backend.database import get_db
from backend.graph import queries
from backend.graph.broadcast import commit_and_publish
from backend.graph.fragments import (
    FragmentKind,
    fragment_id,
)
from backend.models import Project, User
from backend.models.node import Draft, Edge, Fragment, Node

logger = logging.getLogger(__name__)

router = APIRouter()


def _require_project(db: Session, project_id: str) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


# ── Shared response models ────────────────────────────────────────


class ExpansionNodeResponse(BaseModel):
    """Generic node-payload shape used by refs + review-batches."""

    id: str
    name: str
    content: str
    updated_at: str


class DraftHistoryEntry(BaseModel):
    """One row in a node's draft timeline (Phase 13 audit history)."""

    draft_id: str
    target_type: str
    status: str
    discard_reason: str | None
    change_summary: str | None
    created_at: str


class DraftHistoryResponse(BaseModel):
    """Newest-first list of every draft that ever targeted one node."""

    entries: list[DraftHistoryEntry]


# ── Debug ────────────────────────────────────────────────────────────


@router.get("/{project_id}/model")
def get_project_model(
    project_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> dict:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return queries.projection_snapshot(db, project_id)


@router.get("/{project_id}/debug/skeleton")
def get_project_skeleton(
    project_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> dict:
    """Content-stripped projection snapshot for sharing with debuggers.

    Same shape as ``/model`` but every prose field (node content,
    fragment content, draft content) is replaced with its
    character length. Node names are kept because they're
    identifiers, not prose. Also includes a ``recent_jobs``
    section with the latest job per job_type plus an error tail
    for failed jobs.

    Use case: paste the JSON into a chat or issue to get help
    debugging without leaking the project's actual prose content.
    The IDs, relationships, lengths, and error tails are enough
    to reason about structure; the prose stays private.
    """
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return queries.skeleton_snapshot(db, project_id)


# ── Project structure + event stream ─────────────────────────────
#
# Two endpoints that together replace the per-tier polling
# pattern:
#
# - ``GET /structure`` — one consolidated read that ships every
#   node + edge in the project plus status flags. Replaces nav-tree,
#   decomposition-graph, responsibility-coverage, and most list
#   endpoints. Returns ``offset`` so clients can subscribe to
#   ``/events/stream?since=<offset>`` without losing events
#   committed between the snapshot and the SSE handshake.
# - ``GET /events/stream`` — SSE channel. Emits one tiny message
#   per committed event (``{offset, event_type, node_ids}``).
#   Clients use these as invalidation signals for their TanStack
#   Query cache; per-tier detail GETs refetch on push rather than
#   on a 2-second timer.
#
# See ``backend/graph/broadcast.py`` for the in-process pub/sub
# primitive, and the design doc at
# ``/root/.claude/plans/let-s-plan-phase-6-6-gentle-engelbart.md``.


class StructureNodeResponse(BaseModel):
    id: str
    tier: str
    kind: str  # 'domain' | 'presentational'
    parent_id: str | None
    name: str
    display_order: int
    # Content is included inline for the "light" tiers whose
    # only UI is a list view — resp, feat, policy, vocab, ref.
    # Heavy tiers (comp, impl, fanin, expansion, reqs,
    # sysarch) have dedicated detail endpoints that ship the
    # full XML draft + telemetry, so we leave their ``content``
    # empty here to keep the snapshot payload small. The
    # ``has_content`` boolean below still reflects the truth
    # for every tier.
    content: str
    has_content: bool
    has_pending_draft: bool
    generation_running: bool
    # True when the most recent generation job targeting this node
    # ended in ``failed`` state (parse-validate exhausted, CLI
    # crash, budget exceeded, etc.). Cleared when a retry is
    # enqueued. Surfaced as a red dot in the sidebar tree ahead
    # of the amber pending-draft / running indicators.
    has_error: bool
    # True when the node is idle and explicitly waiting on the
    # user to kick it — either the latest job was cancelled with
    # no replacement queued, or the node is an ``impl_*`` that
    # hasn't been triggered yet (impl is the one tier that
    # doesn't auto-enqueue on mint). Surfaced as a blue dot in
    # the sidebar tree, between red (error) and amber (pending
    # / running) in precedence. Does not fire for nodes that
    # are upstream-blocked — those sit idle waiting for the
    # chain, not the user.
    needs_user_action: bool
    # Phase 9 — staleness ledger projection. True when this node has
    # at least one active staleness marker: an upstream node changed
    # and the ledger hasn't been cleared by this node's own regen
    # yet. ``staleness_reasons`` carries the distinct reasons
    # ("content_changed", "fragment_changed", "edge_created",
    # "edge_deleted", "structural_change") across all active
    # markers, so the sidebar tree can surface a stale badge and
    # the per-tier panel can explain why. See
    # ``backend/graph/fanout.py`` for how markers are produced.
    is_stale: bool
    staleness_reasons: list[str]
    # Sysarch-time fragments for ``comp`` tier nodes. Populated at
    # sysarch mint with the role paragraph (techspec) and api-intent
    # paragraph (pubapi) the LLM wrote in its ``<sysarch>`` output.
    # Read-only context for the component Overview tab so the user
    # can review what sysarch said about this comp before triggering
    # comparch generation. Empty string for tiers that don't own
    # these fragments. Kept inline on the structure payload rather
    # than via a dedicated endpoint because the fragment bodies are
    # small (a few hundred chars each) and refetching on SSE keeps
    # them fresh without extra round-trips.
    techspec: str
    pubapi: str
    # Phase-11 followup B7. Deferred features are visible in the
    # DAG and sidebar but excluded from the reqs / sysarch
    # generation inputs. Defaults false for every non-feat tier;
    # the frontend renders deferred feats dimmed.
    is_deferred: bool = False


class StructureEdgeResponse(BaseModel):
    id: str
    edge_type: str
    source_id: str
    target_id: str


class StructureResponse(BaseModel):
    # Event-log offset at the time this snapshot was read. SSE
    # subscribers pass this as ``?since=<offset>`` on
    # ``/events/stream`` so no event is lost in the race between
    # reading the snapshot and subscribing to the channel.
    offset: int
    nodes: list[StructureNodeResponse]
    edges: list[StructureEdgeResponse]


# Every tier the frontend's structure store cares about. ``feat``,
# ``policy``, ``vocab``, and ``ref`` are included so the list
# views for features / policies / vocabulary / references can
# derive from this single endpoint too. ``resp`` covers both
# top-level responsibilities and subresps.
_STRUCTURE_TIERS = (
    "expansion",
    "reqs",
    "sysarch",
    "feat",
    "resp",
    "comp",
    "fanin",
    "impl",
    "policy",
    "vocab",
    "ref",
)

_STRUCTURE_EDGE_TYPES = (
    "dependency",
    "decomposition",
    "domain_parent",
    "reference",
    "policy_application",
)


@router.get(
    "/{project_id}/structure",
    response_model=StructureResponse,
)
def get_project_structure(
    project_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> StructureResponse:
    """Return the full structural snapshot for the workspace.

    One query per project. Consumed by the sidebar tree, the
    decomposition graph, responsibility coverage, and every
    list view (features, responsibilities, subcomps, policies,
    vocab, refs). Replaces the per-view GET endpoints that
    previously each required their own fetch + polling.
    """
    from backend.graph.staleness import stale_node_reasons

    _require_project(db, project_id)

    node_rows = list(
        db.execute(
            select(Node)
            .where(
                Node.project_id == project_id,
                Node.tier.in_(_STRUCTURE_TIERS),
            )
            .order_by(Node.tier.asc(), Node.display_order.asc(), Node.id.asc())
        ).scalars()
    )
    node_ids_in_project = {n.id for n in node_rows}

    edge_rows = list(
        db.execute(
            select(Edge)
            .where(
                Edge.project_id == project_id,
                Edge.edge_type.in_(_STRUCTURE_EDGE_TYPES),
            )
            .order_by(Edge.id.asc())
        ).scalars()
    )
    # Filter edges to those whose endpoints are in the returned
    # node set — keeps the response self-consistent.
    filtered_edges = [
        e
        for e in edge_rows
        if e.source_id in node_ids_in_project and e.target_id in node_ids_in_project
    ]

    pending_target_ids: set[str] = set(
        db.execute(
            select(Draft.target_id).where(
                Draft.project_id == project_id,
                Draft.target_type == "node",
                Draft.status == "pending",
            )
        ).scalars()
    )

    # Per-tier generation retired; the few remaining badges all resolve
    # to "no active job" because the server doesn't generate anymore.
    running_ids: set[str] = set()
    errored_ids: set[str] = set()
    user_action_ids: set[str] = set()
    stale_reasons_by_id = stale_node_reasons(db, project_id)
    offset = queries.latest_offset(db, project_id) or 0

    # Tiers whose content is included inline. See the doc on
    # ``StructureNodeResponse.content`` for the rationale.
    light_content_tiers = {"feat", "resp", "policy", "vocab", "ref"}

    # Bulk-load the techspec + pubapi fragments for every comp in
    # the project. Reads each comp's layered slot first (comparch*
    # for top-level, subcomparch* for subcomp) and falls back to
    # the sysarch skeletal seed when the layer slot is empty —
    # mirrors the per-comp ``best_layered_fragment_content``
    # dispatch but in one bulk query so the structure fetch stays
    # one-query-per-table.
    comp_nodes = [n for n in node_rows if n.tier == "comp"]
    techspec_by_comp: dict[str, str] = {}
    pubapi_by_comp: dict[str, str] = {}
    if comp_nodes:
        wanted_fragment_ids = []
        for n in comp_nodes:
            wanted_fragment_ids.append(fragment_id(n.id, FragmentKind.TECHSPEC))
            wanted_fragment_ids.append(fragment_id(n.id, FragmentKind.PUBAPI))
            if n.parent_id is None:
                wanted_fragment_ids.append(fragment_id(n.id, FragmentKind.COMPARCH_TECHSPEC))
                wanted_fragment_ids.append(fragment_id(n.id, FragmentKind.COMPARCH_PUBAPI))
            else:
                wanted_fragment_ids.append(fragment_id(n.id, FragmentKind.SUBCOMPARCH_TECHSPEC))
                wanted_fragment_ids.append(fragment_id(n.id, FragmentKind.SUBCOMPARCH_PUBAPI))
        frag_rows = db.execute(
            select(Fragment.id, Fragment.content).where(
                Fragment.project_id == project_id,
                Fragment.id.in_(wanted_fragment_ids),
            )
        ).all()
        fragment_by_id = {fid: (fcontent or "") for fid, fcontent in frag_rows}
        for n in comp_nodes:
            layered_ts = (
                FragmentKind.COMPARCH_TECHSPEC
                if n.parent_id is None
                else FragmentKind.SUBCOMPARCH_TECHSPEC
            )
            layered_pa = (
                FragmentKind.COMPARCH_PUBAPI
                if n.parent_id is None
                else FragmentKind.SUBCOMPARCH_PUBAPI
            )
            layered_ts_content = fragment_by_id.get(fragment_id(n.id, layered_ts), "")
            techspec_by_comp[n.id] = (
                layered_ts_content
                if layered_ts_content.strip()
                else fragment_by_id.get(fragment_id(n.id, FragmentKind.TECHSPEC), "")
            )
            layered_pa_content = fragment_by_id.get(fragment_id(n.id, layered_pa), "")
            pubapi_by_comp[n.id] = (
                layered_pa_content
                if layered_pa_content.strip()
                else fragment_by_id.get(fragment_id(n.id, FragmentKind.PUBAPI), "")
            )

    return StructureResponse(
        offset=offset,
        nodes=[
            StructureNodeResponse(
                id=n.id,
                tier=n.tier,
                kind=n.kind,
                parent_id=n.parent_id,
                name=n.name,
                display_order=n.display_order,
                content=(n.content or "") if n.tier in light_content_tiers else "",
                has_content=bool((n.content or "").strip()),
                has_pending_draft=n.id in pending_target_ids,
                generation_running=n.id in running_ids,
                has_error=n.id in errored_ids,
                needs_user_action=n.id in user_action_ids,
                is_stale=n.id in stale_reasons_by_id,
                staleness_reasons=stale_reasons_by_id.get(n.id, []),
                techspec=techspec_by_comp.get(n.id, "") if n.tier == "comp" else "",
                pubapi=pubapi_by_comp.get(n.id, "") if n.tier == "comp" else "",
                is_deferred=n.is_deferred,
            )
            for n in node_rows
        ],
        edges=[
            StructureEdgeResponse(
                id=e.id,
                edge_type=e.edge_type,
                source_id=e.source_id,
                target_id=e.target_id,
            )
            for e in filtered_edges
        ],
    )


@router.get("/{project_id}/events/stream")
async def get_project_event_stream(
    project_id: str,
    since: int | None = None,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """SSE channel of committed events for this project.

    Emits `{offset, event_type, node_ids}` per commit. The
    ``since`` query param is the event-log offset the client
    already has (from its last ``/structure`` read or a prior
    live event). The broadcaster replays buffered messages with
    ``offset > since`` before switching to live; this closes the
    race where an event commits between snapshot read and
    subscribe.

    Client lifecycle: use browser ``EventSource``. Reconnects
    automatically; on reconnect, re-fetch ``/structure`` to
    re-seed state (cheaper and simpler than reasoning about
    ring-buffer gaps).
    """
    from sse_starlette.sse import EventSourceResponse

    from backend.graph.broadcast import get_broadcaster

    _require_project(db, project_id)
    broadcaster = get_broadcaster()

    async def event_publisher():
        async for msg in broadcaster.subscribe(project_id, since_offset=since):
            yield {
                "event": "delta",
                "data": __import__("json").dumps(msg.to_payload()),
            }

    # 15-second ping from sse-starlette so intermediate proxies
    # (load balancers, corporate firewalls) don't drop the
    # connection as idle.
    return EventSourceResponse(event_publisher(), ping=15)


# ── Vocabulary routes (read-only) ──────────────────────────────────
#
# Authoring moved to the `/create_vocab` Claude Code skill — the
# body lives in the project repo at `vocab/<vocab_id>/body.md` and
# the v3 git routes in `vocabulary_git_routes.py` register it.
# The endpoints below are read-only projections used by the
# dashboard.


class VocabEntryResponse(BaseModel):
    id: str
    name: str
    content: str  # rendered body (read from git for v3 rows)
    parent_id: str | None
    parent_name: str | None  # resolved for the UI; None at project scope
    updated_at: str


class VocabListResponse(BaseModel):
    entries: list[VocabEntryResponse]


def _serialize_vocab_entry(db: Session, node: Node) -> VocabEntryResponse:
    from backend.graph.vocabulary_git_routes import resolve_vocab_body

    parent_name: str | None = None
    if node.parent_id is not None:
        parent = db.get(Node, node.parent_id)
        if parent is not None:
            parent_name = parent.name
    return VocabEntryResponse(
        id=node.id,
        name=node.name,
        content=resolve_vocab_body(node),
        parent_id=node.parent_id,
        parent_name=parent_name,
        updated_at=node.updated_at.isoformat() if node.updated_at else "",
    )


@router.get("/{project_id}/vocabulary", response_model=VocabListResponse)
def get_vocabulary(
    project_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> VocabListResponse:
    """List every vocab entry in a project, project-level first."""
    _require_project(db, project_id)
    from backend.graph.vocabulary import list_all_vocab

    entries = list_all_vocab(db, project_id)
    return VocabListResponse(entries=[_serialize_vocab_entry(db, e) for e in entries])


@router.get(
    "/{project_id}/features/{feat_id}/vocabulary",
    response_model=VocabListResponse,
)
def get_feature_vocabulary(
    project_id: str,
    feat_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> VocabListResponse:
    """List vocab entries scoped to one specific feature."""
    _require_project(db, project_id)
    feature = db.get(Node, feat_id)
    if feature is None or feature.project_id != project_id or feature.tier != "feat":
        raise HTTPException(status_code=404, detail=f"Feature {feat_id!r} not found")
    from backend.graph.vocabulary import list_feature_vocab

    entries = list_feature_vocab(db, project_id, feat_id)
    return VocabListResponse(entries=[_serialize_vocab_entry(db, e) for e in entries])


@router.get(
    "/{project_id}/vocabulary/{vocab_id}",
    response_model=VocabEntryResponse,
)
def get_vocabulary_entry(
    project_id: str,
    vocab_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> VocabEntryResponse:
    _require_project(db, project_id)
    from backend.graph.vocabulary import vocab_by_id

    entry = vocab_by_id(db, vocab_id)
    if entry is None or entry.project_id != project_id:
        raise HTTPException(status_code=404, detail=f"Vocab entry {vocab_id!r} not found")
    return _serialize_vocab_entry(db, entry)


# ── Reference routes (read-only) ──────────────────────────────────
#
# Authoring moved to the `/create_ref` Claude Code skill — the
# body lives in the project repo at `refs/<ref_id>/body.md` and
# the v3 git routes in `references_git_routes.py` register it.
# The endpoints below are read-only projections used by the
# dashboard.


class ReferenceEdgeResponse(BaseModel):
    edge_id: str
    source_id: str
    target_id: str


class ReferenceDetailResponse(BaseModel):
    """GET /references/{ref_id} response — node + edge lists."""

    node: ExpansionNodeResponse
    outgoing_edges: list[ReferenceEdgeResponse]
    incoming_edges: list[ReferenceEdgeResponse]


class ReferenceSummary(BaseModel):
    id: str
    name: str
    has_content: bool
    updated_at: str


class ReferenceListResponse(BaseModel):
    references: list[ReferenceSummary]


def _serialize_reference_summary(node: Node) -> ReferenceSummary:
    return ReferenceSummary(
        id=node.id,
        name=node.name,
        has_content=bool((node.body_sha or node.content or "").strip()),
        updated_at=node.updated_at.isoformat() if node.updated_at else "",
    )


def _serialize_ref_edge(edge: Edge) -> ReferenceEdgeResponse:
    return ReferenceEdgeResponse(
        edge_id=edge.id,
        source_id=edge.source_id,
        target_id=edge.target_id,
    )


@router.get("/{project_id}/references", response_model=ReferenceListResponse)
def get_references(
    project_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> ReferenceListResponse:
    """List every reference in a project, ordered by name."""
    _require_project(db, project_id)
    from backend.graph.references import list_project_references

    entries = list_project_references(db, project_id)
    return ReferenceListResponse(references=[_serialize_reference_summary(e) for e in entries])


@router.get(
    "/{project_id}/references/{ref_id}",
    response_model=ReferenceDetailResponse,
)
def get_reference(
    project_id: str,
    ref_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> ReferenceDetailResponse:
    """Return one ref's body + edge lists."""
    from backend.graph.references import (
        incoming_reference_edges,
        outgoing_reference_edges,
        reference_by_id,
    )
    from backend.graph.references_git_routes import resolve_ref_body

    _require_project(db, project_id)
    node = reference_by_id(db, ref_id)
    if node is None or node.project_id != project_id:
        raise HTTPException(status_code=404, detail=f"Reference {ref_id!r} not found")

    outgoing = [_serialize_ref_edge(e) for e in outgoing_reference_edges(db, project_id, ref_id)]
    incoming = [_serialize_ref_edge(e) for e in incoming_reference_edges(db, project_id, ref_id)]
    return ReferenceDetailResponse(
        node=ExpansionNodeResponse(
            id=node.id,
            name=node.name,
            content=resolve_ref_body(node),
            updated_at=node.updated_at.isoformat() if node.updated_at else "",
        ),
        outgoing_edges=outgoing,
        incoming_edges=incoming,
    )


# ── Phase-11 followup B9: aggregate feedback history ──────────────


class FeedbackHistoryEntryResponse(BaseModel):
    created_at: str
    source: str  # 'user' | 'ai_review'
    text: str


class FeedbackHistoryResponse(BaseModel):
    entries: list[FeedbackHistoryEntryResponse]


@router.get(
    "/{project_id}/nodes/{node_id}/feedback-history",
    response_model=FeedbackHistoryResponse,
)
def get_feedback_history(
    project_id: str,
    node_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> FeedbackHistoryResponse:
    """Return every prose feedback entry ever left on the target node.

    Combines user-authored regeneration feedback (pulled from the
    matching tier's job payloads) with AI self-review text (pulled
    from draft rows). Chronological ascending. Used by the B9
    "Feedback History" panel so the user can scan everything that's
    been said about this tier and pattern-match what prompts are
    missing.
    """
    _require_project(db, project_id)
    entries = queries.feedback_history(db, project_id, node_id)
    return FeedbackHistoryResponse(
        entries=[
            FeedbackHistoryEntryResponse(created_at=e.created_at, source=e.source, text=e.text)
            for e in entries
        ]
    )


# ── Phase 12: batched review walker — batch lifecycle ───────────────


class ReviewBatchResponse(BaseModel):
    """Serialized form of a :class:`backend.models.review.ReviewBatch`.

    Minted by ``POST /projects/{id}/review/batches``; the walker UI
    uses ``id`` on every subsequent walker call so the stale set and
    snapshot cache are evaluated relative to a stable pinned offset.
    ``closed_at`` is ``None`` until the user closes the batch.
    """

    id: str
    project_id: str
    pinned_offset: int
    created_at: str
    closed_at: str | None


def _serialize_review_batch(batch) -> ReviewBatchResponse:
    return ReviewBatchResponse(
        id=batch.id,
        project_id=batch.project_id,
        pinned_offset=batch.pinned_offset,
        created_at=batch.created_at.isoformat() if batch.created_at else "",
        closed_at=batch.closed_at.isoformat() if batch.closed_at else None,
    )


def _require_batch(db: Session, project_id: str, batch_id: str):
    """Resolve the batch and verify it belongs to this project."""
    from backend.graph.review import get_review_batch

    batch = get_review_batch(db, batch_id)
    if batch is None or batch.project_id != project_id:
        raise HTTPException(status_code=404, detail="Review batch not found")
    return batch


@router.post(
    "/{project_id}/review/batches",
    response_model=ReviewBatchResponse,
)
def post_open_review_batch(
    project_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> ReviewBatchResponse:
    """Open a new batched-review session pinned at the latest offset.

    The ``pinned_offset`` freezes the staleness-ledger evaluation
    context for the batch so concurrent writes after open don't
    shift the walker's to-do list.
    """
    from backend.graph.review import open_review_batch

    _require_project(db, project_id)
    batch = open_review_batch(db, project_id)
    db.commit()
    return _serialize_review_batch(batch)


@router.post(
    "/{project_id}/review/batches/{batch_id}/close",
    response_model=ReviewBatchResponse,
)
def post_close_review_batch(
    project_id: str,
    batch_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> ReviewBatchResponse:
    """Mark the batch closed so subsequent walker loads can skip it."""
    from backend.graph.review import close_review_batch

    _require_project(db, project_id)
    _require_batch(db, project_id, batch_id)
    batch = close_review_batch(db, batch_id)
    db.commit()
    return _serialize_review_batch(batch)


@router.get(
    "/{project_id}/review/batches/{batch_id}",
    response_model=ReviewBatchResponse,
)
def get_review_batch_route(
    project_id: str,
    batch_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> ReviewBatchResponse:
    """Return the batch row — used by the walker to render its header."""
    _require_project(db, project_id)
    batch = _require_batch(db, project_id, batch_id)
    return _serialize_review_batch(batch)


# ── Phase 12c: walker queries (stale nodes + per-node diff) ─────────


class StaleNodeItemResponse(BaseModel):
    """One row in the walker's left-rail list of stale nodes."""

    node_id: str
    tier: str
    name: str
    parent_id: str | None
    reasons: list[str]
    is_destructive: bool
    topological_order: int


class StaleNodesListResponse(BaseModel):
    items: list[StaleNodeItemResponse]


class DiffSidesResponse(BaseModel):
    """Before / after pair for a single content or fragment body.

    Nullable on either side: ``before=None`` means "didn't exist at
    ``pinned_offset``" (a fragment created after the pin);
    ``after=None`` means "no longer exists" (a fragment deleted by
    a destructive change).
    """

    before: str | None
    after: str | None


class FragmentDiffResponse(BaseModel):
    fragment_kind: str
    before: str | None
    after: str | None


class NodeDiffResponse(BaseModel):
    """Walker-pane payload for a single reviewed node.

    ``node_content`` diffs the ``Node.content`` field itself; the
    per-fragment list covers every fragment owned by the node so
    the accordion in the detail pane can render one section per
    fragment kind. Phase 13 — ``latest_change_summary`` carries
    the most-recent non-null draft change_summary for this
    target so the walker can render the "why" above the diff.
    """

    node_content: DiffSidesResponse
    fragments: list[FragmentDiffResponse]
    latest_change_summary: str | None = None


@router.get(
    "/{project_id}/review/batches/{batch_id}/nodes",
    response_model=StaleNodesListResponse,
)
def get_review_batch_nodes(
    project_id: str,
    batch_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> StaleNodesListResponse:
    """List stale nodes in roughly-topological order for the walker."""
    _require_project(db, project_id)
    batch = _require_batch(db, project_id, batch_id)
    items = queries.stale_nodes_at_offset(db, project_id, batch.pinned_offset)
    return StaleNodesListResponse(
        items=[
            StaleNodeItemResponse(
                node_id=item.node_id,
                tier=item.tier,
                name=item.name,
                parent_id=item.parent_id,
                reasons=item.reasons,
                is_destructive=item.is_destructive,
                topological_order=item.topological_order,
            )
            for item in items
        ]
    )


class AcceptReviewResponse(BaseModel):
    """Outcome of a successful accept click on the walker detail pane."""

    cleared_count: int
    regen_job_ids: list[str]
    is_destructive: bool


@router.post(
    "/{project_id}/review/batches/{batch_id}/nodes/{node_id}/accept",
    response_model=AcceptReviewResponse,
)
def post_review_batch_node_accept(
    project_id: str,
    batch_id: str,
    node_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> AcceptReviewResponse:
    """Accept a stale node from the walker's detail pane.

    Clears the node's active ledger rows. When any of those rows
    were ``structural_change``, additionally re-fires the cascade
    that was halted at destructive time by enqueueing a regen of
    this node — the new draft's non-destructive
    ``DraftGenerated`` event then propagates staleness downstream
    naturally. See :func:`backend.graph.review.accept_review`.
    """
    from backend.graph.review import accept_review

    _require_project(db, project_id)
    _require_batch(db, project_id, batch_id)
    try:
        result = accept_review(db, project_id, batch_id, node_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    commit_and_publish(db, project_id)
    return AcceptReviewResponse(
        cleared_count=result.cleared_count,
        regen_job_ids=result.regen_job_ids,
        is_destructive=result.is_destructive,
    )


@router.get(
    "/{project_id}/review/batches/{batch_id}/nodes/{node_id}/diff",
    response_model=NodeDiffResponse,
)
def get_review_batch_node_diff(
    project_id: str,
    batch_id: str,
    node_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> NodeDiffResponse:
    """Return the before/after diff bundle for one node click."""
    from backend.graph.diff import node_diff_payload
    from backend.models.node import Node

    _require_project(db, project_id)
    batch = _require_batch(db, project_id, batch_id)
    node = db.get(Node, node_id)
    if node is None or node.project_id != project_id:
        raise HTTPException(status_code=404, detail="Node not found in project")
    payload = node_diff_payload(db, project_id, node_id, batch.pinned_offset)
    return NodeDiffResponse(
        node_content=DiffSidesResponse(**payload["node_content"]),
        fragments=[FragmentDiffResponse(**f) for f in payload["fragments"]],
        latest_change_summary=payload.get("latest_change_summary"),
    )


# ── Phase 13 — draft change-summary audit history ───────────────────


@router.get(
    "/{project_id}/drafts/by-target/{target_id}/history",
    response_model=DraftHistoryResponse,
)
def get_draft_history(
    project_id: str,
    target_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> DraftHistoryResponse:
    """Return every draft that ever targeted ``target_id``, newest first.

    Carries the Phase 13 ``change_summary`` alongside each draft's
    lifecycle metadata so the frontend can render a per-node
    timeline without stitching together the walker's snapshot
    payload with the regen-diff state. Read-only — no write surface.
    """
    from backend.models.node import Draft

    _require_project(db, project_id)
    rows = list(
        db.execute(
            select(Draft)
            .where(Draft.project_id == project_id, Draft.target_id == target_id)
            .order_by(Draft.created_at.desc(), Draft.id.desc())
        ).scalars()
    )
    entries = [
        DraftHistoryEntry(
            draft_id=row.id,
            target_type=row.target_type,
            status=row.status,
            discard_reason=row.discard_reason,
            change_summary=row.change_summary,
            created_at=row.created_at.isoformat() if row.created_at else "",
        )
        for row in rows
    ]
    return DraftHistoryResponse(entries=entries)
