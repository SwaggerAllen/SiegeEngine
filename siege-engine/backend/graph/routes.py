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
from backend.graph import events as ev
from backend.graph import per_comp_reset, queries
from backend.graph.bootstrap_routes import (
    BootstrapTierConfig,
    bootstrap_approve,
    bootstrap_cancel,
    bootstrap_discard,
    bootstrap_feedback,
    bootstrap_get_state,
    bootstrap_prompt_preview,
    bootstrap_reset,
    bootstrap_retry_review,
)
from backend.graph.broadcast import commit_and_publish
from backend.graph.expansion import (
    bootstrap_expansion_node,
    get_expansion_node,
    has_been_approved,
    pending_expansion_draft,
)
from backend.graph.expansion import (
    collect_downstream_nodes as expansion_collect_downstream_nodes,
)
from backend.graph.fragments import FragmentKind, fragment_id
from backend.graph.handlers.comparch_generation import (
    GENERATE_COMPARCH_JOB_TYPE,
)
from backend.graph.handlers.comparch_mint import MINT_COMPARCH_JOB_TYPE
from backend.graph.handlers.fanin_generation import GENERATE_FANIN_JOB_TYPE
from backend.graph.handlers.feature_expansion import (
    GENERATE_FEATURE_EXPANSION_JOB_TYPE,
)
from backend.graph.handlers.feature_mint import MINT_FEATURES_JOB_TYPE
from backend.graph.handlers.generate_reference import GENERATE_REFERENCE_JOB_TYPE
from backend.graph.handlers.impl_generation import (
    GENERATE_IMPL_JOB_TYPE,
    on_impl_approved,
)
from backend.graph.handlers.requirements_generation import (
    GENERATE_REQUIREMENTS_JOB_TYPE,
)
from backend.graph.handlers.requirements_mint import MINT_REQUIREMENTS_JOB_TYPE
from backend.graph.handlers.subcomparch_generation import (
    GENERATE_SUBCOMPARCH_JOB_TYPE,
)
from backend.graph.handlers.subcomparch_mint import MINT_SUBCOMPARCH_JOB_TYPE
from backend.graph.handlers.subreqs_generation import (
    GENERATE_SUBREQS_JOB_TYPE,
)
from backend.graph.handlers.subreqs_mint import MINT_SUBREQS_JOB_TYPE
from backend.graph.handlers.sysarch_generation import GENERATE_SYSARCH_JOB_TYPE
from backend.graph.handlers.sysarch_mint import MINT_SYSARCH_JOB_TYPE
from backend.graph.reducer import append_event
from backend.graph.requirements import (
    bootstrap_reqs_node,
    get_reqs_node,
    pending_reqs_draft,
)
from backend.graph.requirements import (
    collect_downstream_nodes as reqs_collect_downstream_nodes,
)
from backend.graph.requirements import has_been_approved as reqs_has_been_approved
from backend.graph.subrequirements import (
    bootstrap_subreqs_node,
    get_subreqs_node,
    pending_subreqs_draft,
)
from backend.graph.subrequirements import has_been_approved as subreqs_has_been_approved
from backend.graph.sysarch import (
    bootstrap_sysarch_node,
    get_sysarch_node,
    pending_sysarch_draft,
)
from backend.graph.sysarch import (
    collect_downstream_nodes as sysarch_collect_downstream_nodes,
)
from backend.graph.sysarch import (
    collect_pending_drafts_for_nodes as sysarch_collect_pending_drafts_for_nodes,
)
from backend.graph.sysarch import has_been_approved as sysarch_has_been_approved
from backend.models import Project, User
from backend.models.node import Draft, Edge, Fragment, Node
from backend.models.telemetry import GenerationTelemetry

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
    # Phase 12 — regen-time diff "before" content. Contains the
    # most recently discarded draft's content for this target,
    # or ``None`` when no prior discarded draft exists (brand-new
    # bootstrap or first regen after approval).
    previous_draft_content: str | None = None
    generation_status: queries.GenerationStatus
    last_error: str | None
    latest_telemetry: TelemetrySummary | None
    # ISO-8601 UTC timestamp (naive) of when the currently-running
    # generation job was enqueued, or ``None`` if no generation is
    # running. Used by the frontend to render a duration clock / PST
    # start-time label while an artifact regenerates.
    generation_started_at: str | None = None
    current_attempt: int | None = None
    max_attempts: int | None = None
    failed_raw_output: str | None = None
    # Phase 8 — AI self-review fields. Populated when the tier
    # has a configured review_job_type; empty string / "idle"
    # for tiers that don't run reviews.
    review_text: str = ""
    review_status: queries.GenerationStatus = "idle"
    review_last_error: str | None = None
    review_started_at: str | None = None
    review_current_attempt: int | None = None
    review_max_attempts: int | None = None


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


class CancelResponse(BaseModel):
    """Response shape for the per-tier ``/cancel`` routes.

    ``cancelled`` is True if a queued or running job was found and
    told to stop; False if no active generation job existed (the
    user clicked stop after the job had already finished, or at a
    moment when no job was in flight). Either way the route is a
    no-op from the client's perspective — the UI just refetches and
    renders whichever state the server now reports.
    """

    cancelled: bool


class ResetResponse(BaseModel):
    """Response from a destructive bootstrap-tier reset.

    Returns counts of what was nuked so the caller can sanity-check
    that the expected amount of state was cleared, and an ``ok``
    flag for the normal happy-path check. The counts are also
    useful in logs and tests as a quick assertion on walker
    correctness.
    """

    ok: bool
    nodes_deleted: int
    drafts_discarded: int
    jobs_cancelled: int


