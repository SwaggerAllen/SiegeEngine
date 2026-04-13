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
from sqlalchemy.orm import Session

from backend.auth.routes import get_current_user
from backend.database import get_db
from backend.graph import events as ev
from backend.graph import queries
from backend.graph.expansion import (
    bootstrap_expansion_node,
    get_expansion_node,
    has_been_approved,
    pending_expansion_draft,
)
from backend.graph.handlers.feature_expansion import (
    GENERATE_FEATURE_EXPANSION_JOB_TYPE,
)
from backend.graph.handlers.feature_mint import MINT_FEATURES_JOB_TYPE
from backend.graph.handlers.requirements_generation import (
    GENERATE_REQUIREMENTS_JOB_TYPE,
)
from backend.graph.handlers.requirements_mint import MINT_REQUIREMENTS_JOB_TYPE
from backend.graph.handlers.sysarch_generation import GENERATE_SYSARCH_JOB_TYPE
from backend.graph.handlers.sysarch_mint import MINT_SYSARCH_JOB_TYPE
from backend.graph.reducer import append_event
from backend.graph.requirements import (
    bootstrap_reqs_node,
    get_reqs_node,
    pending_reqs_draft,
)
from backend.graph.requirements import has_been_approved as reqs_has_been_approved
from backend.graph.sysarch import (
    bootstrap_sysarch_node,
    get_sysarch_node,
    pending_sysarch_draft,
)
from backend.graph.sysarch import has_been_approved as sysarch_has_been_approved
from backend.models import Project, User
from backend.models.node import Draft
from backend.models.telemetry import GenerationTelemetry
from backend.pipeline import queue as pipeline_queue

logger = logging.getLogger(__name__)

router = APIRouter()


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


# ── Expansion request / response models ─────────────────────────────


class ExpansionNodeResponse(BaseModel):
    id: str
    name: str
    content: str
    updated_at: str


class ExpansionDraftResponse(BaseModel):
    id: str
    content: str
    created_at: str


