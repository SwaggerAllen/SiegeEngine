import json
import logging
import re

from sqlalchemy.orm import Session

from backend.cli.manager import cli_manager
from backend.config import settings
from backend.git_manager.service import git_manager
from backend.models import (
    Artifact,
    ArtifactDependency,
    ArtifactStatus,
    ArtifactType,
    ComponentDefinition,
    StageDefinition,
)
from backend.pipeline.nodes.code_extractor import extract_code_files
from backend.pipeline.prompts import PROMPT_REGISTRY

logger = logging.getLogger(__name__)

# Map stage output types to artifact types
ARTIFACT_TYPE_MAP = {
    "system_requirements": ArtifactType.SYSTEM_REQUIREMENTS,
    "system_architecture": ArtifactType.SYSTEM_ARCHITECTURE,
    "component_architecture": ArtifactType.COMPONENT_ARCHITECTURE,
    "component_plan": ArtifactType.COMPONENT_PLAN,
    "component_map": ArtifactType.COMPONENT_MAP,
    "sub_component_map": ArtifactType.SUB_COMPONENT_MAP,
    "sub_component_architecture": ArtifactType.SUB_COMPONENT_ARCHITECTURE,
    "sub_component_plan": ArtifactType.SUB_COMPONENT_PLAN,
    "code": ArtifactType.CODE,
    "code_review": ArtifactType.CODE_REVIEW,
}

# Map artifact types to git file paths
FILE_PATH_MAP = {
    "system_requirements": "requirements/system_requirements.md",
    "system_architecture": "architecture/system_architecture.md",
    "component_architecture": "architecture/components/{component_key}.md",
    "component_plan": "plans/components/{component_key}.md",
    "component_map": "components/component_map.md",
    "sub_component_map": "components/{component_key}/sub_component_map.md",
    "sub_component_architecture": "architecture/sub_components/{component_key}.md",
    "sub_component_plan": "plans/sub_components/{component_key}.md",
    "code": "code/{component_key}/generated_code.md",
    "code_review": "code/{component_key}/code_review.md",
}


def build_prompt_messages(
    stage_def: StageDefinition,
    input_artifacts: dict[str, str],
    component_key: str | None,
    feedback: dict | None = None,
    human_notes: str | None = None,
    current_content: str | None = None,
    upstream_changes: str | None = None,
) -> dict:
    """
    Dry-run prompt build. Returns {messages, model, temperature}.

    Used by both generate() and the prompt-preview endpoint.
    """
    prompt_class = PROMPT_REGISTRY.get(stage_def.prompt_template_key)
    if not prompt_class:
        raise ValueError(f"Unknown prompt template: {stage_def.prompt_template_key}")

    prompt = prompt_class()

    # Load prompt config from DB if it exists
    pc = stage_def.prompt_config
    prompt_config_dict = None
    if pc:
        prompt_config_dict = {
            "system_message": pc.system_message,
            "output_format_instructions": pc.output_format_instructions,
            "context_template": pc.context_template,
            "revision_instructions": pc.revision_instructions,
        }

    messages = prompt.build(
        input_artifacts=input_artifacts,
        component_key=component_key,
        feedback=feedback,
        human_notes=human_notes,
        prompt_config=prompt_config_dict,
        current_content=current_content,
        upstream_changes=upstream_changes,
    )

    # Model selection: prompt config > stage def > default
    model_name = (
        (pc.model if pc and pc.model else None)
        or stage_def.model_override
        or "claude-sonnet-4-20250514"
    )

    return {
        "messages": messages,
        "model": model_name,
        "temperature": 1.0,
    }


