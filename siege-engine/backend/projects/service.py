from pathlib import Path

from sqlalchemy.orm import Session

from backend.config import settings
from backend.git_manager.service import git_manager
from backend.models import (
    Artifact,
    ArtifactStatus,
    ArtifactType,
    PipelineConfig,
    Project,
    StageDefinition,
)
from backend.pipeline.defaults import DEFAULT_STAGES

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
        project.id, claude_md, "CLAUDE.md", "Add CLAUDE.md for CLI context",
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
