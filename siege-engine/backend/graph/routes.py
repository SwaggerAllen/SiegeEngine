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
from backend.graph.reducer import append_event
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
                updated_at=f.updated_at.isoformat() if f.updated_at else "",
            )
            for f in features
        ]
    )
