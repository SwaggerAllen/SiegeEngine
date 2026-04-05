import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.auth.routes import _require_writer, get_current_user
from backend.database import get_db
from backend.models import (
    PipelineConfig,
    PromptConfig,
    StageDefinition,
    User,
)
from backend.pipeline.prompts import PROMPT_REGISTRY
from backend.pipeline.schemas import PromptConfigUpdate

logger = logging.getLogger(__name__)

prompt_router = APIRouter()


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


# ──── Prompt Config CRUD ────


@prompt_router.get("/{project_id}/prompts")
def list_prompt_configs(
    project_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    config = _get_config_or_404(db, project_id)

    result = []
    for stage_def in sorted(config.stages, key=lambda s: s.order_index):
        pc = stage_def.prompt_config
        prompt_class = PROMPT_REGISTRY.get(stage_def.prompt_template_key)
        if pc:
            result.append(
                {
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
                }
            )
        elif prompt_class:
            tmpl = prompt_class()
            result.append(
                {
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
                }
            )

    # Append the AI Review prompt entry
    ai_review_prompt_class = PROMPT_REGISTRY.get("ai_review")
    if ai_review_prompt_class:
        tmpl = ai_review_prompt_class()
        overrides = config.review_prompt_overrides
        if overrides:
            result.append(
                {
                    "stage_key": "__ai_review__",
                    "display_name": "AI Review",
                    "has_custom_config": True,
                    "config": {
                        "id": None,
                        "stage_definition_id": None,
                        "system_message": overrides.get(
                            "system_message", tmpl.default_system_message
                        ),
                        "output_format_instructions": overrides.get(
                            "output_format_instructions", tmpl.default_output_format
                        ),
                        "context_template": overrides.get(
                            "context_template", tmpl.default_context_template
                        ),
                        "revision_instructions": "",
                        "model": overrides.get("model"),
                        "temperature": overrides.get("temperature"),
                        "max_tokens": overrides.get("max_tokens", 8192),
                    },
                }
            )
        else:
            result.append(
                {
                    "stage_key": "__ai_review__",
                    "display_name": "AI Review",
                    "has_custom_config": False,
                    "config": {
                        "id": None,
                        "stage_definition_id": None,
                        "system_message": tmpl.default_system_message,
                        "output_format_instructions": tmpl.default_output_format,
                        "context_template": tmpl.default_context_template,
                        "revision_instructions": "",
                        "model": None,
                        "temperature": None,
                        "max_tokens": 8192,
                    },
                }
            )

    return result


@prompt_router.get("/{project_id}/prompts/{stage_key}")
def get_prompt_config(
    project_id: str,
    stage_key: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    # Handle AI review prompt separately
    if stage_key == "__ai_review__":
        config = _get_config_or_404(db, project_id)
        tmpl = PROMPT_REGISTRY["ai_review"]()
        overrides = config.review_prompt_overrides or {}
        return {
            "id": None,
            "stage_definition_id": None,
            "system_message": overrides.get("system_message", tmpl.default_system_message),
            "output_format_instructions": overrides.get(
                "output_format_instructions", tmpl.default_output_format
            ),
            "context_template": overrides.get("context_template", tmpl.default_context_template),
            "revision_instructions": "",
            "model": overrides.get("model"),
            "temperature": overrides.get("temperature"),
            "max_tokens": overrides.get("max_tokens", 8192),
        }

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


@prompt_router.put("/{project_id}/prompts/{stage_key}")
def update_prompt_config(
    project_id: str,
    stage_key: str,
    req: PromptConfigUpdate,
    db: Session = Depends(get_db),
    _user: User = Depends(_require_writer),
):
    # Handle AI review prompt separately
    if stage_key == "__ai_review__":
        config = _get_config_or_404(db, project_id)
        overrides = config.review_prompt_overrides or {}
        if req.system_message is not None:
            overrides["system_message"] = req.system_message
        if req.output_format_instructions is not None:
            overrides["output_format_instructions"] = req.output_format_instructions
        if req.context_template is not None:
            overrides["context_template"] = req.context_template
        if req.model is not None:
            overrides["model"] = req.model
        if req.temperature is not None:
            overrides["temperature"] = req.temperature
        if req.max_tokens is not None:
            overrides["max_tokens"] = req.max_tokens
        config.review_prompt_overrides = overrides
        db.commit()
        db.refresh(config)
        tmpl = PROMPT_REGISTRY["ai_review"]()
        return {
            "id": None,
            "stage_definition_id": None,
            "system_message": overrides.get("system_message", tmpl.default_system_message),
            "output_format_instructions": overrides.get(
                "output_format_instructions", tmpl.default_output_format
            ),
            "context_template": overrides.get("context_template", tmpl.default_context_template),
            "revision_instructions": "",
            "model": overrides.get("model"),
            "temperature": overrides.get("temperature"),
            "max_tokens": overrides.get("max_tokens", 8192),
        }

    stage_def = _get_stage_def(db, project_id, stage_key)
    pc = stage_def.prompt_config

    if not pc:
        # Create new PromptConfig from defaults
        prompt_class = PROMPT_REGISTRY.get(stage_def.prompt_template_key)
        tmpl2 = prompt_class() if prompt_class else None
        pc = PromptConfig(
            stage_definition_id=stage_def.id,
            system_message=tmpl2.default_system_message if tmpl2 else "",
            output_format_instructions=tmpl2.default_output_format if tmpl2 else "",
            context_template=tmpl2.default_context_template if tmpl2 else "",
            revision_instructions=tmpl2.default_revision_instructions if tmpl2 else "",
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


@prompt_router.post("/{project_id}/prompts/{stage_key}/reset")
def reset_prompt_config(
    project_id: str,
    stage_key: str,
    db: Session = Depends(get_db),
    _user: User = Depends(_require_writer),
):
    # Handle AI review prompt separately
    if stage_key == "__ai_review__":
        config = _get_config_or_404(db, project_id)
        config.review_prompt_overrides = None
        db.commit()
        return {"status": "reset"}

    stage_def = _get_stage_def(db, project_id, stage_key)
    pc = stage_def.prompt_config
    if pc:
        db.delete(pc)
        db.commit()
    return {"status": "reset"}
