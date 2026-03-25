from pydantic import BaseModel


class ProjectCreate(BaseModel):
    name: str
    description: str | None = None
    project_doc_content: str


class ProjectUpdate(BaseModel):
    name: str | None = None
    description: str | None = None


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
    artifact_count: int = 0
    pipeline_status: str | None = None

    model_config = {"from_attributes": True}


class ProjectDetailResponse(ProjectResponse):
    artifacts: list[dict] = []


class ArtifactResponse(BaseModel):
    id: str
    project_id: str
    artifact_type: str
    name: str
    component_key: str | None
    content: str | None
    status: str
    version: int
    ai_review_feedback: dict | None
    human_review_notes: str | None
    file_path: str | None
    language: str | None
    created_at: str
    updated_at: str

    model_config = {"from_attributes": True}


class ArtifactUpdate(BaseModel):
    content: str
    clear_ai_review: bool = False
