"""Event-sourced pipeline models: PipelineEvent and PipelineSnapshot."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base


class PipelineEvent(Base):
    __tablename__ = "pipeline_events"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    run_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("project_id", "sequence", name="uq_event_project_sequence"),
        Index("ix_events_project_seq", "project_id", "sequence"),
    )


class PipelineSnapshot(Base):
    __tablename__ = "pipeline_snapshots"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id"), nullable=False, unique=True
    )
    last_sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    run_status: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    stage_statuses: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    artifact_statuses: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    is_running: Mapped[bool] = mapped_column(Boolean, default=False)
    is_paused: Mapped[bool] = mapped_column(Boolean, default=False)
    paused_stage: Mapped[str | None] = mapped_column(String, nullable=True)
    current_run_id: Mapped[str | None] = mapped_column(String, nullable=True)
    # Extended snapshot fields
    artifact_versions: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    stage_errors: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    comment_counts: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    stage_triggers: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    artifact_meta: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    artifact_git_shas: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    cascade_parents: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    execution_map: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
