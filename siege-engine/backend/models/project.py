"""Project model."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.database import Base

if TYPE_CHECKING:
    from backend.models.artifact import Artifact, ComponentDefinition
    from backend.models.input_document import InputDocument
    from backend.models.pipeline import PipelineConfig, PipelineRun, StageExecution


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    remote_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    github_repo_slug: Mapped[str | None] = mapped_column(String(200), nullable=True)
    git_repo_path: Mapped[str] = mapped_column(String(500), nullable=False)
    auto_push_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    blocking_pr_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    blocking_pr_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
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
    pipeline_runs: Mapped[list["PipelineRun"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    input_documents: Mapped[list["InputDocument"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
