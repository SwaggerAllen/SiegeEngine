import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from jose import JWTError
from sqlalchemy.orm import Session

from backend.auth.routes import get_current_user
from backend.auth.service import decode_token
from backend.dag.service import get_regeneration_order, get_stale_artifacts
from backend.database import get_db
from backend.models import (
    ExecutionMode,
    PipelineConfig,
    Project,
    PromptConfig,
    StageDefinition,
    StageExecution,
    StageStatus,
    User,
)
from backend.pipeline.engine import PipelineEngine
from backend.pipeline.prompts import PROMPT_REGISTRY
from backend.pipeline.schemas import (
    PipelineConfigResponse,
    PipelineConfigUpdate,
    PipelineStartRequest,
    PromptConfigResponse,
    PromptConfigUpdate,
    RegenerateRequest,
    ResumeRequest,
    StageExecutionResponse,
)
from backend.websocket.manager import ws_manager

router = APIRouter()


@router.get("/{project_id}/config", response_model=PipelineConfigResponse)
def get_config(
    project_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    config = db.query(PipelineConfig).filter_by(project_id=project_id).first()
    if not config:
        raise HTTPException(404, "Pipeline config not found")
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
            }
            for s in config.stages
        ],
    }


@router.put("/{project_id}/config", response_model=PipelineConfigResponse)
def update_config(
    project_id: str,
    req: PipelineConfigUpdate,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    config = db.query(PipelineConfig).filter_by(project_id=project_id).first()
    if not config:
        raise HTTPException(404, "Pipeline config not found")

    if req.execution_mode:
        config.execution_mode = ExecutionMode(req.execution_mode)
    if req.default_model:
        config.default_model = req.default_model
    if req.default_temperature is not None:
        config.default_temperature = req.default_temperature

    db.commit()
    db.refresh(config)
    return get_config(project_id, db, _user)


@router.post("/{project_id}/start")
async def start_pipeline(
    project_id: str,
    req: PipelineStartRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    engine = PipelineEngine(db)
    mode = ExecutionMode(req.execution_mode) if req.execution_mode else None

    # Run pipeline in background
    run_id_future = asyncio.ensure_future(engine.start_pipeline(project_id, mode))

    # Wait briefly to get the run_id
    await asyncio.sleep(0.1)

    return {"status": "started", "message": "Pipeline execution started"}


@router.post("/{project_id}/resume")
async def resume_stage(
    project_id: str,
    req: ResumeRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    engine = PipelineEngine(db)
    await engine.resume_stage(
        req.execution_id, req.action, req.notes, req.edited_content
    )
    return {"status": "resumed"}


@router.post("/{project_id}/regenerate")
async def regenerate(
    project_id: str,
    req: RegenerateRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    order = get_regeneration_order(db, req.artifact_ids)
    return {
        "status": "regeneration_started",
        "order": order,
        "levels": len(order),
    }


@router.get("/{project_id}/status")
def get_status(
    project_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    executions = (
        db.query(StageExecution)
        .filter_by(project_id=project_id)
        .order_by(StageExecution.started_at.desc())
        .all()
    )
    return {
        "stages": [
            {
                "id": e.id,
                "stage_key": e.stage_key,
                "component_key": e.component_key,
                "status": e.status.value,
                "artifact_id": e.artifact_id,
                "started_at": e.started_at.isoformat() if e.started_at else None,
                "completed_at": e.completed_at.isoformat() if e.completed_at else None,
                "error_message": e.error_message,
                "run_id": e.run_id,
            }
            for e in executions
        ]
    }


@router.post("/{project_id}/cancel")
def cancel_pipeline(
    project_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    # Mark all running/pending executions as failed
    running = (
        db.query(StageExecution)
        .filter_by(project_id=project_id)
        .filter(StageExecution.status.in_([StageStatus.RUNNING, StageStatus.PENDING, StageStatus.AI_REVIEW]))
        .all()
    )
    for e in running:
        e.status = StageStatus.FAILED
        e.error_message = "Cancelled by user"
    db.commit()
    return {"status": "cancelled", "cancelled_count": len(running)}


# ──── Prompt Config CRUD ────


def _get_stage_def(db: Session, project_id: str, stage_key: str) -> StageDefinition:
    config = db.query(PipelineConfig).filter_by(project_id=project_id).first()
    if not config:
        raise HTTPException(404, "Pipeline config not found")
    stage_def = next((s for s in config.stages if s.stage_key == stage_key), None)
    if not stage_def:
        raise HTTPException(404, f"Stage '{stage_key}' not found")
    return stage_def


@router.get("/{project_id}/prompts")
def list_prompt_configs(
    project_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    config = db.query(PipelineConfig).filter_by(project_id=project_id).first()
    if not config:
        raise HTTPException(404, "Pipeline config not found")

    result = []
    for stage_def in config.stages:
        pc = stage_def.prompt_config
        prompt_class = PROMPT_REGISTRY.get(stage_def.prompt_template_key)
        if pc:
            result.append({
                "stage_key": stage_def.stage_key,
                "display_name": stage_def.display_name,
                "has_custom_config": True,
                "config": {
                    "id": pc.id,
                    "stage_definition_id": pc.stage_definition_id,
                    "system_message": pc.system_message,
                    "output_format_instructions": pc.output_format_instructions,
                    "context_template": pc.context_template,
                    "revision_instructions": pc.revision_instructions,
                    "model": pc.model,
                    "temperature": pc.temperature,
                    "max_tokens": pc.max_tokens,
                },
            })
        elif prompt_class:
            tmpl = prompt_class()
            result.append({
                "stage_key": stage_def.stage_key,
                "display_name": stage_def.display_name,
                "has_custom_config": False,
                "config": {
                    "id": None,
                    "stage_definition_id": stage_def.id,
                    "system_message": tmpl.default_system_message,
                    "output_format_instructions": tmpl.default_output_format,
                    "context_template": tmpl.default_context_template,
                    "revision_instructions": tmpl.default_revision_instructions,
                    "model": None,
                    "temperature": None,
                    "max_tokens": 8192,
                },
            })
    return result


@router.get("/{project_id}/prompts/{stage_key}")
def get_prompt_config(
    project_id: str,
    stage_key: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    stage_def = _get_stage_def(db, project_id, stage_key)
    pc = stage_def.prompt_config
    prompt_class = PROMPT_REGISTRY.get(stage_def.prompt_template_key)

    if pc:
        return {
            "id": pc.id,
            "stage_definition_id": pc.stage_definition_id,
            "system_message": pc.system_message,
            "output_format_instructions": pc.output_format_instructions,
            "context_template": pc.context_template,
            "revision_instructions": pc.revision_instructions,
            "model": pc.model,
            "temperature": pc.temperature,
            "max_tokens": pc.max_tokens,
        }
    elif prompt_class:
        tmpl = prompt_class()
        return {
            "id": None,
            "stage_definition_id": stage_def.id,
            "system_message": tmpl.default_system_message,
            "output_format_instructions": tmpl.default_output_format,
            "context_template": tmpl.default_context_template,
            "revision_instructions": tmpl.default_revision_instructions,
            "model": None,
            "temperature": None,
            "max_tokens": 8192,
        }
    raise HTTPException(404, "No prompt template found for this stage")


@router.put("/{project_id}/prompts/{stage_key}")
def update_prompt_config(
    project_id: str,
    stage_key: str,
    req: PromptConfigUpdate,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    stage_def = _get_stage_def(db, project_id, stage_key)
    pc = stage_def.prompt_config

    if not pc:
        # Create new PromptConfig from defaults
        prompt_class = PROMPT_REGISTRY.get(stage_def.prompt_template_key)
        tmpl = prompt_class() if prompt_class else None
        pc = PromptConfig(
            stage_definition_id=stage_def.id,
            system_message=tmpl.default_system_message if tmpl else "",
            output_format_instructions=tmpl.default_output_format if tmpl else "",
            context_template=tmpl.default_context_template if tmpl else "",
            revision_instructions=tmpl.default_revision_instructions if tmpl else "",
        )
        db.add(pc)

    # Apply updates
    if req.system_message is not None:
        pc.system_message = req.system_message
    if req.output_format_instructions is not None:
        pc.output_format_instructions = req.output_format_instructions
    if req.context_template is not None:
        pc.context_template = req.context_template
    if req.revision_instructions is not None:
        pc.revision_instructions = req.revision_instructions
    if req.model is not None:
        pc.model = req.model
    if req.temperature is not None:
        pc.temperature = req.temperature
    if req.max_tokens is not None:
        pc.max_tokens = req.max_tokens

    db.commit()
    db.refresh(pc)
    return {
        "id": pc.id,
        "stage_definition_id": pc.stage_definition_id,
        "system_message": pc.system_message,
        "output_format_instructions": pc.output_format_instructions,
        "context_template": pc.context_template,
        "revision_instructions": pc.revision_instructions,
        "model": pc.model,
        "temperature": pc.temperature,
        "max_tokens": pc.max_tokens,
    }


@router.post("/{project_id}/prompts/{stage_key}/reset")
def reset_prompt_config(
    project_id: str,
    stage_key: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    stage_def = _get_stage_def(db, project_id, stage_key)
    pc = stage_def.prompt_config
    if pc:
        db.delete(pc)
        db.commit()
    return {"status": "reset"}


@router.post("/{project_id}/retry/{execution_id}")
async def retry_stage(
    project_id: str,
    execution_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    execution = db.get(StageExecution, execution_id)
    if not execution or execution.project_id != project_id:
        raise HTTPException(404, "Execution not found")
    if execution.status.value != "failed":
        raise HTTPException(400, "Can only retry failed executions")

    engine = PipelineEngine(db)
    await engine.retry_stage(execution)
    return {"status": "retrying", "execution_id": execution_id}


@router.websocket("/{project_id}/ws")
async def pipeline_websocket(
    websocket: WebSocket,
    project_id: str,
    token: str = Query(...),
):
    try:
        decode_token(token)
    except (JWTError, Exception):
        await websocket.close(code=4001, reason="Invalid token")
        return

    await ws_manager.connect(project_id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(project_id, websocket)
