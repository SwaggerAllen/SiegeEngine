from pydantic import BaseModel


class ProjectCreate(BaseModel):
    name: str
    description: str | None = None
    project_doc_content: str


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