class PromptPreviewResponse(BaseModel):
    """Rendered system + user prompts for a bootstrap tier.

    Returned by the ``/prompt-preview`` endpoints so the user can
    see exactly what the LLM would receive before hitting
    Reject & Regenerate.
    """

    system_prompt: str
    user_prompt: str


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
    """Return the most recent *generation* telemetry row for a node.

    Must exclude ``section="review"`` rows — review runs right
    after each generation and writes its own telemetry, so if the
    filter doesn't skip it the "Last gen" display shows review
    tokens (much smaller than generation tokens) instead of the
    generation's.
    """
    from sqlalchemy import select

    row = db.execute(
        select(GenerationTelemetry)
        .where(
            GenerationTelemetry.project_id == project_id,
            GenerationTelemetry.node_id == node_id,
            GenerationTelemetry.section != "review",
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


def _node_to_dict(node) -> dict:
    return {
        "id": node.id,
        "name": node.name,
        "content": node.content,
        "updated_at": node.updated_at.isoformat() if node.updated_at else "",
    }


def _draft_to_dict(draft) -> dict:
    return {
        "id": draft.id,
        "content": draft.content,
        "created_at": draft.created_at.isoformat() if draft.created_at else "",
    }


EXPANSION_CONFIG = BootstrapTierConfig(
    tier_name="Feature expansion",
    get_node=get_expansion_node,
    get_pending_draft=pending_expansion_draft,
    has_been_approved=has_been_approved,
    bootstrap_node=bootstrap_expansion_node,
    generate_job_type=GENERATE_FEATURE_EXPANSION_JOB_TYPE,
    mint_job_type=MINT_FEATURES_JOB_TYPE,
    serialize_node=_node_to_dict,
    serialize_draft=_draft_to_dict,
    feedback_readonly_detail=(
        "Feature expansion is read-only after approval; "
        "further feature-layer edits happen on individual feature nodes."
    ),
    collect_downstream_nodes=expansion_collect_downstream_nodes,
    collect_pending_drafts_for_nodes=sysarch_collect_pending_drafts_for_nodes,
    downstream_job_types=(
        "v2.generate_feature_expansion",
        "v2.mint_features",
        "v2.generate_requirements",
        "v2.mint_requirements",
        "v2.generate_sysarch",
        "v2.mint_sysarch",
        "v2.generate_subrequirements",
        "v2.mint_subrequirements",
        "v2.generate_comparch",
        "v2.mint_comparch",
        "v2.generate_subcomparch",
        "v2.mint_subcomparch",
        "v2.apply_top_level_policies",
        "v2.apply_component_local_policies",
    ),
    additional_nodes_to_clear=lambda db, pid: [
        get_reqs_node(db, pid),
        get_sysarch_node(db, pid),
    ],
    additional_drafts_to_discard=lambda db, pid: [
        pending_reqs_draft(db, pid),
        pending_sysarch_draft(db, pid),
    ],
    review_job_type="v2.review_expansion",
)


@router.get("/{project_id}/expansion", response_model=ExpansionResponse)
def get_expansion(
    project_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> ExpansionResponse:
    return ExpansionResponse(
        **bootstrap_get_state(db, project_id, (), EXPANSION_CONFIG, _require_project)
    )


@router.post("/{project_id}/expansion/feedback", response_model=FeedbackResponse)
def post_expansion_feedback(
    project_id: str,
    req: FeedbackRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> FeedbackResponse:
    return FeedbackResponse(
        **bootstrap_feedback(db, project_id, (), req.feedback, EXPANSION_CONFIG, _require_project)
    )


@router.post("/{project_id}/expansion/approve", response_model=ApproveResponse)
def post_expansion_approve(
    project_id: str,
    req: DraftIdRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> ApproveResponse:
    result = bootstrap_approve(db, project_id, (), req.draft_id, EXPANSION_CONFIG, _require_project)
    return ApproveResponse(node=ExpansionNodeResponse(**result["node"]))


@router.post("/{project_id}/expansion/discard", response_model=DiscardResponse)
def post_expansion_discard(
    project_id: str,
    req: DraftIdRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> DiscardResponse:
    return DiscardResponse(
        **bootstrap_discard(db, project_id, (), req.draft_id, EXPANSION_CONFIG, _require_project)
    )


@router.post("/{project_id}/expansion/cancel", response_model=CancelResponse)
def post_expansion_cancel(
    project_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> CancelResponse:
    return CancelResponse(
        **bootstrap_cancel(db, project_id, (), EXPANSION_CONFIG, _require_project)
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
    previous_draft_content: str | None = None
    generation_status: queries.GenerationStatus
    last_error: str | None
    latest_telemetry: TelemetrySummary | None
    generation_started_at: str | None = None
    current_attempt: int | None = None
    max_attempts: int | None = None
    failed_raw_output: str | None = None
    # Phase 8 — AI self-review fields. Populated when the tier
    # has a configured review_job_type; empty string / "idle"
    # for tiers that don't run reviews.
    review_text: str = ""
    review_status: queries.GenerationStatus = "idle"
    review_last_error: str | None = None
    review_started_at: str | None = None
    review_current_attempt: int | None = None
    review_max_attempts: int | None = None


class ReqsApproveResponse(BaseModel):
    node: ReqsNodeResponse


def _serialize_reqs_node(node) -> ReqsNodeResponse:
    return ReqsNodeResponse(
        id=node.id,
        name=node.name,
        content=node.content,
        updated_at=node.updated_at.isoformat() if node.updated_at else "",
    )


# ── Requirements endpoints ──────────────────────────────────────────


REQUIREMENTS_CONFIG = BootstrapTierConfig(
    tier_name="Requirements",
    get_node=get_reqs_node,
    get_pending_draft=pending_reqs_draft,
    has_been_approved=reqs_has_been_approved,
    bootstrap_node=bootstrap_reqs_node,
    generate_job_type=GENERATE_REQUIREMENTS_JOB_TYPE,
    mint_job_type=MINT_REQUIREMENTS_JOB_TYPE,
    serialize_node=_node_to_dict,
    serialize_draft=_draft_to_dict,
    feedback_readonly_detail=(
        "Requirements is read-only after approval; further "
        "responsibility-layer edits happen on individual "
        "responsibility nodes."
    ),
    collect_downstream_nodes=reqs_collect_downstream_nodes,
    collect_pending_drafts_for_nodes=sysarch_collect_pending_drafts_for_nodes,
    downstream_job_types=(
        "v2.generate_requirements",
        "v2.mint_requirements",
        "v2.generate_sysarch",
        "v2.mint_sysarch",
        "v2.generate_subrequirements",
        "v2.mint_subrequirements",
        "v2.generate_comparch",
        "v2.mint_comparch",
        "v2.generate_subcomparch",
        "v2.mint_subcomparch",
        "v2.apply_top_level_policies",
        "v2.apply_component_local_policies",
    ),
    additional_nodes_to_clear=lambda db, pid: [get_sysarch_node(db, pid)],
    additional_drafts_to_discard=lambda db, pid: [pending_sysarch_draft(db, pid)],
    review_job_type="v2.review_requirements",
)


@router.get("/{project_id}/requirements", response_model=ReqsResponse)
def get_requirements(
    project_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> ReqsResponse:
    return ReqsResponse(
        **bootstrap_get_state(db, project_id, (), REQUIREMENTS_CONFIG, _require_project)
    )


@router.post("/{project_id}/requirements/feedback", response_model=FeedbackResponse)
def post_requirements_feedback(
    project_id: str,
    req: FeedbackRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> FeedbackResponse:
    return FeedbackResponse(
        **bootstrap_feedback(
            db,
            project_id,
            (),
            req.feedback,
            REQUIREMENTS_CONFIG,
            _require_project,
        )
    )


@router.post("/{project_id}/requirements/approve", response_model=ReqsApproveResponse)
def post_requirements_approve(
    project_id: str,
    req: DraftIdRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> ReqsApproveResponse:
    result = bootstrap_approve(
        db, project_id, (), req.draft_id, REQUIREMENTS_CONFIG, _require_project
    )
    return ReqsApproveResponse(node=ReqsNodeResponse(**result["node"]))


@router.post("/{project_id}/requirements/discard", response_model=DiscardResponse)
def post_requirements_discard(
    project_id: str,
    req: DraftIdRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> DiscardResponse:
    return DiscardResponse(
        **bootstrap_discard(db, project_id, (), req.draft_id, REQUIREMENTS_CONFIG, _require_project)
    )


@router.post("/{project_id}/requirements/cancel", response_model=CancelResponse)
def post_requirements_cancel(
    project_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> CancelResponse:
    return CancelResponse(
        **bootstrap_cancel(db, project_id, (), REQUIREMENTS_CONFIG, _require_project)
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
    previous_draft_content: str | None = None
    generation_status: queries.GenerationStatus
    last_error: str | None
    latest_telemetry: TelemetrySummary | None
    generation_started_at: str | None = None
    current_attempt: int | None = None
    max_attempts: int | None = None
    failed_raw_output: str | None = None
    # Phase 8 — AI self-review fields. Populated when the tier
    # has a configured review_job_type; empty string / "idle"
    # for tiers that don't run reviews.
    review_text: str = ""
    review_status: queries.GenerationStatus = "idle"
    review_last_error: str | None = None
    review_started_at: str | None = None
    review_current_attempt: int | None = None
    review_max_attempts: int | None = None


class SysarchApproveResponse(BaseModel):
    node: SysarchNodeResponse


def _serialize_sysarch_node(node) -> SysarchNodeResponse:
    return SysarchNodeResponse(
        id=node.id,
        name=node.name,
        content=node.content,
        updated_at=node.updated_at.isoformat() if node.updated_at else "",
    )


# ── Sysarch endpoints ───────────────────────────────────────────────


SYSARCH_CONFIG = BootstrapTierConfig(
    tier_name="System architecture",
    get_node=get_sysarch_node,
    get_pending_draft=pending_sysarch_draft,
    has_been_approved=sysarch_has_been_approved,
    bootstrap_node=bootstrap_sysarch_node,
    generate_job_type=GENERATE_SYSARCH_JOB_TYPE,
    mint_job_type=MINT_SYSARCH_JOB_TYPE,
    serialize_node=_node_to_dict,
    serialize_draft=_draft_to_dict,
    feedback_readonly_detail=(
        "System architecture is read-only after approval; further "
        "component-layer edits happen on individual comp_* nodes "
        "and their arch docs."
    ),
    collect_downstream_nodes=sysarch_collect_downstream_nodes,
    collect_pending_drafts_for_nodes=sysarch_collect_pending_drafts_for_nodes,
    downstream_job_types=(
        "v2.generate_sysarch",
        "v2.mint_sysarch",
        "v2.generate_subrequirements",
        "v2.mint_subrequirements",
        "v2.generate_comparch",
        "v2.mint_comparch",
        "v2.generate_subcomparch",
        "v2.mint_subcomparch",
        "v2.apply_top_level_policies",
        "v2.apply_component_local_policies",
    ),
    review_job_type="v2.review_sysarch",
)


@router.get("/{project_id}/sysarch", response_model=SysarchResponse)
def get_sysarch(
    project_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> SysarchResponse:
    return SysarchResponse(
        **bootstrap_get_state(db, project_id, (), SYSARCH_CONFIG, _require_project)
    )


@router.post("/{project_id}/sysarch/feedback", response_model=FeedbackResponse)
def post_sysarch_feedback(
    project_id: str,
    req: FeedbackRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> FeedbackResponse:
    return FeedbackResponse(
        **bootstrap_feedback(
            db,
            project_id,
            (),
            req.feedback,
            SYSARCH_CONFIG,
            _require_project,
        )
    )


@router.post("/{project_id}/sysarch/approve", response_model=SysarchApproveResponse)
def post_sysarch_approve(
    project_id: str,
    req: DraftIdRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> SysarchApproveResponse:
    result = bootstrap_approve(
        db,
        project_id,
        (),
        req.draft_id,
        SYSARCH_CONFIG,
        _require_project,
    )
    return SysarchApproveResponse(node=SysarchNodeResponse(**result["node"]))


@router.post("/{project_id}/sysarch/discard", response_model=DiscardResponse)
def post_sysarch_discard(
    project_id: str,
    req: DraftIdRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> DiscardResponse:
    return DiscardResponse(
        **bootstrap_discard(
            db,
            project_id,
            (),
            req.draft_id,
            SYSARCH_CONFIG,
            _require_project,
        )
    )


@router.post("/{project_id}/sysarch/cancel", response_model=CancelResponse)
def post_sysarch_cancel(
    project_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> CancelResponse:
    return CancelResponse(**bootstrap_cancel(db, project_id, (), SYSARCH_CONFIG, _require_project))


@router.post("/{project_id}/sysarch/reset", response_model=ResetResponse)
def post_sysarch_reset(
    project_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> ResetResponse:
    return ResetResponse(**bootstrap_reset(db, project_id, (), SYSARCH_CONFIG, _require_project))


@router.post("/{project_id}/sysarch/review/retry", response_model=FeedbackResponse)
def post_sysarch_review_retry(
    project_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> FeedbackResponse:
    return FeedbackResponse(
        **bootstrap_retry_review(db, project_id, (), SYSARCH_CONFIG, _require_project)
    )


# ── Prompt preview endpoints ─────────────────────────────────────────


class PromptPreviewRequest(BaseModel):
    feedback: str = ""


def _expansion_prompt_preview(
    db: Session,
    project_id: str,
    feedback: str,
) -> tuple[str, str]:
    from backend.graph.prompts.feature_expansion import render_system_prompt, render_user_prompt
    from backend.models.input_document import InputDocument

    node = get_expansion_node(db, project_id)
    pending = pending_expansion_draft(db, project_id)
    input_doc_row = (
        db.query(InputDocument)
        .filter(InputDocument.project_id == project_id, InputDocument.doc_type == "project_doc")
        .order_by(InputDocument.created_at.desc())
        .first()
    )
    fb = feedback.strip() or None
    return (
        render_system_prompt(),
        render_user_prompt(
            input_doc=(input_doc_row.content or "") if input_doc_row else "",
            prior_approved=node.content or None if node else None,
            prior_pending=pending.content if pending else None,
            feedback=fb,
        ),
    )


EXPANSION_CONFIG.render_prompt_preview = _expansion_prompt_preview


@router.post("/{project_id}/expansion/prompt-preview", response_model=PromptPreviewResponse)
def post_expansion_prompt_preview(
    project_id: str,
    req: PromptPreviewRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> PromptPreviewResponse:
    return PromptPreviewResponse(
        **bootstrap_prompt_preview(
            db,
            project_id,
            (),
            req.feedback,
            EXPANSION_CONFIG,
            _require_project,
        )
    )


def _requirements_prompt_preview(
    db: Session,
    project_id: str,
    feedback: str,
) -> tuple[str, str]:
    from backend.graph.prompts.requirements import (
        format_features_summary,
        render_system_prompt,
        render_user_prompt,
    )
    from backend.graph.vocabulary import render_vocab_summary_all
    from backend.models.input_document import InputDocument

    node = get_reqs_node(db, project_id)
    pending = pending_reqs_draft(db, project_id)
    feature_rows = (
        db.query(Node)
        .filter(Node.project_id == project_id, Node.tier == "feat")
        .order_by(Node.display_order, Node.created_at)
        .all()
    )
    features_summary = format_features_summary(
        [
            {
                "id": f.id,
                "name": f.name,
                "content": f.content,
                "group_label": f.group_label,
                "is_implicit": f.is_implicit,
            }
            for f in feature_rows
        ]
    )
    vocab_summary = render_vocab_summary_all(db, project_id)
    input_doc_row = (
        db.query(InputDocument)
        .filter(InputDocument.project_id == project_id, InputDocument.doc_type == "project_doc")
        .order_by(InputDocument.created_at.desc())
        .first()
    )
    fb = feedback.strip() or None
    return (
        render_system_prompt(),
        render_user_prompt(
            features_summary=features_summary,
            prior_approved=node.content or None if node else None,
            prior_pending=pending.content if pending else None,
            feedback=fb,
            vocab_summary=vocab_summary,
            input_doc=(input_doc_row.content or "") if input_doc_row else "",
        ),
    )


REQUIREMENTS_CONFIG.render_prompt_preview = _requirements_prompt_preview


@router.post("/{project_id}/requirements/prompt-preview", response_model=PromptPreviewResponse)
def post_reqs_prompt_preview(
    project_id: str,
    req: PromptPreviewRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> PromptPreviewResponse:
    return PromptPreviewResponse(
        **bootstrap_prompt_preview(
            db,
            project_id,
            (),
            req.feedback,
            REQUIREMENTS_CONFIG,
            _require_project,
        )
    )


def _sysarch_prompt_preview(
    db: Session,
    project_id: str,
    feedback: str,
) -> tuple[str, str]:
    from backend.graph.prompts.requirements import format_features_summary
    from backend.graph.prompts.sysarch import (
        format_reqs_summary,
        render_system_prompt,
        render_user_prompt,
    )
    from backend.graph.vocabulary import render_vocab_summary_all
    from backend.models.input_document import InputDocument

    node = get_sysarch_node(db, project_id)
    pending = pending_sysarch_draft(db, project_id)
    feature_rows = (
        db.query(Node)
        .filter(Node.project_id == project_id, Node.tier == "feat")
        .order_by(Node.display_order, Node.created_at)
        .all()
    )
    features_summary = format_features_summary(
        [
            {
                "id": f.id,
                "name": f.name,
                "content": f.content,
                "group_label": f.group_label,
                "is_implicit": f.is_implicit,
            }
            for f in feature_rows
        ]
    )
    resp_rows = (
        db.query(Node)
        .filter(Node.project_id == project_id, Node.tier == "resp", Node.parent_id.is_(None))
        .order_by(Node.display_order, Node.created_at)
        .all()
    )
    reqs_summary = format_reqs_summary(
        [{"id": r.id, "name": r.name, "content": r.content} for r in resp_rows]
    )
    vocab_summary = render_vocab_summary_all(db, project_id)
    input_doc_row = (
        db.query(InputDocument)
        .filter(InputDocument.project_id == project_id, InputDocument.doc_type == "project_doc")
        .order_by(InputDocument.created_at.desc())
        .first()
    )
    fb = feedback.strip() or None
    return (
        render_system_prompt(),
        render_user_prompt(
            features_summary=features_summary,
            reqs_summary=reqs_summary,
            prior_approved=node.content or None if node else None,
            prior_pending=pending.content if pending else None,
            feedback=fb,
            vocab_summary=vocab_summary,
            input_doc=(input_doc_row.content or "") if input_doc_row else "",
        ),
    )


SYSARCH_CONFIG.render_prompt_preview = _sysarch_prompt_preview


@router.post("/{project_id}/sysarch/prompt-preview", response_model=PromptPreviewResponse)
def post_sysarch_prompt_preview(
    project_id: str,
    req: PromptPreviewRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> PromptPreviewResponse:
    return PromptPreviewResponse(
        **bootstrap_prompt_preview(
            db,
            project_id,
            (),
            req.feedback,
            SYSARCH_CONFIG,
            _require_project,
        )
    )


# ── Expansion reset ──────────────────────────────────────────────────


@router.post("/{project_id}/expansion/reset", response_model=ResetResponse)
def post_expansion_reset(
    project_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> ResetResponse:
    return ResetResponse(**bootstrap_reset(db, project_id, (), EXPANSION_CONFIG, _require_project))


@router.post("/{project_id}/expansion/review/retry", response_model=FeedbackResponse)
def post_expansion_review_retry(
    project_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> FeedbackResponse:
    return FeedbackResponse(
        **bootstrap_retry_review(db, project_id, (), EXPANSION_CONFIG, _require_project)
    )


# ── Requirements reset ───────────────────────────────────────────────


@router.post("/{project_id}/requirements/reset", response_model=ResetResponse)
def post_reqs_reset(
    project_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> ResetResponse:
    return ResetResponse(
        **bootstrap_reset(db, project_id, (), REQUIREMENTS_CONFIG, _require_project)
    )


@router.post("/{project_id}/requirements/review/retry", response_model=FeedbackResponse)
def post_reqs_review_retry(
    project_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> FeedbackResponse:
    return FeedbackResponse(
        **bootstrap_retry_review(db, project_id, (), REQUIREMENTS_CONFIG, _require_project)
    )


# ── Subreqs response models ─────────────────────────────────────────


class SubreqsNodeResponse(BaseModel):
    id: str
    name: str
    content: str
    updated_at: str


class SubreqsDraftResponse(BaseModel):
    id: str
    content: str
    created_at: str


class SubreqsResponse(BaseModel):
    node: SubreqsNodeResponse
    pending_draft: SubreqsDraftResponse | None
    previous_draft_content: str | None = None
    generation_status: queries.GenerationStatus
    last_error: str | None
    latest_telemetry: TelemetrySummary | None
    generation_started_at: str | None = None
    current_attempt: int | None = None
    max_attempts: int | None = None
    failed_raw_output: str | None = None
    # Phase 8 — AI self-review fields. Populated when the tier
    # has a configured review_job_type; empty string / "idle"
    # for tiers that don't run reviews.
    review_text: str = ""
    review_status: queries.GenerationStatus = "idle"
    review_last_error: str | None = None
    review_started_at: str | None = None
    review_current_attempt: int | None = None
    review_max_attempts: int | None = None


class SubreqsApproveResponse(BaseModel):
    node: SubreqsNodeResponse


def _serialize_subreqs_node(node) -> SubreqsNodeResponse:
    return SubreqsNodeResponse(
        id=node.id,
        name=node.name,
        content=node.content,
        updated_at=node.updated_at.isoformat() if node.updated_at else "",
    )


def _require_top_level_comp(db: Session, project_id: str, comp_id: str) -> Node:
    """404 unless ``comp_id`` is a top-level ``comp_*`` in the project.

    Used by the per-component subreqs routes to validate the
    ``comp_id`` path parameter before dispatching. Rejects
    unknown IDs, IDs belonging to other projects, subcomponent
    IDs (``parent_id`` is a comp), and non-comp tier nodes.
    """
    node = db.get(Node, comp_id)
    if node is None or node.project_id != project_id:
        raise HTTPException(status_code=404, detail="Component not found")
    if node.tier != "comp":
        raise HTTPException(status_code=404, detail="Not a component")
    if node.parent_id is not None:
        # Phase 3 subreqs is per top-level comp only. Subcomponents
        # get their own arch doc flow in Phase 4; they don't have
        # their own subreqs.
        raise HTTPException(status_code=404, detail="Subreqs are per top-level component only")
    return node


# ── Subreqs endpoints (per-component scoping) ───────────────────────


SUBREQS_CONFIG = BootstrapTierConfig(
    tier_name="Subrequirements",
    get_node=get_subreqs_node,
    get_pending_draft=pending_subreqs_draft,
    has_been_approved=subreqs_has_been_approved,
    bootstrap_node=bootstrap_subreqs_node,
    generate_job_type=GENERATE_SUBREQS_JOB_TYPE,
    mint_job_type=MINT_SUBREQS_JOB_TYPE,
    serialize_node=_node_to_dict,
    serialize_draft=_draft_to_dict,
    feedback_readonly_detail=(
        "Subrequirements is read-only after approval; further "
        "subresponsibility-layer edits happen via individual "
        "subresp nodes and structural edit UIs."
    ),
    collect_downstream_nodes=per_comp_reset.collect_downstream_nodes_subreqs,
    collect_pending_drafts_for_nodes=per_comp_reset.collect_pending_drafts_for_nodes,
    downstream_job_types=per_comp_reset.subreqs_downstream_job_types(),
    additional_nodes_to_clear=per_comp_reset.additional_nodes_to_clear_subreqs,
    review_job_type="v2.review_subreqs",
)


@router.get(
    "/{project_id}/components/{comp_id}/subrequirements",
    response_model=SubreqsResponse,
)
def get_subreqs(
    project_id: str,
    comp_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> SubreqsResponse:
    _require_top_level_comp(db, project_id, comp_id)
    return SubreqsResponse(
        **bootstrap_get_state(
            db,
            project_id,
            (comp_id,),
            SUBREQS_CONFIG,
            _require_project,
        )
    )


@router.post(
    "/{project_id}/components/{comp_id}/subrequirements/feedback",
    response_model=FeedbackResponse,
)
def post_subreqs_feedback(
    project_id: str,
    comp_id: str,
    req: FeedbackRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> FeedbackResponse:
    _require_top_level_comp(db, project_id, comp_id)
    return FeedbackResponse(
        **bootstrap_feedback(
            db,
            project_id,
            (comp_id,),
            req.feedback,
            SUBREQS_CONFIG,
            _require_project,
        )
    )


@router.post(
    "/{project_id}/components/{comp_id}/subrequirements/approve",
    response_model=SubreqsApproveResponse,
)
def post_subreqs_approve(
    project_id: str,
    comp_id: str,
    req: DraftIdRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> SubreqsApproveResponse:
    _require_top_level_comp(db, project_id, comp_id)
    result = bootstrap_approve(
        db,
        project_id,
        (comp_id,),
        req.draft_id,
        SUBREQS_CONFIG,
        _require_project,
    )
    return SubreqsApproveResponse(node=SubreqsNodeResponse(**result["node"]))


@router.post(
    "/{project_id}/components/{comp_id}/subrequirements/discard",
    response_model=DiscardResponse,
)
def post_subreqs_discard(
    project_id: str,
    comp_id: str,
    req: DraftIdRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> DiscardResponse:
    _require_top_level_comp(db, project_id, comp_id)
    return DiscardResponse(
        **bootstrap_discard(
            db,
            project_id,
            (comp_id,),
            req.draft_id,
            SUBREQS_CONFIG,
            _require_project,
        )
    )


@router.post(
    "/{project_id}/components/{comp_id}/subrequirements/cancel",
    response_model=CancelResponse,
)
def post_subreqs_cancel(
    project_id: str,
    comp_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> CancelResponse:
    _require_top_level_comp(db, project_id, comp_id)
    return CancelResponse(
        **bootstrap_cancel(
            db,
            project_id,
            (comp_id,),
            SUBREQS_CONFIG,
            _require_project,
        )
    )


@router.post(
    "/{project_id}/components/{comp_id}/subrequirements/reset",
    response_model=ResetResponse,
)
def post_subreqs_reset(
    project_id: str,
    comp_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> ResetResponse:
    _require_top_level_comp(db, project_id, comp_id)
    return ResetResponse(
        **bootstrap_reset(
            db,
            project_id,
            (comp_id,),
            SUBREQS_CONFIG,
            _require_project,
        )
    )


@router.post(
    "/{project_id}/components/{comp_id}/subrequirements/review/retry",
    response_model=FeedbackResponse,
)
def post_subreqs_review_retry(
    project_id: str,
    comp_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> FeedbackResponse:
    """Manually re-enqueue the AI review for this subreqs draft."""
    _require_top_level_comp(db, project_id, comp_id)
    return FeedbackResponse(
        **bootstrap_retry_review(
            db,
            project_id,
            (comp_id,),
            SUBREQS_CONFIG,
            _require_project,
        )
    )


# ── Comparch response models ───────────────────────────────────────


class ComparchNodeResponse(BaseModel):
    id: str
    name: str
    content: str
    updated_at: str


class ComparchDraftResponse(BaseModel):
    id: str
    content: str
    created_at: str


class ComparchResponse(BaseModel):
    node: ComparchNodeResponse
    pending_draft: ComparchDraftResponse | None
    previous_draft_content: str | None = None
    generation_status: queries.GenerationStatus
    last_error: str | None
    latest_telemetry: TelemetrySummary | None
    generation_started_at: str | None = None
    current_attempt: int | None = None
    max_attempts: int | None = None
    failed_raw_output: str | None = None
    # Phase 8 — AI self-review fields. Populated when the tier
    # has a configured review_job_type; empty string / "idle"
    # for tiers that don't run reviews.
    review_text: str = ""
    review_status: queries.GenerationStatus = "idle"
    review_last_error: str | None = None
    review_started_at: str | None = None
    review_current_attempt: int | None = None
    review_max_attempts: int | None = None


class ComparchApproveResponse(BaseModel):
    node: ComparchNodeResponse


def _serialize_comparch_node(node) -> ComparchNodeResponse:
    return ComparchNodeResponse(
        id=node.id,
        name=node.name,
        content=node.content or "",
        updated_at=node.updated_at.isoformat() if node.updated_at else "",
    )


# ── Comparch endpoints (per-component scoping) ─────────────────────


def _get_comp_node(db: Session, project_id: str, comp_id: str) -> Node | None:
    return _require_top_level_comp(db, project_id, comp_id)


def _pending_comparch_draft(db: Session, project_id: str, comp_id: str) -> Draft | None:
    return db.execute(
        select(Draft).where(
            Draft.project_id == project_id,
            Draft.target_type == "node",
            Draft.target_id == comp_id,
            Draft.status == "pending",
        )
    ).scalar_one_or_none()


def _comparch_approved(db: Session, project_id: str, comp_id: str) -> bool:
    node = db.get(Node, comp_id)
    return bool(node and (node.content or "").strip())


COMPARCH_CONFIG = BootstrapTierConfig(
    tier_name="Component architecture",
    get_node=_get_comp_node,
    get_pending_draft=_pending_comparch_draft,
    has_been_approved=_comparch_approved,
    generate_job_type=GENERATE_COMPARCH_JOB_TYPE,
    mint_job_type=MINT_COMPARCH_JOB_TYPE,
    serialize_node=_node_to_dict,
    serialize_draft=_draft_to_dict,
    feedback_readonly_detail=(
        "Component architecture is read-only after approval; "
        "further edits happen via individual comp_* / policy_* "
        "nodes and the structural-edit UIs coming in Phase 11."
    ),
    collect_downstream_nodes=per_comp_reset.collect_downstream_nodes_comparch,
    collect_pending_drafts_for_nodes=per_comp_reset.collect_pending_drafts_for_nodes,
    downstream_job_types=per_comp_reset.comparch_downstream_job_types(),
    review_job_type="v2.review_comparch",
)


@router.get(
    "/{project_id}/components/{comp_id}/comparch",
    response_model=ComparchResponse,
)
def get_comparch(
    project_id: str,
    comp_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> ComparchResponse:
    return ComparchResponse(
        **bootstrap_get_state(
            db,
            project_id,
            (comp_id,),
            COMPARCH_CONFIG,
            _require_project,
        )
    )


@router.post(
    "/{project_id}/components/{comp_id}/comparch/feedback",
    response_model=FeedbackResponse,
)
def post_comparch_feedback(
    project_id: str,
    comp_id: str,
    req: FeedbackRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> FeedbackResponse:
    return FeedbackResponse(
        **bootstrap_feedback(
            db,
            project_id,
            (comp_id,),
            req.feedback,
            COMPARCH_CONFIG,
            _require_project,
        )
    )


@router.post(
    "/{project_id}/components/{comp_id}/comparch/approve",
    response_model=ComparchApproveResponse,
)
def post_comparch_approve(
    project_id: str,
    comp_id: str,
    req: DraftIdRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> ComparchApproveResponse:
    result = bootstrap_approve(
        db,
        project_id,
        (comp_id,),
        req.draft_id,
        COMPARCH_CONFIG,
        _require_project,
    )
    return ComparchApproveResponse(node=ComparchNodeResponse(**result["node"]))


@router.post(
    "/{project_id}/components/{comp_id}/comparch/discard",
    response_model=DiscardResponse,
)
def post_comparch_discard(
    project_id: str,
    comp_id: str,
    req: DraftIdRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> DiscardResponse:
    return DiscardResponse(
        **bootstrap_discard(
            db,
            project_id,
            (comp_id,),
            req.draft_id,
            COMPARCH_CONFIG,
            _require_project,
        )
    )


@router.post(
    "/{project_id}/components/{comp_id}/comparch/cancel",
    response_model=CancelResponse,
)
def post_comparch_cancel(
    project_id: str,
    comp_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> CancelResponse:
    return CancelResponse(
        **bootstrap_cancel(
            db,
            project_id,
            (comp_id,),
            COMPARCH_CONFIG,
            _require_project,
        )
    )


@router.post(
    "/{project_id}/components/{comp_id}/comparch/reset",
    response_model=ResetResponse,
)
def post_comparch_reset(
    project_id: str,
    comp_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> ResetResponse:
    _require_top_level_comp(db, project_id, comp_id)
    return ResetResponse(
        **bootstrap_reset(
            db,
            project_id,
            (comp_id,),
            COMPARCH_CONFIG,
            _require_project,
        )
    )


@router.post(
    "/{project_id}/components/{comp_id}/comparch/review/retry",
    response_model=FeedbackResponse,
)
def post_comparch_review_retry(
    project_id: str,
    comp_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> FeedbackResponse:
    _require_top_level_comp(db, project_id, comp_id)
    return FeedbackResponse(
        **bootstrap_retry_review(
            db,
            project_id,
            (comp_id,),
            COMPARCH_CONFIG,
            _require_project,
        )
    )


# ── Subcomparch response models (Phase 5) ──────────────────────────


class SubcomparchNodeResponse(BaseModel):
    id: str
    name: str
    parent_id: str
    content: str
    updated_at: str


class SubcomparchDraftResponse(BaseModel):
    id: str
    content: str
    created_at: str


class SubcomparchResponse(BaseModel):
    node: SubcomparchNodeResponse
    pending_draft: SubcomparchDraftResponse | None
    previous_draft_content: str | None = None
    generation_status: queries.GenerationStatus
    last_error: str | None
    latest_telemetry: TelemetrySummary | None
    generation_started_at: str | None = None
    current_attempt: int | None = None
    max_attempts: int | None = None
    failed_raw_output: str | None = None
    # Phase 8 — AI self-review fields. Populated when the tier
    # has a configured review_job_type; empty string / "idle"
    # for tiers that don't run reviews.
    review_text: str = ""
    review_status: queries.GenerationStatus = "idle"
    review_last_error: str | None = None
    review_started_at: str | None = None
    review_current_attempt: int | None = None
    review_max_attempts: int | None = None


class SubcomparchApproveResponse(BaseModel):
    node: SubcomparchNodeResponse


def _serialize_subcomparch_node(node: Node, parent_comp_id: str) -> SubcomparchNodeResponse:
    return SubcomparchNodeResponse(
        id=node.id,
        name=node.name,
        # parent_comp_id comes from the URL path and is validated
        # against ``node.parent_id`` in ``_require_subcomponent``, so
        # it's the same value but typed as ``str`` (not ``str | None``)
        # which satisfies Pydantic without a redundant None check.
        parent_id=parent_comp_id,
        content=node.content or "",
        updated_at=node.updated_at.isoformat() if node.updated_at else "",
    )


def _require_subcomponent(db: Session, project_id: str, parent_comp_id: str, sub_id: str) -> Node:
    """404 unless ``sub_id`` is a subcomponent of ``parent_comp_id``.

    Per-subcomponent routes carry both the parent top-level comp
    ID and the sub ID in the URL path so the client has a clear
    navigation trail (``/components/{parent}/subcomponents/{sub}``).
    This helper validates both:

    - The parent must be a top-level comp in the project.
    - The sub must be a comp in the project with
      ``parent_id == parent_comp_id``.

    Raises ``HTTPException(404)`` for any mismatch (unknown
    parent, unknown sub, parent/sub cross-project confusion,
    sub whose parent_id doesn't match the URL parent).
    """
    _require_top_level_comp(db, project_id, parent_comp_id)
    sub = db.get(Node, sub_id)
    if sub is None or sub.project_id != project_id:
        raise HTTPException(status_code=404, detail="Subcomponent not found")
    if sub.tier != "comp":
        raise HTTPException(status_code=404, detail="Not a component")
    if sub.parent_id != parent_comp_id:
        raise HTTPException(
            status_code=404,
            detail="Subcomponent parent does not match the URL parent component",
        )
    return sub


# ── Subcomparch endpoints (per-subcomponent scoping) ───────────────


def _node_to_dict_with_parent(node) -> dict:
    d = _node_to_dict(node)
    d["parent_id"] = node.parent_id or ""
    return d


def _get_sub_node(db: Session, project_id: str, sub_id: str) -> Node | None:
    sub = db.get(Node, sub_id)
    if sub is None or sub.project_id != project_id or sub.tier != "comp":
        return None
    return sub


def _pending_subcomparch_draft(
    db: Session,
    project_id: str,
    sub_id: str,
) -> Draft | None:
    return db.execute(
        select(Draft).where(
            Draft.project_id == project_id,
            Draft.target_type == "node",
            Draft.target_id == sub_id,
            Draft.status == "pending",
        )
    ).scalar_one_or_none()


def _subcomparch_approved(db: Session, project_id: str, sub_id: str) -> bool:
    node = db.get(Node, sub_id)
    return bool(node and (node.content or "").strip())


SUBCOMPARCH_CONFIG = BootstrapTierConfig(
    tier_name="Subcomponent architecture",
    get_node=_get_sub_node,
    get_pending_draft=_pending_subcomparch_draft,
    has_been_approved=_subcomparch_approved,
    generate_job_type=GENERATE_SUBCOMPARCH_JOB_TYPE,
    mint_job_type=MINT_SUBCOMPARCH_JOB_TYPE,
    serialize_node=_node_to_dict_with_parent,
    serialize_draft=_draft_to_dict,
    feedback_readonly_detail=(
        "Subcomponent architecture is read-only after approval; "
        "further edits happen via the structural-edit UIs "
        "coming in Phase 11."
    ),
    collect_downstream_nodes=per_comp_reset.collect_downstream_nodes_subcomparch,
    collect_pending_drafts_for_nodes=per_comp_reset.collect_pending_drafts_for_nodes,
    downstream_job_types=per_comp_reset.subcomparch_downstream_job_types(),
    review_job_type="v2.review_subcomparch",
)


@router.get(
    "/{project_id}/components/{parent_comp_id}/subcomponents/{sub_id}/subcomparch",
    response_model=SubcomparchResponse,
)
def get_subcomparch(
    project_id: str,
    parent_comp_id: str,
    sub_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> SubcomparchResponse:
    _require_subcomponent(db, project_id, parent_comp_id, sub_id)
    return SubcomparchResponse(
        **bootstrap_get_state(
            db,
            project_id,
            (sub_id,),
            SUBCOMPARCH_CONFIG,
            _require_project,
        )
    )


@router.post(
    "/{project_id}/components/{parent_comp_id}/subcomponents/{sub_id}/subcomparch/feedback",
    response_model=FeedbackResponse,
)
def post_subcomparch_feedback(
    project_id: str,
    parent_comp_id: str,
    sub_id: str,
    req: FeedbackRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> FeedbackResponse:
    _require_subcomponent(db, project_id, parent_comp_id, sub_id)
    return FeedbackResponse(
        **bootstrap_feedback(
            db,
            project_id,
            (sub_id,),
            req.feedback,
            SUBCOMPARCH_CONFIG,
            _require_project,
        )
    )


@router.post(
    "/{project_id}/components/{parent_comp_id}/subcomponents/{sub_id}/subcomparch/approve",
    response_model=SubcomparchApproveResponse,
)
def post_subcomparch_approve(
    project_id: str,
    parent_comp_id: str,
    sub_id: str,
    req: DraftIdRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> SubcomparchApproveResponse:
    _require_subcomponent(db, project_id, parent_comp_id, sub_id)
    result = bootstrap_approve(
        db,
        project_id,
        (sub_id,),
        req.draft_id,
        SUBCOMPARCH_CONFIG,
        _require_project,
    )
    node_dict = result["node"]
    node_dict["parent_id"] = parent_comp_id
    return SubcomparchApproveResponse(node=SubcomparchNodeResponse(**node_dict))


@router.post(
    "/{project_id}/components/{parent_comp_id}/subcomponents/{sub_id}/subcomparch/discard",
    response_model=DiscardResponse,
)
def post_subcomparch_discard(
    project_id: str,
    parent_comp_id: str,
    sub_id: str,
    req: DraftIdRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> DiscardResponse:
    _require_subcomponent(db, project_id, parent_comp_id, sub_id)
    return DiscardResponse(
        **bootstrap_discard(
            db,
            project_id,
            (sub_id,),
            req.draft_id,
            SUBCOMPARCH_CONFIG,
            _require_project,
        )
    )


@router.post(
    "/{project_id}/components/{parent_comp_id}/subcomponents/{sub_id}/subcomparch/cancel",
    response_model=CancelResponse,
)
def post_subcomparch_cancel(
    project_id: str,
    parent_comp_id: str,
    sub_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> CancelResponse:
    _require_subcomponent(db, project_id, parent_comp_id, sub_id)
    return CancelResponse(
        **bootstrap_cancel(
            db,
            project_id,
            (sub_id,),
            SUBCOMPARCH_CONFIG,
            _require_project,
        )
    )


@router.post(
    "/{project_id}/components/{parent_comp_id}/subcomponents/{sub_id}/subcomparch/reset",
    response_model=ResetResponse,
)
def post_subcomparch_reset(
    project_id: str,
    parent_comp_id: str,
    sub_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> ResetResponse:
    _require_subcomponent(db, project_id, parent_comp_id, sub_id)
    return ResetResponse(
        **bootstrap_reset(
            db,
            project_id,
            (sub_id,),
            SUBCOMPARCH_CONFIG,
            _require_project,
        )
    )


@router.post(
    "/{project_id}/components/{parent_comp_id}/subcomponents/{sub_id}/subcomparch/review/retry",
    response_model=FeedbackResponse,
)
def post_subcomparch_review_retry(
    project_id: str,
    parent_comp_id: str,
    sub_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> FeedbackResponse:
    _require_subcomponent(db, project_id, parent_comp_id, sub_id)
    return FeedbackResponse(
        **bootstrap_retry_review(
            db,
            project_id,
            (sub_id,),
            SUBCOMPARCH_CONFIG,
            _require_project,
        )
    )


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
    # Heavy tiers (comp, subreqs, impl, fanin, expansion, reqs,
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
    "subreqs",
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
    from backend.graph.running import (
        errored_node_ids,
        running_node_ids,
        user_action_needed_node_ids,
    )
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

    running_ids = running_node_ids(db, project_id)
    errored_ids = errored_node_ids(db, project_id)
    user_action_ids = user_action_needed_node_ids(db, project_id)
    stale_reasons_by_id = stale_node_reasons(db, project_id)
    offset = queries.latest_offset(db, project_id) or 0

    # Tiers whose content is included inline. See the doc on
    # ``StructureNodeResponse.content`` for the rationale.
    light_content_tiers = {"feat", "resp", "policy", "vocab", "ref"}

    # Bulk-load the sysarch-minted techspec + pubapi fragments for
    # every comp in the project. Two indexed lookups per comp on
    # the ComponentOverviewPanel would be fine but the payload is
    # small and this keeps the structure fetch to one-query-per-
    # table.
    comp_ids = [n.id for n in node_rows if n.tier == "comp"]
    fragment_by_id: dict[str, str] = {}
    if comp_ids:
        wanted_fragment_ids: list[str] = []
        for cid in comp_ids:
            wanted_fragment_ids.append(fragment_id(cid, FragmentKind.TECHSPEC))
            wanted_fragment_ids.append(fragment_id(cid, FragmentKind.PUBAPI))
        frag_rows = db.execute(
            select(Fragment.id, Fragment.content).where(
                Fragment.project_id == project_id,
                Fragment.id.in_(wanted_fragment_ids),
            )
        ).all()
        for fid, fcontent in frag_rows:
            fragment_by_id[fid] = fcontent or ""

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
                techspec=fragment_by_id.get(fragment_id(n.id, FragmentKind.TECHSPEC), "")
                if n.tier == "comp"
                else "",
                pubapi=fragment_by_id.get(fragment_id(n.id, FragmentKind.PUBAPI), "")
                if n.tier == "comp"
                else "",
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


# ── Vocabulary routes (Phase 5.5) ──────────────────────────────────


class VocabEntryResponse(BaseModel):
    id: str
    name: str
    content: str  # raw <vocab-entry> XML
    parent_id: str | None
    parent_name: str | None  # resolved for the UI; None at project scope
    updated_at: str


class VocabListResponse(BaseModel):
    entries: list[VocabEntryResponse]


class CreateVocabRequest(BaseModel):
    name: str
    content: str  # full <vocab-entry>...</vocab-entry> XML
    parent_id: str | None = None  # None → project-level, feat_* id → feature-local


class EditVocabRequest(BaseModel):
    new_content: str  # new full <vocab-entry> XML


class RenameVocabRequest(BaseModel):
    new_name: str


class ReparentVocabRequest(BaseModel):
    new_parent_id: str | None  # None → promote to project-level


def _serialize_vocab_entry(db: Session, node: Node) -> VocabEntryResponse:
    parent_name: str | None = None
    if node.parent_id is not None:
        parent = db.get(Node, node.parent_id)
        if parent is not None:
            parent_name = parent.name
    return VocabEntryResponse(
        id=node.id,
        name=node.name,
        content=node.content or "",
        parent_id=node.parent_id,
        parent_name=parent_name,
        updated_at=node.updated_at.isoformat() if node.updated_at else "",
    )


def _validate_vocab_content(content: str, *, term_name: str, known_feature_names: set[str]) -> None:
    """Run the vocab validator over a standalone ``<vocab-entry>`` block.

    Wraps the content in a synthetic ``<vocabulary><term>`` shell so
    ``validate_vocabulary`` can parse it, because the top-level
    validator expects a ``<vocabulary>`` root. Raises HTTPException
    422 on any structural error. Used by the create and edit routes
    to ensure user-supplied content is valid before committing.
    """
    from backend.graph.parsers.validators import ValidationError, validate_vocabulary
    from backend.graph.parsers.xml_sections import ParseError, extract_tag_tree

    wrapped = f'<vocabulary><term name="{term_name}" scope="project">{content}</term></vocabulary>'
    try:
        tree = extract_tag_tree(wrapped, "vocabulary")
        validate_vocabulary(
            tree,
            known_feature_names=known_feature_names,
            allow_id_refs=True,
        )
    except (ParseError, ValidationError) as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid vocab entry content: {exc}",
        ) from exc


@router.get("/{project_id}/vocabulary", response_model=VocabListResponse)
def get_vocabulary(
    project_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> VocabListResponse:
    """List every vocab entry in a project, project-level first.

    The response carries both project-level (``parent_id`` is
    null) and feature-local (``parent_id`` is a ``feat_*`` id)
    entries in a single flat list. The frontend filters by scope
    when rendering the list view and the per-feature panel.
    """
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


@router.post(
    "/{project_id}/vocabulary/create",
    response_model=VocabEntryResponse,
)
def post_create_vocab(
    project_id: str,
    req: CreateVocabRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> VocabEntryResponse:
    """Create a new vocab entry with user-supplied content.

    Content must be a valid ``<vocab-entry>`` XML block; the
    route validates it before emitting ``NodeCreated``. Scope is
    set via ``parent_id``: ``None`` → project-level, a ``feat_*``
    id → feature-local. The reducer's vocab-parent invariant
    enforces that ``parent_id`` is either ``None`` or a valid
    feat_* node.

    User-supplied content means no LLM is involved in the create
    path. Users type definition prose directly; the LLM-assisted
    feedback → regen flow is deferred to a follow-up.
    """
    _require_project(db, project_id)

    # Parent validation: if scope is feature, the parent must be
    # a real feat_* in this project. The reducer would reject
    # it anyway, but an early 404 is a better UX than an
    # opaque reducer error.
    if req.parent_id is not None:
        parent = db.get(Node, req.parent_id)
        if parent is None or parent.project_id != project_id:
            raise HTTPException(
                status_code=404,
                detail=f"Parent node {req.parent_id!r} not found in project",
            )
        if parent.tier != "feat":
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Vocab entries may only be parented to feat_* nodes; "
                    f"{req.parent_id!r} is a {parent.tier!r} node."
                ),
            )

    # Content validation. Collect feature names for the validator's
    # feature-name cross-reference check in case the user's
    # content has <see-also> entries that reference features
    # (it shouldn't — see-also refs reference other terms, not
    # features — but the validator needs the set to exist).
    known_feature_names: set[str] = set()
    _validate_vocab_content(
        req.content,
        term_name=req.name,
        known_feature_names=known_feature_names,
    )

    # Uniqueness check within scope — matches the validator's
    # rule for batch creation. Reject early with 409 if a term
    # with this name already exists at the requested scope.
    from backend.graph.vocabulary import vocab_by_name

    existing = vocab_by_name(db, project_id, req.name, parent_id=req.parent_id)
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail=(f"Vocab entry named {req.name!r} already exists at this scope."),
        )

    from backend.graph.ids import Kind, mint

    vocab_id = mint(db, Kind.VOCAB)
    append_event(
        db,
        project_id,
        ev.NodeCreated(
            node_id=vocab_id,
            tier="vocab",
            kind="domain",
            parent_id=req.parent_id,
            name=req.name,
            display_order=0,
            content=req.content,
        ),
    )
    commit_and_publish(db, project_id)

    node = db.get(Node, vocab_id)
    assert node is not None
    return _serialize_vocab_entry(db, node)


@router.post(
    "/{project_id}/vocabulary/{vocab_id}/edit",
    response_model=VocabEntryResponse,
)
def post_edit_vocab(
    project_id: str,
    vocab_id: str,
    req: EditVocabRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> VocabEntryResponse:
    """Replace a vocab entry's content with user-supplied new content.

    Direct content replacement, no LLM involvement. The new
    content is validated as a standalone ``<vocab-entry>`` block
    before it lands. Because Node.content is written by the
    ``DraftApproved`` reducer branch (and there's no draft here
    because this is a direct edit), the reducer emits a synthetic
    draft-approved event via a small helper: actually, simpler —
    directly mutate Node.content with an updated_at bump. Event
    sourcing via the reducer is the right long-term path once
    drafts are wired in; for now, direct update is acceptable
    given this is the only write path for vocab content edits.
    """
    _require_project(db, project_id)
    from backend.graph.vocabulary import vocab_by_id

    entry = vocab_by_id(db, vocab_id)
    if entry is None or entry.project_id != project_id:
        raise HTTPException(status_code=404, detail=f"Vocab entry {vocab_id!r} not found")

    _validate_vocab_content(
        req.new_content,
        term_name=entry.name,
        known_feature_names=set(),
    )

    # Direct content update. Using a raw attribute write + commit
    # matches the pattern used by other "user-supplied content
    # lands straight on the node" paths in v2; when the full
    # event-sourced draft flow for vocab lands as a follow-up,
    # this will be refactored to emit DraftGenerated +
    # DraftApproved events through the reducer instead.
    from datetime import datetime

    entry.content = req.new_content
    entry.updated_at = datetime.utcnow()
    commit_and_publish(db, project_id)

    return _serialize_vocab_entry(db, entry)


@router.post(
    "/{project_id}/vocabulary/{vocab_id}/rename",
    response_model=VocabEntryResponse,
)
def post_rename_vocab(
    project_id: str,
    vocab_id: str,
    req: RenameVocabRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> VocabEntryResponse:
    _require_project(db, project_id)
    from backend.graph.vocabulary import vocab_by_id, vocab_by_name

    entry = vocab_by_id(db, vocab_id)
    if entry is None or entry.project_id != project_id:
        raise HTTPException(status_code=404, detail=f"Vocab entry {vocab_id!r} not found")

    new_name = req.new_name.strip()
    if not new_name:
        raise HTTPException(status_code=422, detail="new_name cannot be empty")

    if new_name != entry.name:
        existing = vocab_by_name(db, project_id, new_name, parent_id=entry.parent_id)
        if existing is not None and existing.id != vocab_id:
            raise HTTPException(
                status_code=409,
                detail=f"Vocab entry named {new_name!r} already exists at this scope.",
            )

    append_event(
        db,
        project_id,
        ev.NodeRenamed(node_id=vocab_id, new_name=new_name),
    )
    commit_and_publish(db, project_id)

    entry = db.get(Node, vocab_id)
    assert entry is not None
    return _serialize_vocab_entry(db, entry)


@router.post(
    "/{project_id}/vocabulary/{vocab_id}/reparent",
    response_model=VocabEntryResponse,
)
def post_reparent_vocab(
    project_id: str,
    vocab_id: str,
    req: ReparentVocabRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> VocabEntryResponse:
    """Promote or demote a vocab entry between project and feature scope.

    Passing ``new_parent_id=None`` promotes a feature-local
    entry to project-level. Passing a ``feat_*`` id scopes a
    project-level entry to that feature (or moves a
    feature-local entry between features). The reducer's
    vocab-parent invariant enforces that the new parent is
    either null or a valid feat_* node.
    """
    _require_project(db, project_id)
    from backend.graph.vocabulary import vocab_by_id

    entry = vocab_by_id(db, vocab_id)
    if entry is None or entry.project_id != project_id:
        raise HTTPException(status_code=404, detail=f"Vocab entry {vocab_id!r} not found")

    if req.new_parent_id is not None:
        parent = db.get(Node, req.new_parent_id)
        if parent is None or parent.project_id != project_id:
            raise HTTPException(
                status_code=404,
                detail=f"Parent node {req.new_parent_id!r} not found in project",
            )
        if parent.tier != "feat":
            raise HTTPException(
                status_code=422,
                detail=(
                    "Vocab entries may only be parented to feat_* nodes; "
                    f"{req.new_parent_id!r} is a {parent.tier!r} node."
                ),
            )

    append_event(
        db,
        project_id,
        ev.NodeReparented(node_id=vocab_id, new_parent_id=req.new_parent_id),
    )
    commit_and_publish(db, project_id)

    entry = db.get(Node, vocab_id)
    assert entry is not None
    return _serialize_vocab_entry(db, entry)


@router.post("/{project_id}/vocabulary/{vocab_id}/delete")
def post_delete_vocab(
    project_id: str,
    vocab_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> dict[str, str]:
    _require_project(db, project_id)
    from backend.graph.vocabulary import vocab_by_id

    entry = vocab_by_id(db, vocab_id)
    if entry is None or entry.project_id != project_id:
        raise HTTPException(status_code=404, detail=f"Vocab entry {vocab_id!r} not found")

    append_event(
        db,
        project_id,
        ev.NodeDeleted(node_id=vocab_id),
    )
    commit_and_publish(db, project_id)
    return {"status": "deleted", "vocab_id": vocab_id}


# ── Implementation routes (Phase 8) ────────────────────────────────
#
# One IMPL_CONFIG, two URL shapes:
#
#   /components/{comp_id}/impl              → un-fanned-out top-level
#   /components/{comp_id}/subcomponents/{sub_id}/impl
#                                            → per-subcomponent
#
# Both pass the **owner id** (the comp/sub that owns the impl) as
# the single scope id into ``bootstrap_*`` helpers. ``IMPL_CONFIG``
# sets ``scope_payload_keys=("owner_id",)`` so the generation
# handler's payload carries ``owner_id`` rather than the default
# ``component_id``.
#
# ``has_been_approved=None`` — per the architecture doc, impl has a
# destructive-edit gate only. Feedback / regen / re-approval flow
# freely post-approval; delete/merge/split (Phase 11) are the
# destructive ops that gate.
#
# No ``mint_job_type`` — approval commits ``Node.content`` via the
# standard DraftApproved reducer branch. No fragments, no children.


class ImplNodeResponse(BaseModel):
    id: str
    name: str
    parent_id: str
    content: str
    updated_at: str


class ImplDraftResponse(BaseModel):
    id: str
    content: str
    created_at: str


class ImplResponse(BaseModel):
    node: ImplNodeResponse
    pending_draft: ImplDraftResponse | None
    previous_draft_content: str | None = None
    generation_status: queries.GenerationStatus
    last_error: str | None
    latest_telemetry: TelemetrySummary | None
    generation_started_at: str | None = None
    current_attempt: int | None = None
    max_attempts: int | None = None
    failed_raw_output: str | None = None
    # Phase 8 — AI self-review fields. Populated when the tier
    # has a configured review_job_type; empty string / "idle"
    # for tiers that don't run reviews.
    review_text: str = ""
    review_status: queries.GenerationStatus = "idle"
    review_last_error: str | None = None
    review_started_at: str | None = None
    review_current_attempt: int | None = None
    review_max_attempts: int | None = None


def _get_impl_by_owner(db: Session, project_id: str, owner_id: str) -> Node | None:
    """Return the ``impl_*`` child of ``owner_id``, or None.

    The one-impl-per-leaf invariant is enforced at mint time by
    :func:`comparch_mint._mint_impl_shell`, so the query uses
    ``scalar_one_or_none`` defensively rather than ``.first()``.
    """
    return db.execute(
        select(Node).where(
            Node.project_id == project_id,
            Node.tier == "impl",
            Node.parent_id == owner_id,
        )
    ).scalar_one_or_none()


def _pending_impl_draft(db: Session, project_id: str, owner_id: str) -> Draft | None:
    impl = _get_impl_by_owner(db, project_id, owner_id)
    if impl is None:
        return None
    return db.execute(
        select(Draft).where(
            Draft.project_id == project_id,
            Draft.target_type == "node",
            Draft.target_id == impl.id,
            Draft.status == "pending",
        )
    ).scalar_one_or_none()


IMPL_CONFIG = BootstrapTierConfig(
    tier_name="Implementation",
    get_node=_get_impl_by_owner,
    get_pending_draft=_pending_impl_draft,
    has_been_approved=None,  # destructive-edit gate only; never frozen
    generate_job_type=GENERATE_IMPL_JOB_TYPE,
    mint_job_type="",  # no downstream mint — DraftApproved commits content
    serialize_node=_node_to_dict_with_parent,
    serialize_draft=_draft_to_dict,
    feedback_readonly_detail="",  # unused (has_been_approved is None)
    scope_payload_keys=("owner_id",),
    # Phase 7: after an impl approval lands, walk up to the
    # owning top-level domain comp and enqueue fan-in regen if
    # one exists. See ``impl_generation.on_impl_approved``.
    on_approve=on_impl_approved,
    collect_downstream_nodes=per_comp_reset.collect_downstream_nodes_impl,
    collect_pending_drafts_for_nodes=per_comp_reset.collect_pending_drafts_for_nodes,
    downstream_job_types=per_comp_reset.impl_downstream_job_types(),
    review_job_type="v2.review_impl",
)


def _impl_response_from_state(state: dict) -> ImplResponse:
    """Shape the standard bootstrap_get_state payload into ImplResponse.

    The node dict from ``_node_to_dict_with_parent`` carries
    ``parent_id`` alongside id / name / content / updated_at,
    matching the ``ImplNodeResponse`` schema exactly.
    """
    return ImplResponse(
        node=ImplNodeResponse(**state["node"]),
        pending_draft=(
            ImplDraftResponse(**state["pending_draft"]) if state["pending_draft"] else None
        ),
        generation_status=state["generation_status"],
        last_error=state["last_error"],
        latest_telemetry=state["latest_telemetry"],
        generation_started_at=state.get("generation_started_at"),
        current_attempt=state.get("current_attempt"),
        max_attempts=state.get("max_attempts"),
        failed_raw_output=state.get("failed_raw_output"),
        review_text=state.get("review_text", ""),
        review_status=state.get("review_status", "idle"),
        review_last_error=state.get("review_last_error"),
        review_started_at=state.get("review_started_at"),
        review_current_attempt=state.get("review_current_attempt"),
        review_max_attempts=state.get("review_max_attempts"),
    )


# ── Top-level (un-fanned-out) impl routes ──────────────────────────


@router.get(
    "/{project_id}/components/{comp_id}/impl",
    response_model=ImplResponse,
)
def get_impl_top_level(
    project_id: str,
    comp_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> ImplResponse:
    _require_top_level_comp(db, project_id, comp_id)
    state = bootstrap_get_state(
        db,
        project_id,
        (comp_id,),
        IMPL_CONFIG,
        _require_project,
    )
    return _impl_response_from_state(state)


@router.post(
    "/{project_id}/components/{comp_id}/impl/feedback",
    response_model=FeedbackResponse,
)
def post_impl_top_level_feedback(
    project_id: str,
    comp_id: str,
    req: FeedbackRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> FeedbackResponse:
    _require_top_level_comp(db, project_id, comp_id)
    return FeedbackResponse(
        **bootstrap_feedback(
            db,
            project_id,
            (comp_id,),
            req.feedback,
            IMPL_CONFIG,
            _require_project,
        )
    )


@router.post(
    "/{project_id}/components/{comp_id}/impl/approve",
    response_model=DiscardResponse,
)
def post_impl_top_level_approve(
    project_id: str,
    comp_id: str,
    req: DraftIdRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> DiscardResponse:
    _require_top_level_comp(db, project_id, comp_id)
    bootstrap_approve(
        db,
        project_id,
        (comp_id,),
        req.draft_id,
        IMPL_CONFIG,
        _require_project,
    )
    return DiscardResponse(ok=True)


@router.post(
    "/{project_id}/components/{comp_id}/impl/discard",
    response_model=DiscardResponse,
)
def post_impl_top_level_discard(
    project_id: str,
    comp_id: str,
    req: DraftIdRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> DiscardResponse:
    _require_top_level_comp(db, project_id, comp_id)
    return DiscardResponse(
        **bootstrap_discard(
            db,
            project_id,
            (comp_id,),
            req.draft_id,
            IMPL_CONFIG,
            _require_project,
        )
    )


@router.post(
    "/{project_id}/components/{comp_id}/impl/cancel",
    response_model=CancelResponse,
)
def post_impl_top_level_cancel(
    project_id: str,
    comp_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> CancelResponse:
    _require_top_level_comp(db, project_id, comp_id)
    return CancelResponse(
        **bootstrap_cancel(
            db,
            project_id,
            (comp_id,),
            IMPL_CONFIG,
            _require_project,
        )
    )


@router.post(
    "/{project_id}/components/{comp_id}/impl/reset",
    response_model=ResetResponse,
)
def post_impl_top_level_reset(
    project_id: str,
    comp_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> ResetResponse:
    _require_top_level_comp(db, project_id, comp_id)
    return ResetResponse(
        **bootstrap_reset(
            db,
            project_id,
            (comp_id,),
            IMPL_CONFIG,
            _require_project,
        )
    )


@router.post(
    "/{project_id}/components/{comp_id}/impl/review/retry",
    response_model=FeedbackResponse,
)
def post_impl_top_level_review_retry(
    project_id: str,
    comp_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> FeedbackResponse:
    _require_top_level_comp(db, project_id, comp_id)
    return FeedbackResponse(
        **bootstrap_retry_review(
            db,
            project_id,
            (comp_id,),
            IMPL_CONFIG,
            _require_project,
        )
    )


# ── Per-subcomponent impl routes ───────────────────────────────────


@router.get(
    "/{project_id}/components/{parent_comp_id}/subcomponents/{sub_id}/impl",
    response_model=ImplResponse,
)
def get_impl_sub(
    project_id: str,
    parent_comp_id: str,
    sub_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> ImplResponse:
    _require_subcomponent(db, project_id, parent_comp_id, sub_id)
    state = bootstrap_get_state(
        db,
        project_id,
        (sub_id,),
        IMPL_CONFIG,
        _require_project,
    )
    return _impl_response_from_state(state)


@router.post(
    "/{project_id}/components/{parent_comp_id}/subcomponents/{sub_id}/impl/feedback",
    response_model=FeedbackResponse,
)
def post_impl_sub_feedback(
    project_id: str,
    parent_comp_id: str,
    sub_id: str,
    req: FeedbackRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> FeedbackResponse:
    _require_subcomponent(db, project_id, parent_comp_id, sub_id)
    return FeedbackResponse(
        **bootstrap_feedback(
            db,
            project_id,
            (sub_id,),
            req.feedback,
            IMPL_CONFIG,
            _require_project,
        )
    )


@router.post(
    "/{project_id}/components/{parent_comp_id}/subcomponents/{sub_id}/impl/approve",
    response_model=DiscardResponse,
)
def post_impl_sub_approve(
    project_id: str,
    parent_comp_id: str,
    sub_id: str,
    req: DraftIdRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> DiscardResponse:
    _require_subcomponent(db, project_id, parent_comp_id, sub_id)
    bootstrap_approve(
        db,
        project_id,
        (sub_id,),
        req.draft_id,
        IMPL_CONFIG,
        _require_project,
    )
    return DiscardResponse(ok=True)


@router.post(
    "/{project_id}/components/{parent_comp_id}/subcomponents/{sub_id}/impl/discard",
    response_model=DiscardResponse,
)
def post_impl_sub_discard(
    project_id: str,
    parent_comp_id: str,
    sub_id: str,
    req: DraftIdRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> DiscardResponse:
    _require_subcomponent(db, project_id, parent_comp_id, sub_id)
    return DiscardResponse(
        **bootstrap_discard(
            db,
            project_id,
            (sub_id,),
            req.draft_id,
            IMPL_CONFIG,
            _require_project,
        )
    )


@router.post(
    "/{project_id}/components/{parent_comp_id}/subcomponents/{sub_id}/impl/cancel",
    response_model=CancelResponse,
)
def post_impl_sub_cancel(
    project_id: str,
    parent_comp_id: str,
    sub_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> CancelResponse:
    _require_subcomponent(db, project_id, parent_comp_id, sub_id)
    return CancelResponse(
        **bootstrap_cancel(
            db,
            project_id,
            (sub_id,),
            IMPL_CONFIG,
            _require_project,
        )
    )


@router.post(
    "/{project_id}/components/{parent_comp_id}/subcomponents/{sub_id}/impl/reset",
    response_model=ResetResponse,
)
def post_impl_sub_reset(
    project_id: str,
    parent_comp_id: str,
    sub_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> ResetResponse:
    _require_subcomponent(db, project_id, parent_comp_id, sub_id)
    return ResetResponse(
        **bootstrap_reset(
            db,
            project_id,
            (sub_id,),
            IMPL_CONFIG,
            _require_project,
        )
    )


@router.post(
    "/{project_id}/components/{parent_comp_id}/subcomponents/{sub_id}/impl/review/retry",
    response_model=FeedbackResponse,
)
def post_impl_sub_review_retry(
    project_id: str,
    parent_comp_id: str,
    sub_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> FeedbackResponse:
    _require_subcomponent(db, project_id, parent_comp_id, sub_id)
    return FeedbackResponse(
        **bootstrap_retry_review(
            db,
            project_id,
            (sub_id,),
            IMPL_CONFIG,
            _require_project,
        )
    )


# ── Fan-in inspection routes (Phase 7) ────────────────────────────
#
# Fan-in has **no draft lifecycle** — the handler writes Node.content
# directly via ``FanInContentUpdated``. That makes ``BootstrapTierConfig``
# the wrong shape (no feedback / approve / discard). Three small
# endpoints instead:
#
#   GET  /{project_id}/components/{comp_id}/fanin
#        → node content + generation status + telemetry
#   POST /{project_id}/components/{comp_id}/fanin/regenerate
#        → enqueue v2.generate_fanin (dedup-safe)
#   POST /{project_id}/components/{comp_id}/fanin/cancel
#        → cancel the active regen if any
#
# The owning comp is addressed by its own comp_id in the URL — the
# fan-in node itself lives as its ``tier="fanin"`` child, minted at
# comparch-approval time for fanned-out domain comps.


class FanInNodeResponse(BaseModel):
    id: str
    name: str
    owner_comp_id: str
    content: str
    updated_at: str


class FanInResponse(BaseModel):
    node: FanInNodeResponse
    generation_status: queries.GenerationStatus
    last_error: str | None
    latest_telemetry: TelemetrySummary | None
    generation_started_at: str | None = None
    current_attempt: int | None = None
    max_attempts: int | None = None
    failed_raw_output: str | None = None
    # Phase 8 — AI self-review fields. Populated when the tier
    # has a configured review_job_type; empty string / "idle"
    # for tiers that don't run reviews.
    review_text: str = ""
    review_status: queries.GenerationStatus = "idle"
    review_last_error: str | None = None
    review_started_at: str | None = None
    review_current_attempt: int | None = None
    review_max_attempts: int | None = None


def _get_fanin_by_owner(db: Session, project_id: str, owner_comp_id: str) -> Node | None:
    """Return the ``fanin_*`` child of ``owner_comp_id``, or None.

    Mirrors ``_get_impl_by_owner`` but filters on ``tier="fanin"``.
    One fan-in per fanned-out domain comp — minted by
    ``comparch_mint`` if and only if ``comp.kind == "domain"`` and
    the comp fanned out into subcomponents. A missing fan-in means
    the comp either is presentational or un-fanned-out; callers
    should 404.
    """
    return db.execute(
        select(Node).where(
            Node.project_id == project_id,
            Node.tier == "fanin",
            Node.parent_id == owner_comp_id,
        )
    ).scalar_one_or_none()


def _fanin_response(
    db: Session,
    project_id: str,
    owner_comp_id: str,
    fanin_node: Node,
) -> FanInResponse:
    (
        status,
        last_error,
        started_at,
        current_attempt,
        max_attempts,
        failed_raw_output,
    ) = queries.latest_generation_status(
        db,
        project_id,
        GENERATE_FANIN_JOB_TYPE,
        payload_filters={"owner_comp_id": owner_comp_id},
    )
    # Phase 8 — fanin review status is keyed on the fanin node
    # id (review payload always carries ``node_id``).
    (
        _review_status,
        _review_last_error,
        _review_started_at,
        _review_current_attempt,
        _review_max_attempts,
        _,
    ) = queries.latest_generation_status(
        db,
        project_id,
        "v2.review_fanin",
        payload_filters={"node_id": fanin_node.id},
    )
    telemetry_row = (
        db.query(GenerationTelemetry)
        .filter(
            GenerationTelemetry.project_id == project_id,
            GenerationTelemetry.node_id == fanin_node.id,
        )
        .order_by(GenerationTelemetry.created_at.desc())
        .first()
    )
    telemetry = (
        TelemetrySummary(
            prompt_tokens=telemetry_row.prompt_tokens,
            completion_tokens=telemetry_row.completion_tokens,
            model=telemetry_row.model,
            created_at=telemetry_row.created_at.isoformat() if telemetry_row.created_at else "",
        )
        if telemetry_row is not None
        else None
    )
    return FanInResponse(
        node=FanInNodeResponse(
            id=fanin_node.id,
            name=fanin_node.name,
            owner_comp_id=owner_comp_id,
            content=fanin_node.content or "",
            updated_at=(fanin_node.updated_at.isoformat() if fanin_node.updated_at else ""),
        ),
        generation_status=status,
        last_error=last_error,
        latest_telemetry=telemetry,
        generation_started_at=started_at,
        current_attempt=current_attempt,
        max_attempts=max_attempts,
        failed_raw_output=failed_raw_output,
        review_text=fanin_node.review_text or "",
        review_status=_review_status,
        review_last_error=_review_last_error,
        review_started_at=_review_started_at,
        review_current_attempt=_review_current_attempt,
        review_max_attempts=_review_max_attempts,
    )


@router.get(
    "/{project_id}/components/{comp_id}/fanin",
    response_model=FanInResponse,
)
def get_fanin(
    project_id: str,
    comp_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> FanInResponse:
    """Return the fan-in node's content + generation status.

    404 if the comp has no fan-in child — presentational comps and
    un-fanned-out domain comps don't mint one.
    """
    _require_project(db, project_id)
    _require_top_level_comp(db, project_id, comp_id)
    fanin = _get_fanin_by_owner(db, project_id, comp_id)
    if fanin is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Component {comp_id!r} has no fan-in node — only "
                "fanned-out domain components produce fan-in syntheses."
            ),
        )
    return _fanin_response(db, project_id, comp_id, fanin)


@router.post(
    "/{project_id}/components/{comp_id}/fanin/regenerate",
    response_model=FeedbackResponse,
)
def post_fanin_regenerate(
    project_id: str,
    comp_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> FeedbackResponse:
    """Manually enqueue a fresh fan-in synthesis.

    Normally the ``on_impl_approved`` hook drives regen; this
    endpoint exists for debugging and for the user to re-run with
    updated prompt state. Payload-dedup collapses duplicate enqueues
    into the same running job.
    """
    from backend.pipeline import queue as pipeline_queue

    _require_project(db, project_id)
    _require_top_level_comp(db, project_id, comp_id)
    fanin = _get_fanin_by_owner(db, project_id, comp_id)
    if fanin is None:
        raise HTTPException(
            status_code=404,
            detail=f"Component {comp_id!r} has no fan-in node.",
        )
    job_id = pipeline_queue.enqueue(
        db,
        job_type=GENERATE_FANIN_JOB_TYPE,
        payload={"project_id": project_id, "owner_comp_id": comp_id},
    )
    return FeedbackResponse(job_id=job_id)


@router.post(
    "/{project_id}/components/{comp_id}/fanin/cancel",
    response_model=CancelResponse,
)
def post_fanin_cancel(
    project_id: str,
    comp_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> CancelResponse:
    """Cancel any in-flight fan-in regen for this comp."""
    from backend.pipeline import queue as pipeline_queue

    _require_project(db, project_id)
    _require_top_level_comp(db, project_id, comp_id)
    job = pipeline_queue.find_active_job(
        db,
        GENERATE_FANIN_JOB_TYPE,
        payload_filters={"project_id": project_id, "owner_comp_id": comp_id},
    )
    if job is None:
        return CancelResponse(cancelled=False)
    ok = pipeline_queue.cancel_job(db, job.id)
    return CancelResponse(cancelled=ok)


@router.post(
    "/{project_id}/components/{comp_id}/fanin/reset",
    response_model=ResetResponse,
)
def post_fanin_reset(
    project_id: str,
    comp_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> ResetResponse:
    """Force-reset the fan-in summary for this comp.

    Fan-in doesn't use the draft lifecycle (content writes land
    via ``FanInContentUpdated`` directly from the generation
    handler), so we skip the draft-discard step the generic
    ``bootstrap_reset`` runs. Instead: cancel the in-flight
    generation job if one exists, clear the fanin node's content
    via ``BootstrapNodeContentCleared``, re-enqueue
    ``v2.generate_fanin``, and return the same response shape as
    the other reset endpoints.
    """
    from backend.pipeline import queue as pipeline_queue

    _require_project(db, project_id)
    _require_top_level_comp(db, project_id, comp_id)

    # Locate the fanin node for this comp.
    fanin_node = db.execute(
        select(Node).where(
            Node.project_id == project_id,
            Node.tier == "fanin",
            Node.parent_id == comp_id,
        )
    ).scalar_one_or_none()
    if fanin_node is None:
        raise HTTPException(
            status_code=404,
            detail="Fan-in node missing — this comp hasn't been fanned out yet.",
        )

    jobs_cancelled = pipeline_queue.cancel_jobs_by_type(
        db,
        GENERATE_FANIN_JOB_TYPE,
        project_id=project_id,
        owner_comp_id=comp_id,
    )
    append_event(
        db,
        project_id,
        ev.BootstrapNodeContentCleared(node_id=fanin_node.id),
    )
    commit_and_publish(db, project_id)
    pipeline_queue.enqueue(
        db,
        job_type=GENERATE_FANIN_JOB_TYPE,
        payload={"project_id": project_id, "owner_comp_id": comp_id},
    )
    return ResetResponse(
        ok=True,
        nodes_deleted=0,
        drafts_discarded=0,
        jobs_cancelled=jobs_cancelled,
    )


@router.post(
    "/{project_id}/components/{comp_id}/fanin/review/retry",
    response_model=FeedbackResponse,
)
def post_fanin_review_retry(
    project_id: str,
    comp_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> FeedbackResponse:
    """Manually re-enqueue the AI review for this fanin node.

    Fanin has no draft, so the review targets the Node row. Cancels
    any stuck review job for this fanin and enqueues a fresh one.
    """
    from backend.pipeline import queue as pipeline_queue

    _require_project(db, project_id)
    _require_top_level_comp(db, project_id, comp_id)
    fanin_node = db.execute(
        select(Node).where(
            Node.project_id == project_id,
            Node.tier == "fanin",
            Node.parent_id == comp_id,
        )
    ).scalar_one_or_none()
    if fanin_node is None:
        raise HTTPException(status_code=404, detail="Fan-in node missing for this comp.")
    if not (fanin_node.content or "").strip():
        raise HTTPException(status_code=409, detail="Fan-in has no content to review yet.")
    pipeline_queue.cancel_jobs_by_type(
        db,
        "v2.review_fanin",
        project_id=project_id,
        node_id=fanin_node.id,
    )
    job_id = pipeline_queue.enqueue(
        db,
        job_type="v2.review_fanin",
        payload={
            "project_id": project_id,
            "node_id": fanin_node.id,
            "draft_id": None,
        },
    )
    return FeedbackResponse(job_id=job_id)


# ── Reference routes (Phase 6.6) ──────────────────────────────────
#
# Refs use the BootstrapTierConfig pattern for their per-ref
# lifecycle (get / feedback / approve / discard / cancel). Three
# things make them deviate from a "pure" bootstrap tier:
#
# 1. Multi-instance — the project owns N refs, not a singleton.
#    The standard list endpoint and the create endpoint stay
#    bespoke since they have no analogue in the bootstrap config.
# 2. Never frozen — ``has_been_approved=None`` skips the freeze
#    gate so ``UpdateReference`` works at any time.
# 3. ``ref_id`` payload key — generate_reference expects
#    ``ref_id`` rather than ``component_id`` in the job payload,
#    handled via the config's ``scope_payload_keys``.
#
# Edge add/remove and delete are bespoke because they're
# non-lifecycle operations that don't map onto the bootstrap
# helpers.


class ReferenceEdgeResponse(BaseModel):
    edge_id: str
    source_id: str
    target_id: str


class ReferenceDetailResponse(BaseModel):
    """GET /references/{ref_id} response.

    Wraps the standard ``BootstrapTierConfig`` payload (node /
    pending_draft / generation_status / etc.) and adds the
    ref-specific edge lists.
    """

    node: ExpansionNodeResponse
    pending_draft: ExpansionDraftResponse | None
    generation_status: queries.GenerationStatus
    last_error: str | None
    latest_telemetry: TelemetrySummary | None
    generation_started_at: str | None = None
    current_attempt: int | None = None
    max_attempts: int | None = None
    failed_raw_output: str | None = None
    # Phase 8 — AI self-review fields. Populated when the tier
    # has a configured review_job_type; empty string / "idle"
    # for tiers that don't run reviews.
    review_text: str = ""
    review_status: queries.GenerationStatus = "idle"
    review_last_error: str | None = None
    review_started_at: str | None = None
    review_current_attempt: int | None = None
    review_max_attempts: int | None = None
    outgoing_edges: list[ReferenceEdgeResponse]
    incoming_edges: list[ReferenceEdgeResponse]


class ReferenceSummary(BaseModel):
    id: str
    name: str
    has_content: bool
    updated_at: str


class ReferenceListResponse(BaseModel):
    references: list[ReferenceSummary]


class CreateReferenceRequest(BaseModel):
    name: str
    seed_description: str
    related_nodes: list[str] = []


class CreateReferenceResponse(BaseModel):
    ref_id: str
    job_id: str


class AddReferenceEdgeRequest(BaseModel):
    source_id: str
    target_id: str


class RemoveReferenceEdgeRequest(BaseModel):
    source_id: str
    target_id: str


def _serialize_reference_summary(node: Node) -> ReferenceSummary:
    return ReferenceSummary(
        id=node.id,
        name=node.name,
        has_content=bool(node.content),
        updated_at=node.updated_at.isoformat() if node.updated_at else "",
    )


def _serialize_ref_edge(edge: Edge) -> ReferenceEdgeResponse:
    return ReferenceEdgeResponse(
        edge_id=edge.id,
        source_id=edge.source_id,
        target_id=edge.target_id,
    )


def _ref_get_node(db: Session, project_id: str, ref_id: str) -> Node | None:
    """BootstrapTierConfig.get_node adapter for refs.

    Wraps ``references.reference_by_id`` with a project-id check
    so the bootstrap helper's "node missing" branch fires for
    cross-project lookups too.
    """
    from backend.graph.references import reference_by_id

    node = reference_by_id(db, ref_id)
    if node is None or node.project_id != project_id:
        return None
    return node


def _ref_pending_draft(db: Session, project_id: str, ref_id: str) -> Draft | None:
    return db.execute(
        select(Draft).where(
            Draft.project_id == project_id,
            Draft.target_type == "node",
            Draft.target_id == ref_id,
            Draft.status == "pending",
        )
    ).scalar_one_or_none()


REFERENCE_CONFIG = BootstrapTierConfig(
    tier_name="Reference",
    get_node=_ref_get_node,
    get_pending_draft=_ref_pending_draft,
    # Refs are NOT frozen after approval — leaving this None
    # skips the bootstrap helper's freeze-gate check.
    has_been_approved=None,
    # No lazy bootstrap: refs are always created explicitly via
    # POST /references/create; absent is genuinely 404.
    bootstrap_node=None,
    generate_job_type=GENERATE_REFERENCE_JOB_TYPE,
    # No mint job — refs don't fan out into children, so approval
    # just commits Node.content.
    mint_job_type="",
    serialize_node=_node_to_dict,
    serialize_draft=_draft_to_dict,
    feedback_readonly_detail="",  # unused (has_been_approved is None)
    scope_payload_keys=("ref_id",),
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
    """Return one ref's standard bootstrap payload plus its edges."""
    state = bootstrap_get_state(
        db,
        project_id,
        (ref_id,),
        REFERENCE_CONFIG,
        _require_project,
    )
    from backend.graph.references import (
        incoming_reference_edges,
        outgoing_reference_edges,
    )

    outgoing = [_serialize_ref_edge(e) for e in outgoing_reference_edges(db, project_id, ref_id)]
    incoming = [_serialize_ref_edge(e) for e in incoming_reference_edges(db, project_id, ref_id)]
    return ReferenceDetailResponse(
        node=ExpansionNodeResponse(**state["node"]),
        pending_draft=(
            ExpansionDraftResponse(**state["pending_draft"]) if state["pending_draft"] else None
        ),
        generation_status=state["generation_status"],
        last_error=state["last_error"],
        latest_telemetry=state["latest_telemetry"],
        generation_started_at=state.get("generation_started_at"),
        current_attempt=state.get("current_attempt"),
        max_attempts=state.get("max_attempts"),
        failed_raw_output=state.get("failed_raw_output"),
        outgoing_edges=outgoing,
        incoming_edges=incoming,
    )


@router.post(
    "/{project_id}/references/create",
    response_model=CreateReferenceResponse,
)
def post_create_reference(
    project_id: str,
    req: CreateReferenceRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> CreateReferenceResponse:
    """Mint a new ref node and enqueue its initial generation.

    Unlike vocab (direct-CRUD), refs are LLM-generated. The route
    mints an empty ``ref_*`` node + ``reference`` edges to the
    caller-supplied ``related_nodes``, then delegates to
    :func:`bootstrap_feedback` to enqueue the initial generation
    job — keeping the enqueue path inside the shared bootstrap
    helper rather than duplicating it here.
    """
    _require_project(db, project_id)

    name = req.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="name cannot be empty")
    if not req.seed_description.strip():
        raise HTTPException(
            status_code=422,
            detail="seed_description cannot be empty",
        )

    from backend.graph.references import reference_by_name

    existing = reference_by_name(db, project_id, name)
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail=f"Reference named {name!r} already exists in this project.",
        )

    # Validate related_nodes exist before minting so partial state
    # isn't emitted on a bad request.
    for related_id in req.related_nodes:
        related = db.get(Node, related_id)
        if related is None or related.project_id != project_id:
            raise HTTPException(
                status_code=404,
                detail=f"Related node {related_id!r} not found in project",
            )

    from backend.graph.ids import Kind, mint

    ref_id = mint(db, Kind.REF)
    # The seed description rides into the ref's content as a tiny
    # ``<reference>`` shell, so the generate handler's regen prompt
    # always has something to anchor against (even though refs are
    # not frozen, the very first call still needs a hint). The
    # validator accepts this minimal shape.
    seed_xml = (
        f"<reference><title>{name}</title><body>{req.seed_description.strip()}</body></reference>"
    )
    append_event(
        db,
        project_id,
        ev.NodeCreated(
            node_id=ref_id,
            tier="ref",
            kind="domain",
            parent_id=None,
            name=name,
            content=seed_xml,
        ),
    )
    for related_id in req.related_nodes:
        edge_id = mint(db, Kind.EDGE)
        append_event(
            db,
            project_id,
            ev.EdgeCreated(
                edge_id=edge_id,
                edge_type="reference",
                source_id=ref_id,
                target_id=related_id,
            ),
        )
    commit_and_publish(db, project_id)

    feedback_result = bootstrap_feedback(
        db,
        project_id,
        (ref_id,),
        "",  # initial generation — no feedback yet
        REFERENCE_CONFIG,
        _require_project,
    )
    return CreateReferenceResponse(ref_id=ref_id, job_id=feedback_result["job_id"])


@router.post(
    "/{project_id}/references/{ref_id}/feedback",
    response_model=FeedbackResponse,
)
def post_reference_feedback(
    project_id: str,
    ref_id: str,
    req: FeedbackRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> FeedbackResponse:
    """Regenerate a reference with optional prose feedback.

    Refs are NOT frozen after approval (``has_been_approved`` is
    ``None`` on ``REFERENCE_CONFIG``), so the bootstrap helper's
    freeze-gate check is skipped and feedback works in any state.
    """
    return FeedbackResponse(
        **bootstrap_feedback(
            db,
            project_id,
            (ref_id,),
            req.feedback,
            REFERENCE_CONFIG,
            _require_project,
        )
    )


@router.post(
    "/{project_id}/references/{ref_id}/approve",
    response_model=DiscardResponse,
)
def post_reference_approve(
    project_id: str,
    ref_id: str,
    req: DraftIdRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> DiscardResponse:
    """Approve a pending ref draft, committing its content to Node.content."""
    bootstrap_approve(
        db,
        project_id,
        (ref_id,),
        req.draft_id,
        REFERENCE_CONFIG,
        _require_project,
    )
    return DiscardResponse(ok=True)


@router.post(
    "/{project_id}/references/{ref_id}/discard",
    response_model=DiscardResponse,
)
def post_reference_discard(
    project_id: str,
    ref_id: str,
    req: DraftIdRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> DiscardResponse:
    """Discard a pending ref draft and re-enqueue a fresh generation.

    Same auto-regen behaviour as every other bootstrap tier — the
    user is presumably iterating on the draft, so dropping the
    pending one and immediately re-running matches the bootstrap
    chain's UX.
    """
    return DiscardResponse(
        **bootstrap_discard(
            db,
            project_id,
            (ref_id,),
            req.draft_id,
            REFERENCE_CONFIG,
            _require_project,
        )
    )


@router.post(
    "/{project_id}/references/{ref_id}/cancel",
    response_model=CancelResponse,
)
def post_reference_cancel(
    project_id: str,
    ref_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> CancelResponse:
    """Stop any queued/running generation for this reference."""
    return CancelResponse(
        **bootstrap_cancel(
            db,
            project_id,
            (ref_id,),
            REFERENCE_CONFIG,
            _require_project,
        )
    )


@router.post("/{project_id}/references/{ref_id}/delete")
def post_reference_delete(
    project_id: str,
    ref_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> dict[str, str]:
    """Delete a ref node (and cascade-delete its reference edges)."""
    _require_project(db, project_id)
    node = _ref_get_node(db, project_id, ref_id)
    if node is None:
        raise HTTPException(status_code=404, detail=f"Reference {ref_id!r} not found")
    append_event(db, project_id, ev.NodeDeleted(node_id=ref_id))
    commit_and_publish(db, project_id)
    return {"status": "deleted", "ref_id": ref_id}


@router.post(
    "/{project_id}/edges/reference",
    response_model=ReferenceEdgeResponse,
)
def post_add_reference_edge(
    project_id: str,
    req: AddReferenceEdgeRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> ReferenceEdgeResponse:
    """Add a ``reference`` edge from ``source_id`` to ``target_id``.

    Either endpoint can be any node in the project — the edge type
    is general-purpose advisory context, not specific to refs.
    Refuses to create a duplicate edge (409) and refuses dangling
    references (404).
    """
    _require_project(db, project_id)
    if req.source_id == req.target_id:
        raise HTTPException(
            status_code=422,
            detail="source_id and target_id must differ",
        )
    source = db.get(Node, req.source_id)
    if source is None or source.project_id != project_id:
        raise HTTPException(
            status_code=404,
            detail=f"Source node {req.source_id!r} not found in project",
        )
    target = db.get(Node, req.target_id)
    if target is None or target.project_id != project_id:
        raise HTTPException(
            status_code=404,
            detail=f"Target node {req.target_id!r} not found in project",
        )
    existing = db.execute(
        select(Edge).where(
            Edge.project_id == project_id,
            Edge.edge_type == "reference",
            Edge.source_id == req.source_id,
            Edge.target_id == req.target_id,
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail="A reference edge between these nodes already exists",
        )
    from backend.graph.ids import Kind, mint

    edge_id = mint(db, Kind.EDGE)
    append_event(
        db,
        project_id,
        ev.EdgeCreated(
            edge_id=edge_id,
            edge_type="reference",
            source_id=req.source_id,
            target_id=req.target_id,
        ),
    )
    commit_and_publish(db, project_id)
    return ReferenceEdgeResponse(
        edge_id=edge_id,
        source_id=req.source_id,
        target_id=req.target_id,
    )


@router.delete(
    "/{project_id}/edges/reference",
    response_model=DiscardResponse,
)
def post_remove_reference_edge(
    project_id: str,
    req: RemoveReferenceEdgeRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> DiscardResponse:
    """Delete the ``reference`` edge between two nodes."""
    _require_project(db, project_id)
    edge = db.execute(
        select(Edge).where(
            Edge.project_id == project_id,
            Edge.edge_type == "reference",
            Edge.source_id == req.source_id,
            Edge.target_id == req.target_id,
        )
    ).scalar_one_or_none()
    if edge is None:
        raise HTTPException(
            status_code=404,
            detail=(f"No reference edge between {req.source_id!r} and {req.target_id!r}"),
        )
    append_event(db, project_id, ev.EdgeDeleted(edge_id=edge.id))
    commit_and_publish(db, project_id)
    return DiscardResponse(ok=True)


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
    fragment kind.
    """

    node_content: DiffSidesResponse
    fragments: list[FragmentDiffResponse]


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
    )
