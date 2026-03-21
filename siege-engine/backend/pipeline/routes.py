import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.auth.routes import _require_writer, get_current_user
from backend.database import SessionLocal, get_db
from backend.models import (
    ExecutionMode,
    PipelineConfig,
    Project,
    StageDefinition,
    User,
)
from backend.pipeline.engine import PipelineEngine
from backend.pipeline.schemas import (
    PipelineConfigResponse,
    PipelineConfigUpdate,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def _get_project_or_404(db: Session, project_id: str) -> Project:
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    return project


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


def _check_blocking_pr(project: Project):
    """Raise 409 if this project has an unresolved blocking PR."""
    if project.blocking_pr_url:
        raise HTTPException(
            409,
            detail={
                "message": "A blocking PR must be merged or closed before starting a new run.",
                "blocking_pr_url": project.blocking_pr_url,
                "blocking_pr_number": project.blocking_pr_number,
            },
        )


def _get_stage_def(db: Session, project_id: str, stage_key: str) -> StageDefinition:
    config = _get_config_or_404(db, project_id)
    stage_def = next((s for s in config.stages if s.stage_key == stage_key), None)
    if not stage_def:
        raise HTTPException(404, f"Stage '{stage_key}' not found")
    return stage_def


@router.get("/{project_id}/config", response_model=PipelineConfigResponse)
def get_config(
    project_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    config = _get_config_or_404(db, project_id)
    return {
        "id": config.id,
        "execution_mode": config.execution_mode.value,
        "default_model": config.default_model,
        "default_temperature": config.default_temperature,
        "stages": [
            {
                "id": s.id,
                "stage_key": s.stage_key,
                "display_name": s.display_name,
                "order_index": s.order_index,
                "output_artifact_type": s.output_artifact_type,
                "input_stage_keys": s.input_stage_keys,
                "fan_out_strategy": s.fan_out_strategy.value,
                "ai_review_enabled": s.ai_review_enabled,
                "human_review_enabled": s.human_review_enabled,
                "prompt_template_key": s.prompt_template_key,
                "model_override": s.model_override,
                "temperature_override": s.temperature_override,
            }
            for s in sorted(config.stages, key=lambda s: s.order_index)
        ],
    }


@router.put("/{project_id}/config", response_model=PipelineConfigResponse)
def update_config(
    project_id: str,
    req: PipelineConfigUpdate,
    db: Session = Depends(get_db),
    _user: User = Depends(_require_writer),
):
    config = _get_config_or_404(db, project_id)

    if req.execution_mode:
        config.execution_mode = ExecutionMode(req.execution_mode)
    if req.default_model:
        config.default_model = req.default_model
    if req.default_temperature is not None:
        config.default_temperature = req.default_temperature

    db.commit()
    db.refresh(config)
    return get_config(project_id, db, _user)


from backend.pipeline.routes_input_docs import input_docs_router  # noqa: E402
from backend.pipeline.routes_pipeline import pipeline_router  # noqa: E402
from backend.pipeline.routes_prompt import prompt_router  # noqa: E402
from backend.pipeline.routes_stage import stage_router  # noqa: E402

router.include_router(pipeline_router)
router.include_router(stage_router)
router.include_router(prompt_router)
router.include_router(input_docs_router)
