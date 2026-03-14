from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.auth.routes import get_current_user, _require_writer
from backend.database import get_db
from backend.git_manager.service import git_manager
from backend.github.service import GitHubService
from backend.models import Artifact, GitHubCredential, Project, User
from backend.projects import service
from backend.projects.schemas import (
    ArtifactResponse,
    ArtifactUpdate,
    ProjectCreate,
    ProjectDetailResponse,
    ProjectResponse,
    ProjectUpdate,
)
from backend.dag.service import propagate_staleness

router = APIRouter()


@router.get("/", response_model=list[ProjectResponse])
def list_projects(
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    projects = service.list_projects(db)
    return [
        {
            "id": p.id,
            "name": p.name,
            "description": p.description,
            "git_repo_path": p.git_repo_path,
            "created_at": p.created_at.isoformat(),
            "updated_at": p.updated_at.isoformat(),
            "artifact_count": len(p.artifacts),
        }
        for p in projects
    ]


@router.post("/", response_model=ProjectResponse, status_code=201)
def create_project(
    req: ProjectCreate,
    db: Session = Depends(get_db),
    _user: User = Depends(_require_writer),
):
    project = service.create_project(db, req.name, req.description, req.project_doc_content)
    return {
        "id": project.id,
        "name": project.name,
        "description": project.description,
        "git_repo_path": project.git_repo_path,
        "created_at": project.created_at.isoformat(),
        "updated_at": project.updated_at.isoformat(),
        "artifact_count": len(project.artifacts),
    }


@router.get("/{project_id}", response_model=ProjectDetailResponse)
def get_project(
    project_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    project = service.get_project(db, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    return {
        "id": project.id,
        "name": project.name,
        "description": project.description,
        "remote_url": project.remote_url,
        "github_repo_slug": project.github_repo_slug,
        "auto_push_enabled": project.auto_push_enabled,
        "git_repo_path": project.git_repo_path,
        "created_at": project.created_at.isoformat(),
        "updated_at": project.updated_at.isoformat(),
        "artifact_count": len(project.artifacts),
        "artifacts": [
            {
                "id": a.id,
                "name": a.name,
                "artifact_type": a.artifact_type.value,
                "status": a.status.value,
                "component_key": a.component_key,
                "version": a.version,
            }
            for a in project.artifacts
        ],
    }


@router.put("/{project_id}", response_model=ProjectResponse)
def update_project(
    project_id: str,
    req: ProjectUpdate,
    db: Session = Depends(get_db),
    _user: User = Depends(_require_writer),
):
    project = service.update_project(db, project_id, req.name, req.description)
    if not project:
        raise HTTPException(404, "Project not found")
    return {
        "id": project.id,
        "name": project.name,
        "description": project.description,
        "git_repo_path": project.git_repo_path,
        "created_at": project.created_at.isoformat(),
        "updated_at": project.updated_at.isoformat(),
        "artifact_count": len(project.artifacts),
    }


@router.delete("/{project_id}", status_code=204)
def delete_project(
    project_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(_require_writer),
):
    if not service.delete_project(db, project_id):
        raise HTTPException(404, "Project not found")


# ── Artifact endpoints ──


@router.get("/artifacts/{artifact_id}", response_model=ArtifactResponse)
def get_artifact(
    artifact_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    artifact = db.get(Artifact, artifact_id)
    if not artifact:
        raise HTTPException(404, "Artifact not found")
    return _artifact_to_dict(artifact)


@router.put("/artifacts/{artifact_id}", response_model=ArtifactResponse)
def update_artifact(
    artifact_id: str,
    req: ArtifactUpdate,
    db: Session = Depends(get_db),
    _user: User = Depends(_require_writer),
):
    artifact = db.get(Artifact, artifact_id)
    if not artifact:
        raise HTTPException(404, "Artifact not found")

    artifact.content = req.content
    artifact.version += 1

    # Commit to git
    if artifact.file_path:
        sha = git_manager.commit_artifact(
            artifact.project_id,
            req.content,
            artifact.file_path,
            f"Manual edit: {artifact.name} v{artifact.version}",
        )
        artifact.git_commit_sha = sha

    # Propagate staleness
    stale_ids = propagate_staleness(db, artifact_id)

    db.commit()
    db.refresh(artifact)
    return _artifact_to_dict(artifact)


@router.get("/artifacts/{artifact_id}/diff")
def get_artifact_diff(
    artifact_id: str,
    version: int | None = None,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    artifact = db.get(Artifact, artifact_id)
    if not artifact:
        raise HTTPException(404, "Artifact not found")
    if not artifact.file_path:
        raise HTTPException(400, "Artifact has no file path")

    history = git_manager.get_file_history(artifact.project_id, artifact.file_path)
    if len(history) < 2:
        return {"diff": "", "message": "No previous version to diff against"}

    old_sha = history[1]["sha"]
    new_sha = history[0]["sha"]
    diff = git_manager.get_diff(artifact.project_id, old_sha, new_sha, artifact.file_path)
    return {"diff": diff, "old_sha": old_sha, "new_sha": new_sha}


@router.get("/artifacts/{artifact_id}/history")
def get_artifact_history(
    artifact_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    artifact = db.get(Artifact, artifact_id)
    if not artifact:
        raise HTTPException(404, "Artifact not found")
    if not artifact.file_path:
        return []

    return git_manager.get_file_history(artifact.project_id, artifact.file_path)


# ── Remote / GitHub PR endpoints ──


class SetRemoteRequest(BaseModel):
    remote_url: str
    github_repo_slug: str | None = None
    auto_push_enabled: bool | None = None


class OpenPRRequest(BaseModel):
    title: str
    body: str
    base_branch: str = "main"
    branch_name: str | None = None


@router.post("/{project_id}/remote")
def set_remote(
    project_id: str,
    req: SetRemoteRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(_require_writer),
):
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    project.remote_url = req.remote_url
    project.github_repo_slug = req.github_repo_slug
    if req.auto_push_enabled is not None:
        project.auto_push_enabled = req.auto_push_enabled
    git_manager.add_remote(project_id, req.remote_url)
    db.commit()
    return {
        "status": "remote_configured",
        "remote_url": req.remote_url,
        "auto_push_enabled": project.auto_push_enabled,
    }


@router.post("/{project_id}/push")
def push_project(
    project_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(_require_writer),
):
    project = db.get(Project, project_id)
    if not project or not project.remote_url:
        raise HTTPException(400, "Project has no remote configured")

    # Build one-time auth URL (never persisted in .git/config)
    cred = db.query(GitHubCredential).filter_by(user_id=user.id).first()
    auth_url = None
    if cred and project.remote_url.startswith("https://"):
        auth_url = project.remote_url.replace(
            "https://", f"https://x-access-token:{cred.access_token}@"
        )

    branch = f"siege-engine/{project.name.lower().replace(' ', '-')}"
    result = git_manager.push_branch(project_id, branch, auth_url=auth_url)
    return {"status": "pushed", "branch": branch, "result": result}


@router.post("/{project_id}/open-pr")
async def open_pr(
    project_id: str,
    req: OpenPRRequest,
    db: Session = Depends(get_db),
    user: User = Depends(_require_writer),
):
    project = db.get(Project, project_id)
    if not project or not project.github_repo_slug:
        raise HTTPException(400, "Project has no GitHub repo configured")

    cred = db.query(GitHubCredential).filter_by(user_id=user.id).first()
    if not cred:
        raise HTTPException(400, "GitHub not connected. Connect via Settings.")

    # Push first (token passed as one-time auth URL, never persisted)
    branch = req.branch_name or f"siege-engine/{project.name.lower().replace(' ', '-')}"
    auth_url = None
    if project.remote_url and project.remote_url.startswith("https://"):
        auth_url = project.remote_url.replace(
            "https://", f"https://x-access-token:{cred.access_token}@"
        )
    git_manager.push_branch(project_id, branch, auth_url=auth_url)

    # Create PR
    gh = GitHubService(cred.access_token)
    pr = await gh.create_pr(
        project.github_repo_slug,
        req.title,
        req.body,
        branch,
        req.base_branch,
    )
    return {
        "status": "pr_created",
        "pr_number": pr.get("number"),
        "pr_url": pr.get("html_url"),
    }


@router.get("/{project_id}/pr-status")
async def get_pr_status(
    project_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    project = db.get(Project, project_id)
    if not project or not project.github_repo_slug:
        return {"prs": []}

    cred = db.query(GitHubCredential).filter_by(user_id=user.id).first()
    if not cred:
        return {"prs": []}

    gh = GitHubService(cred.access_token)
    prs = await gh.list_prs(project.github_repo_slug)
    return {
        "prs": [
            {
                "number": pr["number"],
                "title": pr["title"],
                "state": pr["state"],
                "url": pr["html_url"],
            }
            for pr in prs
        ]
    }


def _artifact_to_dict(artifact: Artifact) -> dict:
    return {
        "id": artifact.id,
        "project_id": artifact.project_id,
        "artifact_type": artifact.artifact_type.value,
        "name": artifact.name,
        "component_key": artifact.component_key,
        "content": artifact.content,
        "status": artifact.status.value,
        "version": artifact.version,
        "ai_review_feedback": artifact.ai_review_feedback,
        "human_review_notes": artifact.human_review_notes,
        "file_path": artifact.file_path,
        "language": artifact.language,
        "created_at": artifact.created_at.isoformat(),
        "updated_at": artifact.updated_at.isoformat(),
    }
