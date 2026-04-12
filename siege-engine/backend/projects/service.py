import logging
import shutil
from pathlib import Path

from sqlalchemy.orm import Session

from backend.config import settings
from backend.git_manager.service import git_manager
from backend.models import InputDocument, Project

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

    # Store the initial project doc as an InputDocument for the v2 build phase
    # to pick up. v1's artifact-based project_doc has been removed.
    git_manager.commit_artifact(
        project.id,
        project_doc_content,
        "project_doc.md",
        "Initial project document",
    )
    db.add(
        InputDocument(
            project_id=project.id,
            name="Project Document",
            content=project_doc_content,
            doc_type="project_doc",
        )
    )

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
    """Clone a project: copy the git repo and input documents."""
    source = db.get(Project, source_project_id)
    if not source:
        raise ValueError("Source project not found")

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

    db.commit()
    db.refresh(new_project)
    logger.info("Cloned project %s → %s (%s)", source_project_id, new_project.id, clone_name)
    return new_project
