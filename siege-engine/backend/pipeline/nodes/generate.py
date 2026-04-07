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
    "feature_expansion": ArtifactType.FEATURE_EXPANSION,
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
    # Frontend DAG artifact types
    "frontend_component_map": ArtifactType.FRONTEND_COMPONENT_MAP,
    "frontend_component_architecture": ArtifactType.FRONTEND_COMPONENT_ARCHITECTURE,
    "frontend_component_plan": ArtifactType.FRONTEND_COMPONENT_PLAN,
    "frontend_sub_component_map": ArtifactType.FRONTEND_SUB_COMPONENT_MAP,
    "frontend_sub_component_architecture": ArtifactType.FRONTEND_SUB_COMPONENT_ARCHITECTURE,
    "frontend_sub_component_plan": ArtifactType.FRONTEND_SUB_COMPONENT_PLAN,
    "frontend_code": ArtifactType.FRONTEND_CODE,
    "frontend_code_review": ArtifactType.FRONTEND_CODE_REVIEW,
}

# Map artifact types to git file paths
FILE_PATH_MAP = {
    "feature_expansion": "features/feature_expansion.md",
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
    # Frontend DAG file paths
    "frontend_component_map": "frontend/components/component_map.md",
    "frontend_component_architecture": "frontend/architecture/components/{component_key}.md",
    "frontend_component_plan": "frontend/plans/components/{component_key}.md",
    "frontend_sub_component_map": "frontend/components/{component_key}/sub_component_map.md",
    "frontend_sub_component_architecture": (
        "frontend/architecture/sub_components/{component_key}.md"
    ),
    "frontend_sub_component_plan": "frontend/plans/sub_components/{component_key}.md",
    "frontend_code": "frontend/code/{component_key}/generated_code.md",
    "frontend_code_review": "frontend/code/{component_key}/code_review.md",
}


def build_prompt_messages(
    stage_def: StageDefinition,
    input_artifacts: dict[str, str],
    component_key: str | None,
    human_notes: str | None = None,
    current_content: str | None = None,
    upstream_changes: str | None = None,
    prompt_template_override: str | None = None,
) -> dict:
    """
    Dry-run prompt build. Returns {messages, model, temperature}.

    Used by both generate() and the prompt-preview endpoint.
    """
    effective_key = prompt_template_override or stage_def.prompt_template_key
    prompt_class = PROMPT_REGISTRY.get(effective_key)
    if not prompt_class:
        raise ValueError(f"Unknown prompt template: {effective_key}")

    prompt = prompt_class()

    messages = prompt.build(
        input_artifacts=input_artifacts,
        component_key=component_key,
        human_notes=human_notes,
        current_content=current_content,
        upstream_changes=upstream_changes,
    )

    # Model selection: stage def > default
    model_name = stage_def.model_override or "claude-sonnet-4-20250514"

    return {
        "messages": messages,
        "model": model_name,
        "temperature": 1.0,
    }


# Stage keys whose outputs come from fan-out (multiple artifacts per type)
_FANOUT_STAGE_KEYS = {
    "component_architectures",
    "extract_sub_components",
    "component_plans",
    "sub_component_architectures",
    "sub_component_plans",
    "code_generation",
    "code_review",
}

# 90% of Claude Code's 200k token context window
CONTEXT_BUDGET_CHARS = 180_000 * 4  # ~720k chars ≈ 180k tokens


def _estimate_prompt_chars(messages: list[dict]) -> int:
    """Estimate total character count across all prompt messages."""
    return sum(len(m.get("content", "")) for m in messages)


def _build_fanout_summary_content(
    db: Session,
    project_id: str,
    stage_key: str,
) -> str | None:
    """Build aggregated content from fan-out artifact summaries.

    Returns the combined summary text if all artifacts have summaries,
    or None if any are missing.
    """
    artifact_type = _stage_key_to_type(stage_key)
    at = ARTIFACT_TYPE_MAP.get(artifact_type)
    if not at:
        return None

    artifacts = db.query(Artifact).filter_by(project_id=project_id, artifact_type=at).all()
    artifacts_with_content = [a for a in artifacts if a.content]
    if not artifacts_with_content:
        return None

    # Check all have summaries
    if any(a.summary is None for a in artifacts_with_content):
        return None

    return "\n\n---\n\n".join(
        f"### {a.component_key or a.name}\n\n{a.summary}" for a in artifacts_with_content
    )


