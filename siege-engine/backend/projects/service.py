import logging
import shutil
import uuid
from pathlib import Path

from sqlalchemy.orm import Session

from backend.config import settings
from backend.git_manager.service import git_manager
from backend.models import (
    Artifact,
    ArtifactComment,
    ArtifactDependency,
    ArtifactStatus,
    ArtifactType,
    ComponentDefinition,
    InputDocument,
    PipelineConfig,
    PipelineSnapshot,
    Project,
    PromptConfig,
    StageDefinition,
)
from backend.pipeline.defaults import DEFAULT_STAGES

logger = logging.getLogger(__name__)

_CLAUDE_MD_TEMPLATE = (
    Path(__file__).resolve().parent.parent / "cli" / "claude_md_template.md"
).read_text()


def create_project(
    db: Session, name: str, description: str | None, project_doc_content: str
) -> Project:
    project = Project(name=name, description=description, git_repo_path="")
    db.add(project)
    db.flush()

    # Init git repo
    repo_path = git_manager.init_repo(project.id)
    project.git_repo_path = repo_path

    # Write CLAUDE.md to give CLI context about the project
    claude_md = _CLAUDE_MD_TEMPLATE.format(
        project_name=name,
        project_description=description or "",
    )
    git_manager.commit_artifact(
        project.id,
        claude_md,
        "CLAUDE.md",
        "Add CLAUDE.md for CLI context",
    )

    # Create project doc artifact
    artifact = Artifact(
        project_id=project.id,
        artifact_type=ArtifactType.PROJECT_DOC,
        name="Project Document",
        content=project_doc_content,
        status=ArtifactStatus.APPROVED,
        file_path="project_doc.md",
    )
    db.add(artifact)
    db.flush()

    # Commit project doc to git
    sha = git_manager.commit_artifact(
        project.id,
        project_doc_content,
        "project_doc.md",
        "Initial project document",
    )
    artifact.git_commit_sha = sha

    # Seed default pipeline config
    config = PipelineConfig(
        project_id=project.id,
        default_model=settings.default_model,
        default_temperature=settings.default_temperature,
    )
    db.add(config)
    db.flush()

    for stage_data in DEFAULT_STAGES:
        stage = StageDefinition(pipeline_config_id=config.id, **stage_data)
        db.add(stage)

    db.commit()
    db.refresh(project)
    return project


def get_project(db: Session, project_id: str) -> Project | None:
    return db.get(Project, project_id)


def list_projects(db: Session) -> list[Project]:
    return db.query(Project).order_by(Project.created_at.desc()).all()


def update_project(
    db: Session, project_id: str, name: str | None, description: str | None
) -> Project | None:
    project = db.get(Project, project_id)
    if not project:
        return None
    if name is not None:
        project.name = name
    if description is not None:
        project.description = description
    db.commit()
    db.refresh(project)
    return project


def delete_project(db: Session, project_id: str) -> bool:
    project = db.get(Project, project_id)
    if not project:
        return False
    git_manager.delete_repo(project_id)
    db.delete(project)
    db.commit()
    return True


