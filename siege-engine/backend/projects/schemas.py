from pydantic import BaseModel


class ProjectCreate(BaseModel):
    name: str
    description: str | None = None
    project_doc_content: str
    # Optional GitHub wire-up at creation time. The remote_url is the
    # clone URL (https or ssh); github_repo_slug is the `owner/name`
    # form used for the REST API. When remote_url is provided and
    # github_repo_slug is not, the slug is auto-derived from the URL.
    remote_url: str | None = None
    github_repo_slug: str | None = None


class ProjectUpdate(BaseModel):
    name: str | None = None
    description: str | None = None


class ProjectClone(BaseModel):
    new_name: str | None = None


class ProjectResponse(BaseModel):
    id: str
    name: str
    description: str | None
    remote_url: str | None = None
    github_repo_slug: str | None = None
    auto_push_enabled: bool = False
    git_repo_path: str
    created_at: str
    updated_at: str

    model_config = {"from_attributes": True}


class ProjectDetailResponse(ProjectResponse):
    pass
