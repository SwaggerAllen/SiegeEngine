"""Pipeline models: PipelineConfig, PipelineRun, StageDefinition, StageExecution, PromptConfig."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, Float, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.database import Base
from backend.models.enums import (
    ExecutionMode,
    FanOutStrategy,
    PipelineRunStatus,
    StageStatus,
    StopPoint,
)


class PipelineConfig(Base):
    __tablename__ = "pipeline_configs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), unique=True, nullable=False)
    execution_mode: Mapped[ExecutionMode] = mapped_column(
        Enum(ExecutionMode), default=ExecutionMode.GATED
    )
    default_model: Mapped[str] = mapped_column(String(100), default="claude-sonnet-4-20250514")
    default_temperature: Mapped[float] = mapped_column(Float, default=0.3)
    review_prompt_overrides: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    project: Mapped["Project"] = relationship(back_populates="pipeline_config")
    stages: Mapped[list["StageDefinition"]] = relationship(
        back_populates="pipeline_config",
        cascade="all, delete-orphan",
        order_by="StageDefinition.order_index",
    )


class PipelineRun(Base):
    __tablename__ = "pipeline_runs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), nullable=False)
    run_number: Mapped[int] = mapped_column(Integer, nullable=False)
    run_id: Mapped[str] = mapped_column(
        String, unique=True, nullable=False, default=lambda: str(uuid.uuid4())
    )
    status: Mapped[PipelineRunStatus] = mapped_column(
        Enum(PipelineRunStatus), default=PipelineRunStatus.RUNNING
    )
    ai_loops: Mapped[int] = mapped_column(Integer, default=1)
    stop_point: Mapped[StopPoint] = mapped_column(Enum(StopPoint), default=StopPoint.END_OF_PHASE)
    propagation_run: Mapped[bool] = mapped_column(Boolean, default=False)
    start_stage_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    start_component_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    regen_generated_only: Mapped[bool] = mapped_column(Boolean, default=False)
    git_commit_sha: Mapped[str | None] = mapped_column(String(40), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    project: Mapped["Project"] = relationship(back_populates="pipeline_runs")


class StageDefinition(Base):
    __tablename__ = "stage_definitions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
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
    fan_out_source_field: Mapped[str | None] = mapped_column(String(100), nullable=True)
    ai_review_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    human_review_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    model_override: Mapped[str | None] = mapped_column(String(100), nullable=True)
    temperature_override: Mapped[float | None] = mapped_column(Float, nullable=True)
    prompt_template_key: Mapped[str] = mapped_column(String(100), nullable=False)

    pipeline_config: Mapped["PipelineConfig"] = relationship(back_populates="stages")
    prompt_config: Mapped["PromptConfig | None"] = relationship(
        back_populates="stage_definition",
        uselist=False,
        cascade="all, delete-orphan",
    )


class PromptConfig(Base):
    __tablename__ = "prompt_configs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
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

    stage_definition: Mapped["StageDefinition"] = relationship(back_populates="prompt_config")


class StageExecution(Base):
    __tablename__ = "stage_executions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), nullable=False)
    stage_key: Mapped[str] = mapped_column(String(100), nullable=False)
    component_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[StageStatus] = mapped_column(Enum(StageStatus), default=StageStatus.PENDING)
    artifact_id: Mapped[str | None] = mapped_column(ForeignKey("artifacts.id"), nullable=True)
    langgraph_thread_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    run_id: Mapped[str] = mapped_column(String, nullable=False)

    project: Mapped["Project"] = relationship(back_populates="stage_executions")