def _build_dependency_summary_content(
    db: Session,
    project_id: str,
    component_key: str | None,
) -> tuple[str | None, list[tuple[str, int]]]:
    """Build dependency architectures using summaries where available.

    Returns (summarized_content_or_None, [(dep_key, content_len), ...])
    sorted by content length descending for budget swap ordering.
    """
    if not component_key:
        return None, []

    parent_key = component_key.split(".")[0] if "." in component_key else None

    if parent_key:
        sc_key = component_key.split(".")[-1]
        comp_def = (
            db.query(ComponentDefinition)
            .filter_by(project_id=project_id, key=sc_key, parent_key=parent_key)
            .first()
        )
        art_type = ArtifactType.SUB_COMPONENT_ARCHITECTURE

        def key_fn(dk: str) -> str:
            return f"{parent_key}.{dk}"

    else:
        comp_def = (
            db.query(ComponentDefinition)
            .filter_by(project_id=project_id, key=component_key, parent_key=None)
            .first()
        )
        art_type = ArtifactType.COMPONENT_ARCHITECTURE

        def key_fn(dk: str) -> str:
            return dk

    if not comp_def or not comp_def.dependencies:
        return None, []

    # Collect dep artifacts sorted by content size descending
    dep_artifacts = []
    for dep_key in comp_def.dependencies:
        full_key = key_fn(dep_key)
        dep_art = (
            db.query(Artifact)
            .filter_by(project_id=project_id, artifact_type=art_type, component_key=full_key)
            .first()
        )
        if dep_art and dep_art.content:
            dep_artifacts.append((full_key, dep_art))

    dep_artifacts.sort(key=lambda x: len(x[1].content or ""), reverse=True)

    # Try building with summaries for largest first
    parts = []
    for full_key, dep_art in dep_artifacts:
        text = dep_art.summary if dep_art.summary else dep_art.content
        parts.append(f"### {full_key}\n\n{text}")

    if parts:
        return "\n\n---\n\n".join(parts), [(k, len(a.content or "")) for k, a in dep_artifacts]
    return None, []


