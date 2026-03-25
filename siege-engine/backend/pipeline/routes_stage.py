import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.auth.routes import _require_writer
from backend.database import get_db
from backend.models import (
    Artifact,
    ArtifactStatus,
    PipelineConfig,
    StageDefinition,
    StageExecution,
    StageStatus,
    User,
)
from backend.pipeline.defaults import DEFAULT_STAGES
from backend.pipeline.engine import PipelineEngine
from backend.pipeline.queue import cancel_jobs_by_type, cancel_running_execution, enqueue
from backend.pipeline.schemas import (
    RegenDownstreamRequest,
    ResolveStaleRequest,
    ResumeRequest,
    ReviseRequest,
    StageDefinitionResponse,
    StageDefinitionUpdate,
    TriggerStageRequest,
)
from backend.websocket.manager import ws_manager

logger = logging.getLogger(__name__)

stage_router = APIRouter()


def _get_config_or_404(db: Session, project_id: str) -> PipelineConfig:
    config = db.query(PipelineConfig).filter_by(project_id=project_id).first()
    if not config:
        raise HTTPException(404, "Pipeline config not found")
    return config


def _get_stage_def(db: Session, project_id: str, stage_key: str) -> StageDefinition:
    config = _get_config_or_404(db, project_id)
    stage_def = next((s for s in config.stages if s.stage_key == stage_key), None)
    if not stage_def:
        raise HTTPException(404, f"Stage '{stage_key}' not found")
    return stage_def


@stage_router.post("/{project_id}/resume")
async def resume_stage(
    project_id: str,
    req: ResumeRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(_require_writer),
):
    user_id = _user.id

    enqueue(db, "resume_stage", {
        "execution_id": req.execution_id,
        "action": req.action,
        "notes": req.notes,
        "edited_content": req.edited_content,
        "user_id": user_id,
    })
    return {"status": "resumed"}


@stage_router.post("/{project_id}/revise")
async def revise_artifact(
    project_id: str,
    req: ReviseRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(_require_writer),
):
    """Revise an approved artifact with AI using human feedback."""
    user_id = _user.id

    enqueue(db, "revise_artifact", {
        "artifact_id": req.artifact_id,
        "feedback": req.feedback,
        "user_id": user_id,
    })
    return {"status": "revision_started"}


@stage_router.post("/{project_id}/resolve-stale")
async def resolve_stale(
    project_id: str,
    req: ResolveStaleRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(_require_writer),
):
    """Approve, reject, or save feedback on a stale artifact."""
    user_id = _user.id

    enqueue(db, "resolve_stale", {
        "artifact_id": req.artifact_id,
        "action": req.action,
        "notes": req.notes,
        "edited_content": req.edited_content,
        "user_id": user_id,
    })
    return {"status": "resolving"}


@stage_router.post("/{project_id}/regen-downstream")
async def regen_downstream(
    project_id: str,
    req: RegenDownstreamRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(_require_writer),
):
    """Start a scoped run to regenerate already-generated downstream nodes."""
    enqueue(db, "regen_downstream", {
        "artifact_id": req.artifact_id,
    })
    return {"status": "regenerating"}


@stage_router.post("/{project_id}/cancel-stage/{execution_id}")
async def cancel_stage(
    project_id: str,
    execution_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(_require_writer),
):
    """Cancel a single running/pending/ai_review stage execution."""
    execution = db.get(StageExecution, execution_id)
    if not execution or execution.project_id != project_id:
        raise HTTPException(404, "Execution not found")

    cancelable = {"running", "ai_review", "pending"}
    if execution.status.value not in cancelable:
        raise HTTPException(
            400,
            f"Can only cancel running/pending/ai_review executions, "
            f"current status: {execution.status.value}",
        )

    # Determine safe artifact status: unstick GENERATING/AI_REVIEWING → PENDING
    art_status = None
    if execution.artifact_id:
        artifact = db.get(Artifact, execution.artifact_id)
        if artifact and artifact.status.value in ("generating", "ai_reviewing"):
            art_status = ArtifactStatus.PENDING

    engine = PipelineEngine(db)
    engine._transition_execution(
        execution, StageStatus.FAILED,
        artifact_status=art_status,
        error_message="Cancelled by user",
        set_completed=True,
    )

    db.commit()

    await ws_manager.broadcast(
        project_id,
        {
            "type": "stage_failed",
            "stage_key": execution.stage_key,
            "component_key": execution.component_key,
            "error": "Cancelled by user",
        },
    )

    return {"status": "cancelled", "execution_id": execution_id}


