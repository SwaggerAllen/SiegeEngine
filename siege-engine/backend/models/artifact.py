"""Artifact models: Artifact, ArtifactDependency, ArtifactComment, ComponentDefinition."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, JSON, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.database import Base
from backend.models.enums import ArtifactStatus, ArtifactType


class Artifact(Base):
    __tablename__ = "artifacts"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), nullable=False)
    artifact_type: Mapped[ArtifactType] = mapped_column(Enum(ArtifactType), nullable=False)
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

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    upstream_artifact_id: Mapped[str] = mapped_column(ForeignKey("artifacts.id"), nullable=False)
    downstream_artifact_id: Mapped[str] = mapped_column(ForeignKey("artifacts.id"), nullable=False)
    stage_key: Mapped[str] = mapped_column(String(100), nullable=False)

    upstream_artifact: Mapped["Artifact"] = relationship(
        foreign_keys=[upstream_artifact_id], back_populates="downstream_deps"
    )
    downstream_artifact: Mapped["Artifact"] = relationship(
        foreign_keys=[downstream_artifact_id], back_populates="upstream_deps"
    )


class ArtifactComment(Base):
    __tablename__ = "artifact_comments"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    artifact_id: Mapped[str] = mapped_column(
        String, nullable=False
    )  # NO FK — persists across regenerations
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), nullable=False)
    author_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id"),
        nullable=True,  # null for system events
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    comment_type: Mapped[str] = mapped_column(
        String(20), default="comment"
    )  # 'comment' | 'system_event'
    parent_id: Mapped[str | None] = mapped_column(ForeignKey("artifact_comments.id"), nullable=True)
    artifact_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ComponentDefinition(Base):
    __tablename__ = "component_definitions"
    __table_args__ = (
        Index(
            "uq_comp_def_project_key_parent",
            "project_id", "key", text("COALESCE(parent_key, '')"),
            unique=True,
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), nullable=False)
    key: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    parent_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    dependencies: Mapped[list | None] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    project: Mapped["Project"] = relationship(back_populates="component_definitions")