async def apply_context_budget(
    input_artifacts: dict[str, str],
    stage_def: StageDefinition,
    component_key: str | None,
    db: Session,
    human_notes: str | None = None,
    current_content: str | None = None,
    upstream_changes: str | None = None,
    prompt_template_override: str | None = None,
) -> tuple[dict[str, str], list[str]]:
    """Apply context budget to input artifacts, swapping summaries as needed.

    Returns (final_input_artifacts, list_of_summarized_input_keys).

    Three tiers of summarization:
    1. Fan-out aggregated inputs ALWAYS use summaries (when available)
    2. Dependency architectures swap to summaries biggest-first if over budget
    3. Direct inputs get hot-path summarized if still over budget
    """
    project_id = stage_def.pipeline_config.project_id
    result = dict(input_artifacts)
    summarized_keys: list[str] = []

    # --- Tier 2: Fan-out aggregated inputs always use summaries ---
    for stage_key in stage_def.input_stage_keys:
        if stage_key in _FANOUT_STAGE_KEYS and stage_key in result:
            summary_content = _build_fanout_summary_content(db, project_id, stage_key)
            if summary_content:
                result[stage_key] = summary_content
                summarized_keys.append(stage_key)

    # Check budget after tier 2
    messages = build_prompt_messages(
        stage_def,
        result,
        component_key,
        human_notes=human_notes,
        current_content=current_content,
        upstream_changes=upstream_changes,
        prompt_template_override=prompt_template_override,
    )["messages"]
    total_chars = _estimate_prompt_chars(messages)

    if total_chars <= CONTEXT_BUDGET_CHARS:
        return result, summarized_keys

    # --- Tier 1: Dependency architectures — swap biggest-first to summaries ---
    if "dependency_architectures" in result and component_key:
        dep_summary, _ = _build_dependency_summary_content(db, project_id, component_key)
        if dep_summary:
            result["dependency_architectures"] = dep_summary
            summarized_keys.append("dependency_architectures")

            # Re-check budget
            messages = build_prompt_messages(
                stage_def,
                result,
                component_key,
                human_notes=human_notes,
                current_content=current_content,
                upstream_changes=upstream_changes,
                prompt_template_override=prompt_template_override,
            )["messages"]
            total_chars = _estimate_prompt_chars(messages)

            if total_chars <= CONTEXT_BUDGET_CHARS:
                return result, summarized_keys

    # --- Tier 3: Hot-path summarization of direct inputs ---
    from backend.pipeline.summarize import generate_hotpath_summary

    # Sort direct inputs by size descending (exclude already-summarized keys)
    direct_keys = sorted(
        [k for k in result if k not in summarized_keys and k != "input_documents"],
        key=lambda k: len(result[k]),
        reverse=True,
    )

    for key in direct_keys:
        if total_chars <= CONTEXT_BUDGET_CHARS:
            break

        # Check if the source artifact already has a summary we can use
        artifact_type_str = _stage_key_to_type(key)
        at = ARTIFACT_TYPE_MAP.get(artifact_type_str)
        if at:
            source_art = (
                db.query(Artifact)
                .filter_by(project_id=project_id, artifact_type=at, component_key=component_key)
                .first()
            )
            if source_art and source_art.summary:
                result[key] = source_art.summary
                summarized_keys.append(key)
                messages = build_prompt_messages(
                    stage_def,
                    result,
                    component_key,
                    human_notes=human_notes,
                    current_content=current_content,
                    upstream_changes=upstream_changes,
                    prompt_template_override=prompt_template_override,
                )["messages"]
                total_chars = _estimate_prompt_chars(messages)
                continue

        # Generate hot-path summary on demand
        summary = await generate_hotpath_summary(
            result[key],
            stage_def.output_artifact_type,
            component_key,
        )
        if summary:
            # Save to source artifact for reuse
            if at and source_art:
                source_art.summary = summary
                db.flush()
            result[key] = summary
            summarized_keys.append(key)

            messages = build_prompt_messages(
                stage_def,
                result,
                component_key,
                human_notes=human_notes,
                current_content=current_content,
                upstream_changes=upstream_changes,
                prompt_template_override=prompt_template_override,
            )["messages"]
            total_chars = _estimate_prompt_chars(messages)

    # If still over budget after all tiers, truncate the largest remaining input
    if total_chars > CONTEXT_BUDGET_CHARS:
        largest_key = max(result, key=lambda k: len(result[k]))
        overage = total_chars - CONTEXT_BUDGET_CHARS
        result[largest_key] = result[largest_key][: len(result[largest_key]) - overage]
        logger.warning(
            "Context budget exceeded after all tiers, truncated %s by %d chars",
            largest_key,
            overage,
        )

    return result, summarized_keys


async def generate(
    stage_def: StageDefinition,
    input_artifacts: dict[str, str],
    component_key: str | None,
    db: Session,
    human_notes: str | None = None,
    current_content: str | None = None,
    upstream_changes: str | None = None,
    execution_id: str | None = None,
    prompt_template_override: str | None = None,
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

    # Apply context budget — swap summaries for large inputs as needed
    budgeted_artifacts, summarized_keys = await apply_context_budget(
        input_artifacts,
        stage_def,
        component_key,
        db,
        human_notes=human_notes,
        current_content=current_content,
        upstream_changes=upstream_changes,
        prompt_template_override=prompt_template_override,
    )
    if summarized_keys:
        logger.info("Context budget: summarized inputs %s", summarized_keys)

    result = build_prompt_messages(
        stage_def,
        budgeted_artifacts,
        component_key,
        human_notes=human_notes,
        current_content=current_content,
        upstream_changes=upstream_changes,
        prompt_template_override=prompt_template_override,
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
        execution_id=execution_id,
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
        existing.summary = None
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
                        Artifact.status.in_(
                            [ArtifactStatus.APPROVED, ArtifactStatus.AWAITING_REVIEW]
                        )
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
        "feature_expansion": "feature_expansion",
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
        # Frontend DAG stages
        "fe_component_architectures": "frontend_component_architecture",
        "fe_extract_sub_components": "frontend_sub_component_map",
        "fe_component_plans": "frontend_component_plan",
        "fe_sub_component_architectures": "frontend_sub_component_architecture",
        "fe_sub_component_plans": "frontend_sub_component_plan",
        "fe_code_generation": "frontend_code",
        "fe_code_review": "frontend_code_review",
    }
    return mapping.get(stage_key, stage_key)
