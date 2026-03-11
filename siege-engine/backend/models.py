"""All SQLAlchemy models in one module to avoid circular imports."""

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.database import Base


# ──── Auth ────


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    username: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(20), default="member")
    invited_by: Mapped[str | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class InviteLink(Base):
    __tablename__ = "invite_links"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    token: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    created_by: Mapped[str] = mapped_column(
        ForeignKey("users.id"), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    used: Mapped[bool] = mapped_column(Boolean, default=False)
    used_by: Mapped[str | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


# ──── Project ────


class ArtifactStatus(str, enum.Enum):
    PENDING = "pending"
    GENERATING = "generating"
    AI_REVIEWING = "ai_reviewing"
    AWAITING_REVIEW = "awaiting_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    STALE = "stale"


class ArtifactType(str, enum.Enum):
    PROJECT_DOC = "project_doc"
    SYSTEM_REQUIREMENTS = "system_requirements"
    SYSTEM_ARCHITECTURE = "system_architecture"
    HIGH_LEVEL_PLAN = "high_level_plan"
    COMPONENT_MAP = "component_map"
    COMPONENT_REQUIREMENTS = "component_requirements"
    COMPONENT_ARCHITECTURE = "component_architecture"
    COMPONENT_PLAN = "component_plan"
    SUB_COMPONENT_MAP = "sub_component_map"
    SUB_COMPONENT_REQUIREMENTS = "sub_component_requirements"
    SUB_COMPONENT_ARCHITECTURE = "sub_component_architecture"
    SUB_COMPONENT_PLAN = "sub_component_plan"
    CODE = "code"
    CODE_REVIEW = "code_review"


class GitHubCredential(Base):
    __tablename__ = "github_credentials"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id"), unique=True, nullable=False
    )
    access_token: Mapped[str] = mapped_column(String(500), nullable=False)
    github_username: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    remote_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    github_repo_slug: Mapped[str | None] = mapped_column(String(200), nullable=True)
    git_repo_path: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    artifacts: Mapped[list["Artifact"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    pipeline_config: Mapped["PipelineConfig"] = relationship(
        back_populates="project", uselist=False, cascade="all, delete-orphan"
    )
    stage_executions: Mapped[list["StageExecution"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    component_definitions: Mapped[list["ComponentDefinition"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )


class Artifact(Base):
    __tablename__ = "artifacts"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id"), nullable=False
    )
    artifact_type: Mapped[ArtifactType] = mapped_column(
        Enum(ArtifactType), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    component_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[ArtifactStatus] = mapped_column(
        Enum(ArtifactStatus), default=ArtifactStatus.PENDING
    )
    git_commit_sha: Mapped[str | None] = mapped_column(String(40), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    ai_review_feedback: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    human_review_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    language: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    project: Mapped["Project"] = relationship(back_populates="artifacts")
    upstream_deps: Mapped[list["ArtifactDependency"]] = relationship(
        foreign_keys="ArtifactDependency.downstream_artifact_id",
        back_populates="downstream_artifact",
        cascade="all, delete-orphan",
    )
    downstream_deps: Mapped[list["ArtifactDependency"]] = relationship(
        foreign_keys="ArtifactDependency.upstream_artifact_id",
        back_populates="upstream_artifact",
        cascade="all, delete-orphan",
    )


class ArtifactDependency(Base):
    __tablename__ = "artifact_dependencies"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    upstream_artifact_id: Mapped[str] = mapped_column(
        ForeignKey("artifacts.id"), nullable=False
    )
    downstream_artifact_id: Mapped[str] = mapped_column(
        ForeignKey("artifacts.id"), nullable=False
    )
    stage_key: Mapped[str] = mapped_column(String(100), nullable=False)

    upstream_artifact: Mapped["Artifact"] = relationship(
        foreign_keys=[upstream_artifact_id], back_populates="downstream_deps"
    )
    downstream_artifact: Mapped["Artifact"] = relationship(
        foreign_keys=[downstream_artifact_id], back_populates="upstream_deps"
    )


class ComponentDefinition(Base):
    __tablename__ = "component_definitions"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id"), nullable=False
    )
    key: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    parent_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    dependencies: Mapped[list | None] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    project: Mapped["Project"] = relationship(back_populates="component_definitions")


# ──── Pipeline ────


class ExecutionMode(str, enum.Enum):
    GATED = "gated"
    ASYNC = "async"


class StageStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    AI_REVIEW = "ai_review"
    AWAITING_REVIEW = "awaiting_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    SKIPPED = "skipped"
    FAILED = "failed"


class FanOutStrategy(str, enum.Enum):
    NONE = "none"
    COMPONENT = "component"
    SUB_COMPONENT = "sub_component"
    LEAF = "leaf"


class PipelineConfig(Base):
    __tablename__ = "pipeline_configs"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id"), unique=True, nullable=False
    )
    execution_mode: Mapped[ExecutionMode] = mapped_column(
        Enum(ExecutionMode), default=ExecutionMode.GATED
    )
    default_model: Mapped[str] = mapped_column(
        String(100), default="claude-sonnet-4-20250514"
    )
    default_temperature: Mapped[float] = mapped_column(Float, default=0.3)
    review_prompt_overrides: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    project: Mapped["Project"] = relationship(back_populates="pipeline_config")
    stages: Mapped[list["StageDefinition"]] = relationship(
        back_populates="pipeline_config",
        cascade="all, delete-orphan",
        order_by="StageDefinition.order_index",
    )


class StageDefinition(Base):
    __tablename__ = "stage_definitions"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    pipeline_config_id: Mapped[str] = mapped_column(
        ForeignKey("pipeline_configs.id"), nullable=False
    )
    stage_key: Mapped[str] = mapped_column(String(100), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False)
    output_artifact_type: Mapped[str] = mapped_column(String(100), nullable=False)
    input_stage_keys: Mapped[list] = mapped_column(JSON, default=list)
    fan_out_strategy: Mapped[FanOutStrategy] = mapped_column(
        Enum(FanOutStrategy), default=FanOutStrategy.NONE
    )
    fan_out_source_field: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )
    ai_review_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    human_review_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    model_override: Mapped[str | None] = mapped_column(String(100), nullable=True)
    temperature_override: Mapped[float | None] = mapped_column(Float, nullable=True)
    prompt_template_key: Mapped[str] = mapped_column(String(100), nullable=False)

    pipeline_config: Mapped["PipelineConfig"] = relationship(
        back_populates="stages"
    )
    prompt_config: Mapped["PromptConfig | None"] = relationship(
        back_populates="stage_definition",
        uselist=False,
        cascade="all, delete-orphan",
    )


class PromptConfig(Base):
    __tablename__ = "prompt_configs"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    stage_definition_id: Mapped[str] = mapped_column(
        ForeignKey("stage_definitions.id"), unique=True, nullable=False
    )
    system_message: Mapped[str] = mapped_column(Text, default="")
    output_format_instructions: Mapped[str] = mapped_column(Text, default="")
    context_template: Mapped[str] = mapped_column(Text, default="")
    revision_instructions: Mapped[str] = mapped_column(Text, default="")
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    temperature: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_tokens: Mapped[int] = mapped_column(Integer, default=8192)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    stage_definition: Mapped["StageDefinition"] = relationship(
        back_populates="prompt_config"
    )


class StageExecution(Base):
    __tablename__ = "stage_executions"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id"), nullable=False
    )
    stage_key: Mapped[str] = mapped_column(String(100), nullable=False)
    component_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[StageStatus] = mapped_column(
        Enum(StageStatus), default=StageStatus.PENDING
    )
    artifact_id: Mapped[str | None] = mapped_column(
        ForeignKey("artifacts.id"), nullable=True
    )
    langgraph_thread_id: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    run_id: Mapped[str] = mapped_column(String, nullable=False)

    project: Mapped["Project"] = relationship(back_populates="stage_executions")