def clone_project(db: Session, source_project_id: str, new_name: str | None = None) -> Project:
    """Clone a project: copy git repo, artifacts, config, components.

    Skips pipeline events, runs, executions, and chat history.
    Builds a fresh snapshot from the cloned artifact data.
    """
    source = db.get(Project, source_project_id)
    if not source:
        raise ValueError("Source project not found")

    # Create new project record
    clone_name = new_name or f"{source.name} (copy)"
    new_project = Project(
        name=clone_name,
        description=source.description,
        git_repo_path="",
    )
    db.add(new_project)
    db.flush()

    # Copy git repo directory
    src_repo = Path(settings.git_repos_base_path) / source_project_id
    dst_repo = Path(settings.git_repos_base_path) / new_project.id
    if src_repo.exists():
        shutil.copytree(str(src_repo), str(dst_repo))
    else:
        git_manager.init_repo(new_project.id)
    new_project.git_repo_path = str(dst_repo)

    # Clone pipeline config + stage definitions + prompt configs
    src_config = db.query(PipelineConfig).filter_by(project_id=source_project_id).first()
    if src_config:
        new_config = PipelineConfig(
            project_id=new_project.id,
            execution_mode=src_config.execution_mode,
            default_model=src_config.default_model,
            default_temperature=src_config.default_temperature,
            review_prompt_overrides=src_config.review_prompt_overrides,
        )
        db.add(new_config)
        db.flush()

        for sd in src_config.stages:
            new_sd = StageDefinition(
                pipeline_config_id=new_config.id,
                stage_key=sd.stage_key,
                display_name=sd.display_name,
                order_index=sd.order_index,
                output_artifact_type=sd.output_artifact_type,
                input_stage_keys=sd.input_stage_keys,
                fan_out_strategy=sd.fan_out_strategy,
                fan_out_source_field=sd.fan_out_source_field,
                ai_review_enabled=sd.ai_review_enabled,
                human_review_enabled=sd.human_review_enabled,
                model_override=sd.model_override,
                temperature_override=sd.temperature_override,
                prompt_template_key=sd.prompt_template_key,
            )
            db.add(new_sd)
            db.flush()

            if sd.prompt_config:
                pc = sd.prompt_config
                new_pc = PromptConfig(
                    stage_definition_id=new_sd.id,
                    system_message=pc.system_message,
                    output_format_instructions=pc.output_format_instructions,
                    context_template=pc.context_template,
                    revision_instructions=pc.revision_instructions,
                    model=pc.model,
                    temperature=pc.temperature,
                    max_tokens=pc.max_tokens,
                )
                db.add(new_pc)

    # Clone artifacts (map old IDs to new IDs for dependency remapping)
    artifact_id_map: dict[str, str] = {}
    src_artifacts = db.query(Artifact).filter_by(project_id=source_project_id).all()

    # Snapshot data we'll build as we go
    artifact_statuses: dict[str, str] = {}
    artifact_versions: dict[str, int] = {}
    artifact_git_shas: dict[str, str] = {}
    stage_statuses: dict[str, str] = {}

    from backend.pipeline.readiness import _ARTIFACT_TYPE_TO_STAGE_KEY

    for art in src_artifacts:
        new_id = str(uuid.uuid4())
        artifact_id_map[art.id] = new_id
        new_art = Artifact(
            id=new_id,
            project_id=new_project.id,
            artifact_type=art.artifact_type,
            name=art.name,
            component_key=art.component_key,
            content=art.content,
            summary=art.summary,
            status=art.status,
            git_commit_sha=art.git_commit_sha,
            prev_git_commit_sha=art.prev_git_commit_sha,
            version=art.version,
            ai_review_feedback=art.ai_review_feedback,
            human_review_notes=art.human_review_notes,
            file_path=art.file_path,
            is_stale=art.is_stale,
            language=art.language,
        )
        db.add(new_art)

        # Build snapshot entries
        artifact_statuses[new_id] = art.status.value
        artifact_versions[new_id] = art.version
        if art.git_commit_sha:
            artifact_git_shas[new_id] = art.git_commit_sha

        # Build stage_statuses entry
        stage_key = _ARTIFACT_TYPE_TO_STAGE_KEY.get(art.artifact_type)
        if stage_key:
            sk = f"{stage_key}/{art.component_key}" if art.component_key else stage_key
            stage_statuses[sk] = art.status.value

    db.flush()

    # Clone artifact dependencies
    src_deps = (
        db.query(ArtifactDependency)
        .filter(ArtifactDependency.upstream_artifact_id.in_(artifact_id_map.keys()))
        .all()
    )
    for dep in src_deps:
        new_up = artifact_id_map.get(dep.upstream_artifact_id)
        new_down = artifact_id_map.get(dep.downstream_artifact_id)
        if new_up and new_down:
            db.add(
                ArtifactDependency(
                    upstream_artifact_id=new_up,
                    downstream_artifact_id=new_down,
                    stage_key=dep.stage_key,
                )
            )

    # Clone component definitions
    src_comps = db.query(ComponentDefinition).filter_by(project_id=source_project_id).all()
    for comp in src_comps:
        db.add(
            ComponentDefinition(
                project_id=new_project.id,
                key=comp.key,
                name=comp.name,
                description=comp.description,
                parent_key=comp.parent_key,
                dependencies=comp.dependencies,
                dag_type=comp.dag_type,
                domain_parents=comp.domain_parents,
            )
        )

    # Clone input documents
    src_docs = db.query(InputDocument).filter_by(project_id=source_project_id).all()
    for doc in src_docs:
        db.add(
            InputDocument(
                project_id=new_project.id,
                name=doc.name,
                content=doc.content,
                doc_type=doc.doc_type,
                inject_into_stages=doc.inject_into_stages,
                version=doc.version,
            )
        )

    # Clone comments (remap artifact IDs)
    src_comments = db.query(ArtifactComment).filter_by(project_id=source_project_id).all()
    comment_id_map: dict[str, str] = {}
    for comment in src_comments:
        new_comment_id = str(uuid.uuid4())
        comment_id_map[comment.id] = new_comment_id
        db.add(
            ArtifactComment(
                id=new_comment_id,
                artifact_id=artifact_id_map.get(comment.artifact_id, comment.artifact_id),
                project_id=new_project.id,
                author_id=comment.author_id,
                content=comment.content,
                comment_type=comment.comment_type,
                parent_id=comment_id_map.get(comment.parent_id) if comment.parent_id else None,
                artifact_version=comment.artifact_version,
            )
        )

    # Build snapshot directly (no events needed)
    snapshot = PipelineSnapshot(
        project_id=new_project.id,
        last_sequence=0,
        run_status={},
        stage_statuses=stage_statuses,
        artifact_statuses=artifact_statuses,
        is_running=False,
        is_paused=False,
        artifact_versions=artifact_versions,
        artifact_git_shas=artifact_git_shas,
        stage_errors={},
        comment_counts={},
        stage_triggers={},
        artifact_meta={},
        cascade_parents={},
        execution_map={},
        artifact_stale={},
    )
    db.add(snapshot)

    db.commit()
    db.refresh(new_project)
    logger.info("Cloned project %s → %s (%s)", source_project_id, new_project.id, clone_name)
    return new_project
