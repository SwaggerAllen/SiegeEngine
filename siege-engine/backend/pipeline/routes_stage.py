import asyncio
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.auth.routes import _require_writer
from backend.database import SessionLocal, get_db
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
from backend.pipeline.schemas import (
    ResolveStaleRequest,
    ResumeRequest,
    ReviseRequest,
    StageDefinitionResponse,
    StageDefinitionUpdate,
)
from backend.websocket.manager import ws_manager

logger = logging.getLogger(__name__)

stage_router = APIRouter()


def _get_config_or_404(db: Session, project_id: str) -> PipelineConfig:
    config = db.query(PipelineConfig).filter_by(project_id=project_id).first()
    if not config:
        raise HTTPException(404, "Pipeline config not found")
    return config


def _run_in_background(coro_factory, log_msg: str = "Background task failed") -> None:
    """Schedule a coroutine factory to run in a background asyncio task.

    The factory receives a PipelineEngine and should return a coroutine.
    Each invocation gets its own DB session.
    """

    async def _run():
        bg_db = SessionLocal()
        try:
            engine = PipelineEngine(bg_db)
            await coro_factory(engine)
        except Exception:
            logger.exception(log_msg)
        finally:
            bg_db.close()

    asyncio.ensure_future(_run())


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
    # Run in a background task with its own DB session so that
    # rejection → regeneration (LLM call) doesn't block the request
    # and the session isn't closed mid-generation.
    user_id = _user.id

    _run_in_background(
        lambda eng: eng.resume_stage(
            req.execution_id, req.action, req.notes, req.edited_content, user_id=user_id
        ),
        f"resume_stage failed for execution_id={req.execution_id}",
    )
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

    _run_in_background(
        lambda eng: eng.revise_artifact(req.artifact_id, req.feedback, user_id=user_id),
        f"revise_artifact failed for artifact_id={req.artifact_id}",
    )
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

    _run_in_background(
        lambda eng: eng.resolve_stale(
            req.artifact_id, req.action, req.notes, req.edited_content, user_id=user_id
        ),
        f"resolve_stale failed for artifact_id={req.artifact_id}",
    )
    return {"status": "resolving"}


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

    execution.status = StageStatus.FAILED
    execution.error_message = "Cancelled by user"
    execution.completed_at = datetime.utcnow()

    # Reset any associated artifact stuck in generating/ai_reviewing
    if execution.artifact_id:
        artifact = db.get(Artifact, execution.artifact_id)
        if artifact and artifact.status.value in ("generating", "ai_reviewing"):
            artifact.status = ArtifactStatus.PENDING

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
    """Force-restart a stuck execution (running/ai_review/generating).

    Resets the execution and its artifact to failed state, then immediately
    retries. Use this when a CLI process died without triggering error handling.
    """
    execution = db.get(StageExecution, execution_id)
    if not execution or execution.project_id != project_id:
        raise HTTPException(404, "Execution not found")

    restartable_statuses = {"running", "ai_review", "failed"}
    if execution.status.value not in restartable_statuses:
        raise HTTPException(
            400,
            f"Can only force-restart stuck or failed executions (running/ai_review/failed), "
            f"current status: {execution.status.value}",
        )

    # Reset the execution to failed state
    execution.status = StageStatus.FAILED
    execution.error_message = "Force-restarted by user"
    execution.completed_at = datetime.utcnow()

    # Reset any associated artifact stuck in generating/ai_reviewing
    if execution.artifact_id:
        artifact = db.get(Artifact, execution.artifact_id)
        if artifact and artifact.status.value in ("generating", "ai_reviewing"):
            artifact.status = ArtifactStatus.PENDING

    db.flush()

    # Broadcast so the UI updates immediately
    await ws_manager.broadcast(
        project_id,
        {
            "type": "stage_failed",
            "stage_key": execution.stage_key,
            "component_key": execution.component_key,
            "error": "Force-restarted by user",
        },
    )

    # Now retry using the existing retry logic
    engine = PipelineEngine(db)
    await engine.retry_stage(execution)
    return {"status": "force_restarted", "execution_id": execution_id}


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