async def generate(
    stage_def: StageDefinition,
    input_artifacts: dict[str, str],
    component_key: str | None,
    db: Session,
    feedback: dict | None = None,
    human_notes: str | None = None,
    current_content: str | None = None,
    upstream_changes: str | None = None,
) -> tuple[str, str]:
    """
    Run AI generation for a stage. Returns (content, artifact_id).
    """
    logger.info(
        "generate() called: template=%s, component=%s, input_keys=%s, revision=%s",
        stage_def.prompt_template_key,
        component_key,
        list(input_artifacts.keys()),
        bool(current_content or upstream_changes),
    )

    result = build_prompt_messages(
        stage_def,
        input_artifacts,
        component_key,
        feedback=feedback,
        human_notes=human_notes,
        current_content=current_content,
        upstream_changes=upstream_changes,
    )
    messages = result["messages"]
    model_name = result["model"]

    # Extract system and user messages for CLI invocation
    system_msg = next((m["content"] for m in messages if m["role"] == "system"), None)
    user_msgs = [m["content"] for m in messages if m["role"] == "user"]
    user_prompt = "\n\n".join(user_msgs)

    # Determine CLI settings based on stage type
    is_code_stage = stage_def.output_artifact_type in ("code", "code_review")
    project_id = stage_def.pipeline_config.project_id

    if is_code_stage:
        working_dir = str(git_manager.base_path / project_id)
        tools = "default"
        timeout = settings.cli_timeout_code
        max_budget = settings.cli_max_budget_code
    else:
        working_dir = None
        tools = "WebFetch,WebSearch"  # Research tools for document generation
        timeout = settings.cli_timeout_document
        max_budget = None

    logger.info(
        "CLI generate: model=%s, tools=%s, is_code=%s, messages=%d",
        model_name,
        tools,
        is_code_stage,
        len(messages),
    )
    content = await cli_manager.generate(
        prompt=user_prompt,
        system_prompt=system_msg,
        working_dir=working_dir,
        model=model_name,
        tools=tools,
        timeout=timeout,
        max_budget_usd=max_budget,
    )
    logger.info("CLI response received: %d chars", len(content) if content else 0)

    # Determine file path
    file_path_template = FILE_PATH_MAP.get(
        stage_def.output_artifact_type, "artifacts/{stage_key}.md"
    )
    file_path = file_path_template.format(
        component_key=component_key or "default",
        stage_key=stage_def.stage_key,
    )

    # Create or update artifact
    artifact_type = ARTIFACT_TYPE_MAP.get(stage_def.output_artifact_type, ArtifactType.CODE)
    artifact_name = stage_def.display_name
    if component_key:
        artifact_name = f"{stage_def.display_name} - {component_key}"

    # Check for existing artifact to update
    existing = (
        db.query(Artifact)
        .filter_by(
            project_id=stage_def.pipeline_config.project_id,
            artifact_type=artifact_type,
            component_key=component_key,
        )
        .first()
    )

    if existing:
        existing.content = content
        existing.status = ArtifactStatus.GENERATING
        existing.version += 1
        existing.ai_review_feedback = None
        artifact = existing
    else:
        artifact = Artifact(
            project_id=stage_def.pipeline_config.project_id,
            artifact_type=artifact_type,
            name=artifact_name,
            component_key=component_key,
            content=content,
            status=ArtifactStatus.GENERATING,
            file_path=file_path,
        )
        db.add(artifact)

    db.flush()

    # Commit to git
    sha = git_manager.commit_artifact(
        stage_def.pipeline_config.project_id,
        content,
        file_path,
        f"Generate {artifact_name} v{artifact.version}",
    )
    artifact.git_commit_sha = sha

    # For code generation stages, extract individual files and commit them
    if stage_def.output_artifact_type == "code":
        code_files = extract_code_files(content)
        for cf in code_files:
            code_path = f"code/{component_key or 'default'}/{cf['file_path']}"
            git_manager.commit_artifact(
                stage_def.pipeline_config.project_id,
                cf["content"],
                code_path,
                f"Extract {cf['file_path']} from {artifact_name}",
            )

    # Create dependency edges from input artifacts
    project_id = stage_def.pipeline_config.project_id
    for input_stage_key in stage_def.input_stage_keys:
        upstream_artifacts = (
            db.query(Artifact)
            .filter_by(project_id=project_id)
            .filter(
                Artifact.artifact_type.in_([at for at in ArtifactType if at.value != "project_doc"])
            )
            .all()
        )
        for upstream in upstream_artifacts:
            # Check if this upstream artifact belongs to the input stage
            type_matches = upstream.artifact_type.value == _stage_key_to_type(input_stage_key)
            component_matches = (
                component_key is None
                or upstream.component_key is None
                or upstream.component_key == component_key
            )
            if type_matches and component_matches:
                # Only add if edge doesn't exist
                existing_dep = (
                    db.query(ArtifactDependency)
                    .filter_by(
                        upstream_artifact_id=upstream.id,
                        downstream_artifact_id=artifact.id,
                    )
                    .first()
                )
                if not existing_dep:
                    dep = ArtifactDependency(
                        upstream_artifact_id=upstream.id,
                        downstream_artifact_id=artifact.id,
                        stage_key=stage_def.stage_key,
                    )
                    db.add(dep)

    # Create dependency edges for cross-component dependency architectures
    # (injected by _gather_inputs but not covered by input_stage_keys)
    if component_key:
        parent_key = component_key.split(".")[0] if "." in component_key else None
        if parent_key:
            # Sub-component: look up sibling dependencies
            sc_key = component_key.split(".")[-1]
            comp_def = (
                db.query(ComponentDefinition)
                .filter_by(project_id=project_id, key=sc_key, parent_key=parent_key)
                .first()
            )
            dep_art_type = ArtifactType.SUB_COMPONENT_ARCHITECTURE
            dep_key_fn = lambda dk: f"{parent_key}.{dk}"  # noqa: E731
        else:
            comp_def = (
                db.query(ComponentDefinition)
                .filter_by(project_id=project_id, key=component_key, parent_key=None)
                .first()
            )
            dep_art_type = ArtifactType.COMPONENT_ARCHITECTURE
            dep_key_fn = lambda dk: dk  # noqa: E731

        if comp_def and comp_def.dependencies:
            for dep_key in comp_def.dependencies:
                dep_art = (
                    db.query(Artifact)
                    .filter_by(
                        project_id=project_id,
                        artifact_type=dep_art_type,
                        component_key=dep_key_fn(dep_key),
                    )
                    .filter(
                        Artifact.status.in_([ArtifactStatus.APPROVED, ArtifactStatus.AWAITING_REVIEW])
                    )
                    .first()
                )
                if dep_art:
                    existing_dep = (
                        db.query(ArtifactDependency)
                        .filter_by(
                            upstream_artifact_id=dep_art.id,
                            downstream_artifact_id=artifact.id,
                        )
                        .first()
                    )
                    if not existing_dep:
                        db.add(
                            ArtifactDependency(
                                upstream_artifact_id=dep_art.id,
                                downstream_artifact_id=artifact.id,
                                stage_key=stage_def.stage_key,
                            )
                        )

    db.flush()
    return content, artifact.id


def extract_components(content: str) -> list[dict]:
    """Extract component list from architecture output."""
    pattern = r"```components\s*\n(.*?)```"
    match = re.search(pattern, content, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    # Fallback: try to find JSON array in the content
    pattern = r'\[[\s\S]*?"key"[\s\S]*?\]'
    match = re.search(pattern, content)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    return []


def _stage_key_to_type(stage_key: str) -> str:
    mapping = {
        "system_requirements": "system_requirements",
        "system_architecture": "system_architecture",
        "component_architectures": "component_architecture",
        "component_plans": "component_plan",
        "extract_components": "component_map",
        "extract_sub_components": "sub_component_map",
        "sub_component_architectures": "sub_component_architecture",
        "sub_component_plans": "sub_component_plan",
        "code_generation": "code",
        "code_review": "code_review",
    }
    return mapping.get(stage_key, stage_key)