class TelemetrySummary(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    model: str
    created_at: str


class ExpansionResponse(BaseModel):
    node: ExpansionNodeResponse
    pending_draft: ExpansionDraftResponse | None
    generation_status: queries.GenerationStatus
    last_error: str | None
    latest_telemetry: TelemetrySummary | None


class FeedbackRequest(BaseModel):
    feedback: str


class FeedbackResponse(BaseModel):
    job_id: str


class DraftIdRequest(BaseModel):
    draft_id: str


class ApproveResponse(BaseModel):
    node: ExpansionNodeResponse


class DiscardResponse(BaseModel):
    ok: bool


# ── Feature list response models ────────────────────────────────────


class FeatureSummary(BaseModel):
    id: str
    name: str
    content: str
    display_order: int
    group_label: str | None
    is_implicit: bool
    updated_at: str


class FeatureListResponse(BaseModel):
    features: list[FeatureSummary]


# ── Expansion endpoints ─────────────────────────────────────────────


def _require_project(db: Session, project_id: str) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def _serialize_node(node) -> ExpansionNodeResponse:
    return ExpansionNodeResponse(
        id=node.id,
        name=node.name,
        content=node.content,
        updated_at=node.updated_at.isoformat() if node.updated_at else "",
    )


def _latest_telemetry(db: Session, project_id: str, node_id: str) -> TelemetrySummary | None:
    """Return the most recent telemetry row for a node, or None."""
    from sqlalchemy import select

    row = db.execute(
        select(GenerationTelemetry)
        .where(
            GenerationTelemetry.project_id == project_id,
            GenerationTelemetry.node_id == node_id,
        )
        .order_by(GenerationTelemetry.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    if row is None:
        return None
    return TelemetrySummary(
        prompt_tokens=row.prompt_tokens,
        completion_tokens=row.completion_tokens,
        model=row.model,
        created_at=row.created_at.isoformat() if row.created_at else "",
    )


@router.get("/{project_id}/expansion", response_model=ExpansionResponse)
def get_expansion(
    project_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> ExpansionResponse:
    _require_project(db, project_id)
    node = get_expansion_node(db, project_id)
    if node is None:
        # Legacy projects created before the ``expansion`` tier shipped
        # don't have a bootstrap node. Lazily mint one on first open
        # and kick off an initial generation, so "open old project"
        # Just Works instead of surfacing a raw 404 on the dashboard.
        # This also covers any future migration or crash that leaves
        # a project in a pre-bootstrap state.
        logger.warning("Project %s has no expansion node; lazy-bootstrapping", project_id)
        bootstrap_expansion_node(db, project_id)
        db.commit()
        pipeline_queue.enqueue(
            db,
            job_type=GENERATE_FEATURE_EXPANSION_JOB_TYPE,
            payload={"project_id": project_id, "feedback": None},
        )
        node = get_expansion_node(db, project_id)
        assert node is not None, "bootstrap_expansion_node should have minted one"
    draft = pending_expansion_draft(db, project_id)
    status, last_error = queries.latest_generation_status(
        db, project_id, GENERATE_FEATURE_EXPANSION_JOB_TYPE
    )
    return ExpansionResponse(
        node=_serialize_node(node),
        pending_draft=(
            ExpansionDraftResponse(
                id=draft.id,
                content=draft.content,
                created_at=draft.created_at.isoformat() if draft.created_at else "",
            )
            if draft is not None
            else None
        ),
        generation_status=status,
        last_error=last_error,
        latest_telemetry=_latest_telemetry(db, project_id, node.id),
    )


@router.post("/{project_id}/expansion/feedback", response_model=FeedbackResponse)
def post_expansion_feedback(
    project_id: str,
    req: FeedbackRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> FeedbackResponse:
    _require_project(db, project_id)
    if get_expansion_node(db, project_id) is None:
        raise HTTPException(
            status_code=404,
            detail="Feature expansion node missing for project",
        )
    # v2 bootstrap nodes are read-only after approval: feature-layer
    # edits after that point land on individual feat_* nodes, not by
    # re-editing the expansion prose. See docs/architecture/
    # v2-rearchitecture.md §Core principle (second corollary).
    if has_been_approved(db, project_id):
        raise HTTPException(
            status_code=409,
            detail=(
                "Feature expansion is read-only after approval; "
                "further feature-layer edits happen on individual "
                "feature nodes."
            ),
        )
    feedback = (req.feedback or "").strip() or None
    job_id = pipeline_queue.enqueue(
        db,
        job_type=GENERATE_FEATURE_EXPANSION_JOB_TYPE,
        payload={"project_id": project_id, "feedback": feedback},
    )
    return FeedbackResponse(job_id=job_id)


@router.post("/{project_id}/expansion/approve", response_model=ApproveResponse)
def post_expansion_approve(
    project_id: str,
    req: DraftIdRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> ApproveResponse:
    _require_project(db, project_id)
    node = get_expansion_node(db, project_id)
    if node is None:
        raise HTTPException(
            status_code=404,
            detail="Feature expansion node missing for project",
        )
    draft = db.get(Draft, req.draft_id)
    if (
        draft is None
        or draft.project_id != project_id
        or draft.target_type != "node"
        or draft.target_id != node.id
    ):
        raise HTTPException(
            status_code=404,
            detail="Draft not found for this project's expansion",
        )
    if draft.status != "pending":
        raise HTTPException(
            status_code=409,
            detail=f"Draft is {draft.status!r}, not pending",
        )

    append_event(db, project_id, ev.DraftApproved(draft_id=req.draft_id))
    db.commit()
    db.refresh(node)

    # Approval is destructive at the child level — the content has
    # been committed to node.content, and now we mint feat_* nodes
    # from it. The mint handler runs asynchronously on the
    # pipeline worker; the response returns immediately with the
    # approved node, and the frontend polls the /features endpoint
    # to see the minted features.
    pipeline_queue.enqueue(
        db,
        job_type=MINT_FEATURES_JOB_TYPE,
        payload={"project_id": project_id},
    )

    return ApproveResponse(node=_serialize_node(node))


@router.post("/{project_id}/expansion/discard", response_model=DiscardResponse)
def post_expansion_discard(
    project_id: str,
    req: DraftIdRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> DiscardResponse:
    _require_project(db, project_id)
    node = get_expansion_node(db, project_id)
    if node is None:
        raise HTTPException(
            status_code=404,
            detail="Feature expansion node missing for project",
        )
    draft = db.get(Draft, req.draft_id)
    if (
        draft is None
        or draft.project_id != project_id
        or draft.target_type != "node"
        or draft.target_id != node.id
    ):
        raise HTTPException(
            status_code=404,
            detail="Draft not found for this project's expansion",
        )
    if draft.status != "pending":
        raise HTTPException(
            status_code=409,
            detail=f"Draft is {draft.status!r}, not pending",
        )

    append_event(db, project_id, ev.DraftDiscarded(draft_id=req.draft_id))
    db.commit()

    # Rejecting a draft is usually a step in an iteration loop, not
    # a "give up" signal. Enqueue a fresh generation so the user
    # gets a new draft to react to without having to type "try
    # again" into the feedback box. The generation handler runs
    # without prior_pending (we just discarded it) and without
    # explicit feedback, so it regenerates from scratch against
    # the input doc.
    pipeline_queue.enqueue(
        db,
        job_type=GENERATE_FEATURE_EXPANSION_JOB_TYPE,
        payload={"project_id": project_id, "feedback": None},
    )

    return DiscardResponse(ok=True)


# ── Feature list endpoint ───────────────────────────────────────────


@router.get("/{project_id}/features", response_model=FeatureListResponse)
def get_features(
    project_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> FeatureListResponse:
    """List all ``feat_*`` nodes for a project in document order.

    The list is populated by the ``v2.mint_features`` pipeline job
    after the user approves the feature expansion. Before mint
    completes, the list is empty. The frontend polls this endpoint
    while the mint is running; once features appear, it stops
    polling.
    """
    _require_project(db, project_id)
    features = queries.list_features(db, project_id)
    return FeatureListResponse(
        features=[
            FeatureSummary(
                id=f.id,
                name=f.name,
                content=f.content,
                display_order=f.display_order,
                group_label=f.group_label,
                is_implicit=f.is_implicit,
                updated_at=f.updated_at.isoformat() if f.updated_at else "",
            )
            for f in features
        ]
    )


# ── Requirements response models ────────────────────────────────────


class ReqsNodeResponse(BaseModel):
    id: str
    name: str
    content: str
    updated_at: str


class ReqsDraftResponse(BaseModel):
    id: str
    content: str
    created_at: str


class ReqsResponse(BaseModel):
    node: ReqsNodeResponse
    pending_draft: ReqsDraftResponse | None
    generation_status: queries.GenerationStatus
    last_error: str | None
    latest_telemetry: TelemetrySummary | None


class ReqsApproveResponse(BaseModel):
    node: ReqsNodeResponse


class ResponsibilitySummary(BaseModel):
    id: str
    name: str
    content: str
    display_order: int
    updated_at: str


class ResponsibilityListResponse(BaseModel):
    responsibilities: list[ResponsibilitySummary]


def _serialize_reqs_node(node) -> ReqsNodeResponse:
    return ReqsNodeResponse(
        id=node.id,
        name=node.name,
        content=node.content,
        updated_at=node.updated_at.isoformat() if node.updated_at else "",
    )


# ── Requirements endpoints ──────────────────────────────────────────


@router.get("/{project_id}/requirements", response_model=ReqsResponse)
def get_requirements(
    project_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> ReqsResponse:
    """Return the project's reqs node state — same four-state shape
    as ``GET /{project_id}/expansion``.

    Lazily bootstraps the node and enqueues its initial generation
    if it's missing, so opening a project whose feature mint
    finished before the reqs bootstrap (e.g. a replay before Phase
    3 shipped) still works without a 404.
    """
    _require_project(db, project_id)
    node = get_reqs_node(db, project_id)
    if node is None:
        logger.warning("Project %s has no reqs node; lazy-bootstrapping", project_id)
        bootstrap_reqs_node(db, project_id)
        db.commit()
        pipeline_queue.enqueue(
            db,
            job_type=GENERATE_REQUIREMENTS_JOB_TYPE,
            payload={"project_id": project_id, "feedback": None},
        )
        node = get_reqs_node(db, project_id)
        assert node is not None, "bootstrap_reqs_node should have minted one"
    draft = pending_reqs_draft(db, project_id)
    status, last_error = queries.latest_generation_status(
        db, project_id, GENERATE_REQUIREMENTS_JOB_TYPE
    )
    return ReqsResponse(
        node=_serialize_reqs_node(node),
        pending_draft=(
            ReqsDraftResponse(
                id=draft.id,
                content=draft.content,
                created_at=draft.created_at.isoformat() if draft.created_at else "",
            )
            if draft is not None
            else None
        ),
        generation_status=status,
        last_error=last_error,
        latest_telemetry=_latest_telemetry(db, project_id, node.id),
    )


@router.post("/{project_id}/requirements/feedback", response_model=FeedbackResponse)
def post_requirements_feedback(
    project_id: str,
    req: FeedbackRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> FeedbackResponse:
    _require_project(db, project_id)
    if get_reqs_node(db, project_id) is None:
        raise HTTPException(
            status_code=404,
            detail="Requirements node missing for project",
        )
    # Read-only after approval — further changes land as structural
    # edits on resp_* nodes (Phase 10), not by re-editing the prose.
    if reqs_has_been_approved(db, project_id):
        raise HTTPException(
            status_code=409,
            detail=(
                "Requirements is read-only after approval; further "
                "responsibility-layer edits happen on individual "
                "responsibility nodes."
            ),
        )
    feedback = (req.feedback or "").strip() or None
    job_id = pipeline_queue.enqueue(
        db,
        job_type=GENERATE_REQUIREMENTS_JOB_TYPE,
        payload={"project_id": project_id, "feedback": feedback},
    )
    return FeedbackResponse(job_id=job_id)


@router.post("/{project_id}/requirements/approve", response_model=ReqsApproveResponse)
def post_requirements_approve(
    project_id: str,
    req: DraftIdRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> ReqsApproveResponse:
    _require_project(db, project_id)
    node = get_reqs_node(db, project_id)
    if node is None:
        raise HTTPException(status_code=404, detail="Requirements node missing for project")
    draft = db.get(Draft, req.draft_id)
    if (
        draft is None
        or draft.project_id != project_id
        or draft.target_type != "node"
        or draft.target_id != node.id
    ):
        raise HTTPException(
            status_code=404,
            detail="Draft not found for this project's requirements",
        )
    if draft.status != "pending":
        raise HTTPException(
            status_code=409,
            detail=f"Draft is {draft.status!r}, not pending",
        )

    append_event(db, project_id, ev.DraftApproved(draft_id=req.draft_id))
    db.commit()
    db.refresh(node)

    # Approval is destructive at the child level — mint top-level
    # resp_* nodes from the approved content. Runs on the pipeline
    # worker; the frontend polls /responsibilities.
    pipeline_queue.enqueue(
        db,
        job_type=MINT_REQUIREMENTS_JOB_TYPE,
        payload={"project_id": project_id},
    )

    return ReqsApproveResponse(node=_serialize_reqs_node(node))


@router.post("/{project_id}/requirements/discard", response_model=DiscardResponse)
def post_requirements_discard(
    project_id: str,
    req: DraftIdRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> DiscardResponse:
    _require_project(db, project_id)
    node = get_reqs_node(db, project_id)
    if node is None:
        raise HTTPException(status_code=404, detail="Requirements node missing for project")
    draft = db.get(Draft, req.draft_id)
    if (
        draft is None
        or draft.project_id != project_id
        or draft.target_type != "node"
        or draft.target_id != node.id
    ):
        raise HTTPException(
            status_code=404,
            detail="Draft not found for this project's requirements",
        )
    if draft.status != "pending":
        raise HTTPException(
            status_code=409,
            detail=f"Draft is {draft.status!r}, not pending",
        )

    append_event(db, project_id, ev.DraftDiscarded(draft_id=req.draft_id))
    db.commit()

    # Mirrors /expansion/discard: reject regenerates from scratch.
    pipeline_queue.enqueue(
        db,
        job_type=GENERATE_REQUIREMENTS_JOB_TYPE,
        payload={"project_id": project_id, "feedback": None},
    )

    return DiscardResponse(ok=True)


# ── Responsibilities list endpoint ──────────────────────────────────


@router.get("/{project_id}/responsibilities", response_model=ResponsibilityListResponse)
def get_responsibilities(
    project_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> ResponsibilityListResponse:
    """List all top-level ``resp_*`` nodes for a project in document order.

    Top-level responsibilities are the ones minted by the
    ``v2.mint_requirements`` pipeline job after the user approves
    the requirements. Subresponsibilities (minted later by per-
    component subreqs handlers) have a non-null ``parent_id`` and
    are not included in this list.
    """
    _require_project(db, project_id)
    responsibilities = queries.list_top_level_responsibilities(db, project_id)
    return ResponsibilityListResponse(
        responsibilities=[
            ResponsibilitySummary(
                id=r.id,
                name=r.name,
                content=r.content,
                display_order=r.display_order,
                updated_at=r.updated_at.isoformat() if r.updated_at else "",
            )
            for r in responsibilities
        ]
    )


# ── Sysarch response models ─────────────────────────────────────────


class SysarchNodeResponse(BaseModel):
    id: str
    name: str
    content: str
    updated_at: str


class SysarchDraftResponse(BaseModel):
    id: str
    content: str
    created_at: str


class SysarchResponse(BaseModel):
    node: SysarchNodeResponse
    pending_draft: SysarchDraftResponse | None
    generation_status: queries.GenerationStatus
    last_error: str | None
    latest_telemetry: TelemetrySummary | None


class SysarchApproveResponse(BaseModel):
    node: SysarchNodeResponse


class ComponentSummary(BaseModel):
    id: str
    name: str
    kind: str  # "domain" | "presentational"
    display_order: int
    updated_at: str


class ComponentListResponse(BaseModel):
    components: list[ComponentSummary]


class PolicySummary(BaseModel):
    id: str
    name: str
    # The raw <policy>...</policy> blob stored on Node.content. The
    # frontend parses it for display; no need to double-parse on
    # every list read when the payload is small.
    content: str
    display_order: int
    updated_at: str


class PolicyListResponse(BaseModel):
    policies: list[PolicySummary]


def _serialize_sysarch_node(node) -> SysarchNodeResponse:
    return SysarchNodeResponse(
        id=node.id,
        name=node.name,
        content=node.content,
        updated_at=node.updated_at.isoformat() if node.updated_at else "",
    )


# ── Sysarch endpoints ───────────────────────────────────────────────


@router.get("/{project_id}/sysarch", response_model=SysarchResponse)
def get_sysarch(
    project_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> SysarchResponse:
    """Return the project's sysarch node state — same four-state shape
    as ``GET /{project_id}/expansion`` and ``/requirements``.

    Lazily bootstraps the sysarch node + first generation job if
    missing, so opening a project whose reqs mint finished before
    the sysarch bootstrap path shipped still works without a 404.
    """
    _require_project(db, project_id)
    node = get_sysarch_node(db, project_id)
    if node is None:
        logger.warning("Project %s has no sysarch node; lazy-bootstrapping", project_id)
        bootstrap_sysarch_node(db, project_id)
        db.commit()
        pipeline_queue.enqueue(
            db,
            job_type=GENERATE_SYSARCH_JOB_TYPE,
            payload={"project_id": project_id, "feedback": None},
        )
        node = get_sysarch_node(db, project_id)
        assert node is not None, "bootstrap_sysarch_node should have minted one"
    draft = pending_sysarch_draft(db, project_id)
    status, last_error = queries.latest_generation_status(db, project_id, GENERATE_SYSARCH_JOB_TYPE)
    return SysarchResponse(
        node=_serialize_sysarch_node(node),
        pending_draft=(
            SysarchDraftResponse(
                id=draft.id,
                content=draft.content,
                created_at=draft.created_at.isoformat() if draft.created_at else "",
            )
            if draft is not None
            else None
        ),
        generation_status=status,
        last_error=last_error,
        latest_telemetry=_latest_telemetry(db, project_id, node.id),
    )


@router.post("/{project_id}/sysarch/feedback", response_model=FeedbackResponse)
def post_sysarch_feedback(
    project_id: str,
    req: FeedbackRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> FeedbackResponse:
    _require_project(db, project_id)
    if get_sysarch_node(db, project_id) is None:
        raise HTTPException(status_code=404, detail="Sysarch node missing for project")
    # Read-only after approval. Post-approval sysarch regen is
    # deferred to Phase 11 structural edit UIs.
    if sysarch_has_been_approved(db, project_id):
        raise HTTPException(
            status_code=409,
            detail=(
                "System architecture is read-only after approval; further "
                "component-layer edits happen on individual comp_* nodes "
                "and their arch docs."
            ),
        )
    feedback = (req.feedback or "").strip() or None
    job_id = pipeline_queue.enqueue(
        db,
        job_type=GENERATE_SYSARCH_JOB_TYPE,
        payload={"project_id": project_id, "feedback": feedback},
    )
    return FeedbackResponse(job_id=job_id)


@router.post("/{project_id}/sysarch/approve", response_model=SysarchApproveResponse)
def post_sysarch_approve(
    project_id: str,
    req: DraftIdRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> SysarchApproveResponse:
    _require_project(db, project_id)
    node = get_sysarch_node(db, project_id)
    if node is None:
        raise HTTPException(status_code=404, detail="Sysarch node missing for project")
    draft = db.get(Draft, req.draft_id)
    if (
        draft is None
        or draft.project_id != project_id
        or draft.target_type != "node"
        or draft.target_id != node.id
    ):
        raise HTTPException(
            status_code=404,
            detail="Draft not found for this project's sysarch",
        )
    if draft.status != "pending":
        raise HTTPException(
            status_code=409,
            detail=f"Draft is {draft.status!r}, not pending",
        )

    append_event(db, project_id, ev.DraftApproved(draft_id=req.draft_id))
    db.commit()
    db.refresh(node)

    # Approval is destructive at the child level — enqueues the
    # sysarch mint which will produce comp_*, policy_*, edges, and
    # fan out subreqs bootstrap jobs for every top-level component.
    pipeline_queue.enqueue(
        db,
        job_type=MINT_SYSARCH_JOB_TYPE,
        payload={"project_id": project_id},
    )

    return SysarchApproveResponse(node=_serialize_sysarch_node(node))


@router.post("/{project_id}/sysarch/discard", response_model=DiscardResponse)
def post_sysarch_discard(
    project_id: str,
    req: DraftIdRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> DiscardResponse:
    _require_project(db, project_id)
    node = get_sysarch_node(db, project_id)
    if node is None:
        raise HTTPException(status_code=404, detail="Sysarch node missing for project")
    draft = db.get(Draft, req.draft_id)
    if (
        draft is None
        or draft.project_id != project_id
        or draft.target_type != "node"
        or draft.target_id != node.id
    ):
        raise HTTPException(
            status_code=404,
            detail="Draft not found for this project's sysarch",
        )
    if draft.status != "pending":
        raise HTTPException(
            status_code=409,
            detail=f"Draft is {draft.status!r}, not pending",
        )

    append_event(db, project_id, ev.DraftDiscarded(draft_id=req.draft_id))
    db.commit()

    # Mirrors the other discard routes: reject regenerates from scratch.
    pipeline_queue.enqueue(
        db,
        job_type=GENERATE_SYSARCH_JOB_TYPE,
        payload={"project_id": project_id, "feedback": None},
    )

    return DiscardResponse(ok=True)


# ── Components + policies list endpoints ────────────────────────────


@router.get("/{project_id}/components", response_model=ComponentListResponse)
def get_components(
    project_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> ComponentListResponse:
    """List all top-level ``comp_*`` nodes for a project.

    Populated by the ``v2.mint_sysarch`` pipeline job after the
    sysarch draft is approved. Before then, empty. Frontend polls
    while the mint might still be running; stops once at least one
    component is present.
    """
    _require_project(db, project_id)
    components = queries.list_top_level_components(db, project_id)
    return ComponentListResponse(
        components=[
            ComponentSummary(
                id=c.id,
                name=c.name,
                kind=c.kind,
                display_order=c.display_order,
                updated_at=c.updated_at.isoformat() if c.updated_at else "",
            )
            for c in components
        ]
    )


@router.get("/{project_id}/policies", response_model=PolicyListResponse)
def get_policies(
    project_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> PolicyListResponse:
    """List all ``policy_*`` nodes for a project.

    Includes top-level policies minted at sysarch approval and
    component-local policies minted at comparch approval (Phase 4).
    Frontend is responsible for parsing the inline ``<policy>`` XML
    blob on ``Node.content`` into structured fields for display.
    """
    _require_project(db, project_id)
    policies = queries.list_policies(db, project_id)
    return PolicyListResponse(
        policies=[
            PolicySummary(
                id=p.id,
                name=p.name,
                content=p.content,
                display_order=p.display_order,
                updated_at=p.updated_at.isoformat() if p.updated_at else "",
            )
            for p in policies
        ]
    )
