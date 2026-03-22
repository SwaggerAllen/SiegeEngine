"""Stage execution strategies and lifecycle management.

The strategy pattern separates HOW a stage execution is prepared (each
trigger type) from HOW it runs (shared lifecycle in _run_stage).  This
guarantees that run completion, event emission, and error handling are
always handled correctly regardless of what triggered the execution.

Adding a new trigger type:
  1. Subclass StageExecutionStrategy
  2. Implement prepare() to build a StageExecutionContext
  3. Call engine.execute_strategy(strategy) from your route/handler
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

from backend.models import (
    Artifact,
    ArtifactStatus,
    PipelineConfig,
    PipelineRun,
    StageDefinition,
    StageExecution,
    StageStatus,
)

if TYPE_CHECKING:
    from backend.pipeline.engine import PipelineEngine

logger = logging.getLogger(__name__)


@dataclass
class StageExecutionContext:
    """All data needed to execute a single stage.

    Built by trigger-specific code (strategies or orchestrators),
    consumed by _run_stage.  Replaces the 11-parameter signature.
    """

    project_id: str
    stage_def: StageDefinition
    config: PipelineConfig
    execution: StageExecution
    run_id: str
    pipeline_run: PipelineRun | None = None
    input_artifacts: dict[str, str] = field(default_factory=dict)
    trigger: str = "pipeline_run"
    human_notes: str | None = None
    current_content: str | None = None


# ---------------------------------------------------------------------------
# Strategy ABC
# ---------------------------------------------------------------------------


class StageExecutionStrategy(ABC):
    """Defines how to prepare a stage for execution.

    Each trigger type (force restart, manual trigger, etc.) implements
    this interface.  The shared lifecycle (event emission, error handling,
    run completion) is managed by PipelineEngine._run_stage.
    """

    @abstractmethod
    async def prepare(self, engine: PipelineEngine) -> StageExecutionContext:
        """Build a fully-populated execution context.

        Implementations should:
        - Guard against duplicate running executions
        - Ensure an active PipelineRun exists
        - Create a StageExecution record (flush, don't commit)
        - Gather input artifacts and feedback notes
        """
        ...


# ---------------------------------------------------------------------------
# Concrete strategies
# ---------------------------------------------------------------------------


class ForceRestartStrategy(StageExecutionStrategy):
    """Prepare a stage execution triggered by force-restart.

    Creates a NEW execution (never reuses the old one) so each attempt
    gets its own record and retry counts don't accumulate unboundedly.
    """

    def __init__(self, old_execution: StageExecution):
        self.old_execution = old_execution

    async def prepare(self, engine: PipelineEngine) -> StageExecutionContext:
        execution = self.old_execution
        project_id = execution.project_id

        # Guard: skip if there's already a RUNNING execution for this stage.
        already_running = (
            engine.db.query(StageExecution)
            .filter(
                StageExecution.project_id == project_id,
                StageExecution.stage_key == execution.stage_key,
                StageExecution.component_key == execution.component_key,
                StageExecution.status.in_([StageStatus.RUNNING, StageStatus.AI_REVIEW]),
                StageExecution.id != execution.id,
            )
            .first()
        )
        if already_running:
            raise SkipExecution(
                f"stage {execution.stage_key}: execution {already_running.id} "
                f"is already running"
            )

        config = engine._get_config(project_id)
        if not config:
            raise ValueError("Pipeline config not found")

        stage_def = next(
            (s for s in config.stages if s.stage_key == execution.stage_key),
            None,
        )
        if not stage_def:
            raise ValueError(f"Stage definition not found: {execution.stage_key}")

        # Ensure we have an active run.
        run_id, pipeline_run = engine._ensure_active_run(
            project_id, execution.run_id,
        )

        # Reset artifact to PENDING so regeneration starts clean.
        if execution.artifact_id:
            artifact = engine.db.get(Artifact, execution.artifact_id)
            if artifact and artifact.status != ArtifactStatus.PENDING:
                engine._mark_artifact_status(
                    execution.artifact_id, ArtifactStatus.PENDING,
                )

        # Gather feedback and current content for iterative improvement.
        human_notes = (
            engine._get_feedback_notes(execution.artifact_id)
            if execution.artifact_id
            else None
        )
        current_content = None
        if execution.artifact_id:
            existing_artifact = engine.db.get(Artifact, execution.artifact_id)
            if existing_artifact and existing_artifact.content:
                current_content = existing_artifact.content

        # Create a NEW execution rather than reusing the old one.
        new_execution = StageExecution(
            project_id=project_id,
            stage_key=execution.stage_key,
            component_key=execution.component_key,
            status=StageStatus.RUNNING,
            started_at=datetime.utcnow(),
            run_id=run_id,
            retry_count=(execution.retry_count or 0) + 1,
            artifact_id=execution.artifact_id,
        )
        engine.db.add(new_execution)
        engine.db.flush()

        input_artifacts = engine._gather_inputs(
            project_id, stage_def, execution.component_key,
        )

        return StageExecutionContext(
            project_id=project_id,
            stage_def=stage_def,
            config=config,
            execution=new_execution,
            run_id=run_id,
            pipeline_run=pipeline_run,
            input_artifacts=input_artifacts,
            trigger="force_restart",
            human_notes=human_notes,
            current_content=current_content,
        )


class ManualTriggerStrategy(StageExecutionStrategy):
    """Prepare a stage execution triggered by manual kickoff.

    Used for both single-entity and fan-out stages (one entity at a time).
    For fan-out stages, create one strategy per entity.
    """

    def __init__(
        self,
        project_id: str,
        stage_def: StageDefinition,
        run_id: str,
        config: PipelineConfig,
        pipeline_run: PipelineRun | None,
        component_key: str | None = None,
    ):
        self.project_id = project_id
        self.stage_def = stage_def
        self.run_id = run_id
        self.config = config
        self.pipeline_run = pipeline_run
        self.component_key = component_key

    async def prepare(self, engine: PipelineEngine) -> StageExecutionContext:
        stage_key = self.stage_def.stage_key

        # Guard: check for already-running execution.
        existing = (
            engine.db.query(StageExecution)
            .filter_by(
                project_id=self.project_id,
                stage_key=stage_key,
                component_key=self.component_key,
                run_id=self.run_id,
            )
            .filter(
                StageExecution.status.in_(
                    [StageStatus.RUNNING, StageStatus.AI_REVIEW]
                )
            )
            .first()
        )
        if existing:
            raise SkipExecution(
                f"stage {stage_key} (component={self.component_key}) is already "
                f"running (execution {existing.id})"
            )

        input_artifacts = engine._gather_inputs(
            self.project_id, self.stage_def, self.component_key,
        )

        # Gather feedback and current content from previous execution.
        human_notes = None
        current_content = None
        prev_exec = (
            engine.db.query(StageExecution)
            .filter_by(
                project_id=self.project_id,
                stage_key=stage_key,
                component_key=self.component_key,
            )
            .order_by(StageExecution.started_at.desc())
            .first()
        )
        if prev_exec and prev_exec.artifact_id:
            human_notes = engine._get_feedback_notes(prev_exec.artifact_id)
            prev_artifact = engine.db.get(Artifact, prev_exec.artifact_id)
            if prev_artifact and prev_artifact.content:
                current_content = prev_artifact.content

        execution = StageExecution(
            project_id=self.project_id,
            stage_key=stage_key,
            component_key=self.component_key,
            status=StageStatus.RUNNING,
            started_at=datetime.utcnow(),
            run_id=self.run_id,
        )
        engine.db.add(execution)
        engine.db.flush()

        logger.info(
            "Manually triggered stage %s (component=%s) execution=%s",
            stage_key, self.component_key, execution.id,
        )

        return StageExecutionContext(
            project_id=self.project_id,
            stage_def=self.stage_def,
            config=self.config,
            execution=execution,
            run_id=self.run_id,
            pipeline_run=self.pipeline_run,
            input_artifacts=input_artifacts,
            trigger="manual_trigger",
            human_notes=human_notes,
            current_content=current_content,
        )


# ---------------------------------------------------------------------------
# Sentinel exception for skippable executions
# ---------------------------------------------------------------------------


class SkipExecution(Exception):
    """Raised by a strategy when the execution should be skipped.

    This is NOT an error — it means there's already a running execution
    for this stage/component, or some other guard prevented the strategy
    from creating a new one.
    """

    pass
