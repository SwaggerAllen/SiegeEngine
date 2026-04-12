import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.auth.routes import _require_writer, get_current_user
from backend.database import get_db
from backend.git_manager.service import git_manager
from backend.github.service import GitHubService
from backend.models import GitHubCredential, Project, User
from backend.projects import service
from backend.projects.schemas import (
    ProjectClone,
    ProjectCreate,
    ProjectDetailResponse,
    ProjectResponse,
    ProjectUpdate,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def _project_to_dict(project: Project) -> dict:
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
    }


@router.get("/", response_model=list[ProjectResponse])
def list_projects(
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    projects = service.list_projects(db)
    return [_project_to_dict(p) for p in projects]


@router.post("/", response_model=ProjectResponse, status_code=201)
def create_project(
    req: ProjectCreate,
    db: Session = Depends(get_db),
    _user: User = Depends(_require_writer),
):
    project = service.create_project(db, req.name, req.description, req.project_doc_content)
    return _project_to_dict(project)


@router.get("/{project_id}", response_model=ProjectDetailResponse)
def get_project(
    project_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    project = service.get_project(db, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    return _project_to_dict(project)


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
    return _project_to_dict(project)


@router.post("/{project_id}/clone", response_model=ProjectResponse, status_code=201)
def clone_project(
    project_id: str,
    req: ProjectClone,
    db: Session = Depends(get_db),
    _user: User = Depends(_require_writer),
):
    try:
        project = service.clone_project(db, project_id, req.new_name)
    except ValueError as e:
        raise HTTPException(404, str(e))
    return _project_to_dict(project)


@router.delete("/{project_id}", status_code=204)
def delete_project(
    project_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(_require_writer),
):
    if not service.delete_project(db, project_id):
        raise HTTPException(404, "Project not found")


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

    if not project.remote_url:
        raise HTTPException(400, "Project has no remote URL configured")

    # Push first (token passed as one-time auth URL, never persisted)
    branch = req.branch_name or f"siege-engine/{project.name.lower().replace(' ', '-')}"
    auth_url = None
    if project.remote_url.startswith("https://"):
        auth_url = project.remote_url.replace(
            "https://", f"https://x-access-token:{cred.access_token}@"
        )
    else:
        raise HTTPException(400, "Only HTTPS remote URLs are supported for PR creation")

    try:
        git_manager.push_branch(project_id, branch, auth_url=auth_url)
    except Exception as e:
        raise HTTPException(502, f"Failed to push branch '{branch}': {e}")

    # Create PR
    gh = GitHubService(cred.access_token)
    try:
        pr = await gh.create_pr(
            project.github_repo_slug,
            req.title,
            req.body,
            branch,
            req.base_branch,
        )
    except Exception as e:
        error_detail = str(e)
        # httpx errors include the response body
        if hasattr(e, "response") and e.response is not None:
            try:
                error_detail = e.response.json().get("message", error_detail)
            except Exception:
                pass
        raise HTTPException(502, f"GitHub API error: {error_detail}")

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