@stage_router.post("/{project_id}/force-restart/{execution_id}")
async def force_restart_stage(
    project_id: str,
    execution_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(_require_writer),
):
    """Force-restart a stuck or rejected execution.

    Resets the execution and its artifact to failed/pending state, then
    immediately retries via the job queue.
    """
    execution = db.get(StageExecution, execution_id)
    if not execution or execution.project_id != project_id:
        raise HTTPException(404, "Execution not found")

    restartable_statuses = {
        "running", "ai_review", "failed", "rejected",
        "awaiting_review", "approved",
    }
    if execution.status.value not in restartable_statuses:
        raise HTTPException(
            400,
            f"Cannot force-restart execution with status: {execution.status.value}",
        )

    # Reset execution to failed and artifact to pending so regeneration starts fresh.
    # This includes "approved" because a failed revision restores the artifact
    # to approved — the user explicitly wants to retry in that case too.
    art_status = None
    if execution.artifact_id:
        artifact = db.get(Artifact, execution.artifact_id)
        if artifact and artifact.status.value not in ("pending",):
            art_status = ArtifactStatus.PENDING

    engine = PipelineEngine(db)
    engine._transition_execution(
        execution, StageStatus.FAILED,
        artifact_status=art_status,
        error_message="Force-restarted by user",
        set_completed=True,
    )

    db.commit()

    # Broadcast so the UI updates immediately (include artifact_status so
    # components showing the approved/rejected badge can clear it).
    await ws_manager.broadcast(
        project_id,
        {
            "type": "stage_failed",
            "stage_key": execution.stage_key,
            "component_key": execution.component_key,
            "error": "Force-restarted by user",
            "artifact_id": execution.artifact_id,
            "artifact_status": "pending",
        },
    )

    # Cancel any in-flight work for this execution (kills CLI process + asyncio task)
    cancel_running_execution(execution_id)

    # Cancel any already-queued retry jobs for this execution to avoid duplicates
    cancel_jobs_by_type(db, "retry_stage", execution_id=execution_id)

    # Retry via job queue
    enqueue(db, "retry_stage", {"execution_id": execution_id})
    return {"status": "force_restarted", "execution_id": execution_id}


@stage_router.post("/{project_id}/trigger-stage")
async def trigger_stage(
    project_id: str,
    req: TriggerStageRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(_require_writer),
):
    """Manually trigger a single stage.  Useful for recovering from stuck
    pipeline states where no execution exists to force-restart."""
    config = _get_config_or_404(db, project_id)
    stage_def = next(
        (s for s in config.stages if s.stage_key == req.stage_key), None
    )
    if not stage_def:
        raise HTTPException(404, f"Stage '{req.stage_key}' not found")

    # Cancel any existing queued trigger/retry jobs for this stage to prevent
    # duplicate executions from concurrent requests.
    cancel_jobs_by_type(db, "trigger_stage", project_id=project_id, stage_key=req.stage_key)
    cancel_jobs_by_type(db, "retry_stage", stage_key=req.stage_key)

    enqueue(
        db,
        "trigger_stage",
        {
            "project_id": project_id,
            "stage_key": req.stage_key,
            "component_key": req.component_key,
        },
    )
    return {"status": "triggered", "stage_key": req.stage_key}


# ──── Stage Definition Config ────


@stage_router.put("/{project_id}/stages/{stage_key}", response_model=StageDefinitionResponse)
def update_stage_config(
    project_id: str,
    stage_key: str,
    req: StageDefinitionUpdate,
    db: Session = Depends(get_db),
    _user: User = Depends(_require_writer),
):
    stage_def = _get_stage_def(db, project_id, stage_key)

    if req.display_name is not None:
        stage_def.display_name = req.display_name
    if req.ai_review_enabled is not None:
        stage_def.ai_review_enabled = req.ai_review_enabled
    if req.human_review_enabled is not None:
        stage_def.human_review_enabled = req.human_review_enabled
    # Nullable overrides: use model_fields_set to distinguish "omitted" from "set to null"
    if "model_override" in req.model_fields_set:
        stage_def.model_override = req.model_override
    if "temperature_override" in req.model_fields_set:
        stage_def.temperature_override = req.temperature_override

    db.commit()
    db.refresh(stage_def)
    return StageDefinitionResponse.model_validate(stage_def)


@stage_router.post("/{project_id}/stages/{stage_key}/reset", response_model=StageDefinitionResponse)
def reset_stage_config(
    project_id: str,
    stage_key: str,
    db: Session = Depends(get_db),
    _user: User = Depends(_require_writer),
):
    stage_def = _get_stage_def(db, project_id, stage_key)
    defaults = next((s for s in DEFAULT_STAGES if s["stage_key"] == stage_key), None)
    if not defaults:
        raise HTTPException(404, f"No defaults found for stage '{stage_key}'")

    stage_def.display_name = defaults["display_name"]
    stage_def.model_override = defaults.get("model_override")
    stage_def.temperature_override = defaults.get("temperature_override")
    stage_def.ai_review_enabled = defaults.get("ai_review_enabled", True)
    stage_def.human_review_enabled = defaults.get("human_review_enabled", True)

    db.commit()
    db.refresh(stage_def)
    return StageDefinitionResponse.model_validate(stage_def)
