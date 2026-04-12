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

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.auth.routes import get_current_user
from backend.database import get_db
from backend.graph import events as ev
from backend.graph import queries
from backend.graph.expansion import get_expansion_node, pending_expansion_draft
from backend.graph.handlers.feature_expansion import (
    GENERATE_FEATURE_EXPANSION_JOB_TYPE,
)
from backend.graph.reducer import append_event
from backend.models import Project, User
from backend.models.node import Draft
from backend.pipeline import queue as pipeline_queue

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


class ExpansionResponse(BaseModel):
    node: ExpansionNodeResponse
    pending_draft: ExpansionDraftResponse | None
    generation_status: queries.GenerationStatus
    last_error: str | None


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


@router.get("/{project_id}/expansion", response_model=ExpansionResponse)
def get_expansion(
    project_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> ExpansionResponse:
    _require_project(db, project_id)
    node = get_expansion_node(db, project_id)
    if node is None:
        raise HTTPException(
            status_code=404,
            detail="Feature expansion node missing for project",
        )
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
