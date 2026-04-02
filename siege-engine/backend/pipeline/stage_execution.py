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
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

from backend.models import (
    Artifact,
    ArtifactComment,
    ArtifactStatus,
    PipelineConfig,
    PipelineRun,
    StageDefinition,
    StageExecution,
    StageStatus,
)
from backend.pipeline import events as evt

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

    # Error recovery: what status to restore the artifact to on failure.
    # If None, defaults to ArtifactStatus.PENDING (first-generation).
    # Rejection regeneration sets REJECTED, revision sets APPROVED.
    error_artifact_status: ArtifactStatus | None = None

    # The original artifact ID to restore on failure.  When generate()
    # creates a new artifact, execution.artifact_id changes — but on
    # error we need to restore the ORIGINAL artifact's status.
    original_artifact_id: str | None = None

    # If set, _run_stage adds a system_event comment on the artifact
    # after successful generation, e.g. "Artifact regenerated".
    version_comment: str | None = None


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
                f"stage {execution.stage_key}: execution {already_running.id} is already running"
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
            project_id,
            execution.run_id,
        )

        # Reset artifact to PENDING so regeneration starts clean.
        if execution.artifact_id:
            artifact = engine.db.get(Artifact, execution.artifact_id)
            if artifact and artifact.status != ArtifactStatus.PENDING:
                engine._mark_artifact_status(
                    execution.artifact_id,
                    ArtifactStatus.PENDING,
                )

        # Gather feedback and current content for iterative improvement.
        human_notes = (
            engine._get_feedback_notes(execution.artifact_id) if execution.artifact_id else None
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
            project_id,
            stage_def,
            execution.component_key,
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
            .filter(StageExecution.status.in_([StageStatus.RUNNING, StageStatus.AI_REVIEW]))
            .first()
        )
        if existing:
            raise SkipExecution(
                f"stage {stage_key} (component={self.component_key}) is already "
                f"running (execution {existing.id})"
            )

        input_artifacts = engine._gather_inputs(
            self.project_id,
            self.stage_def,
            self.component_key,
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
            stage_key,
            self.component_key,
            execution.id,
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


class RejectionRegenerateStrategy(StageExecutionStrategy):
    """Prepare a stage execution triggered by human rejection.

    When an artifact is rejected, the pipeline regenerates it with the
    accumulated feedback.  On failure, the artifact is restored to its
    pre-generation status (typically REJECTED).
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
            )
            .first()
        )
        if already_running:
            raise SkipExecution(
                f"stage {execution.stage_key}: execution {already_running.id} is already running"
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

        # Capture original artifact status for error recovery.
        original_artifact_status = None
        if execution.artifact_id:
            artifact = engine.db.get(Artifact, execution.artifact_id)
            if artifact:
                original_artifact_status = artifact.status

        # Ensure we have an active run.
        run_id, pipeline_run = engine._ensure_active_run(
            project_id,
            execution.run_id,
        )

        # Create new execution.
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

        # Mark artifact as GENERATING so the UI shows progress.
        if execution.artifact_id:
            engine._mark_artifact_status(
                execution.artifact_id,
                ArtifactStatus.GENERATING,
            )

        input_artifacts = engine._gather_inputs(
            project_id,
            stage_def,
            execution.component_key,
        )

        # Gather feedback and current content.
        human_notes = (
            engine._get_feedback_notes(execution.artifact_id) if execution.artifact_id else None
        )
        current_content = None
        if execution.artifact_id:
            existing_artifact = engine.db.get(Artifact, execution.artifact_id)
            if existing_artifact and existing_artifact.content:
                current_content = existing_artifact.content

        return StageExecutionContext(
            project_id=project_id,
            stage_def=stage_def,
            config=config,
            execution=new_execution,
            run_id=run_id,
            pipeline_run=pipeline_run,
            input_artifacts=input_artifacts,
            trigger="rejection_regenerate",
            human_notes=human_notes,
            current_content=current_content,
            error_artifact_status=original_artifact_status or ArtifactStatus.REJECTED,
            original_artifact_id=execution.artifact_id,
            version_comment="Artifact regenerated",
        )


class ArtifactRevisionStrategy(StageExecutionStrategy):
    """Prepare a stage execution triggered by artifact revision.

    The user provides feedback on an approved/stale artifact and requests
    AI revision.  Creates a standalone execution (no PipelineRun) so it
    doesn't interfere with pipeline flow.  On failure, the artifact is
    restored to its pre-revision status (typically APPROVED).
    """

    def __init__(
        self,
        artifact_id: str,
        feedback: str,
        user_id: str | None = None,
        fresh: bool = False,
    ):
        self.artifact_id = artifact_id
        self.feedback = feedback
        self.user_id = user_id
        self.fresh = fresh

    async def prepare(self, engine: PipelineEngine) -> StageExecutionContext:
        artifact = engine.db.get(Artifact, self.artifact_id)
        if not artifact:
            raise ValueError("Artifact not found")

        # Guard: skip if there's already a RUNNING execution for this artifact.
        already_running = (
            engine.db.query(StageExecution)
            .filter(
                StageExecution.artifact_id == self.artifact_id,
                StageExecution.status.in_([StageStatus.RUNNING, StageStatus.AI_REVIEW]),
            )
            .first()
        )
        if already_running:
            raise SkipExecution(
                f"artifact {self.artifact_id}: execution {already_running.id} is already running"
            )

        original_artifact_status = artifact.status
        project_id = artifact.project_id

        config = engine._get_config(project_id)
        if not config:
            raise ValueError("Pipeline config not found")

        stage_def = next(
            (s for s in config.stages if s.output_artifact_type == artifact.artifact_type.value),
            None,
        )
        if not stage_def:
            raise ValueError(
                f"No stage definition for artifact type: {artifact.artifact_type.value}"
            )

        # Save feedback as a comment.
        if self.feedback and self.feedback.strip():
            engine.db.add(
                ArtifactComment(
                    artifact_id=self.artifact_id,
                    project_id=project_id,
                    author_id=self.user_id,
                    content=self.feedback.strip(),
                    comment_type="feedback",
                    artifact_version=artifact.version,
                )
            )
            engine.db.flush()

        accumulated = engine._get_feedback_notes(self.artifact_id)

        # Mark artifact as GENERATING.
        engine._mark_artifact_status(self.artifact_id, ArtifactStatus.GENERATING)
        engine.db.flush()

        # Emit ARTIFACT_REVISED event.
        engine.events.emit(
            project_id,
            evt.ARTIFACT_REVISED,
            {
                "artifact_id": self.artifact_id,
                "stage_key": stage_def.stage_key,
                "component_key": artifact.component_key,
                "feedback": self.feedback,
            },
        )

        input_artifacts = engine._gather_inputs(
            project_id,
            stage_def,
            artifact.component_key,
        )

        # Standalone run (no PipelineRun object).
        run_id = str(uuid.uuid4())

        execution = StageExecution(
            project_id=project_id,
            stage_key=stage_def.stage_key,
            component_key=artifact.component_key,
            status=StageStatus.RUNNING,
            started_at=datetime.utcnow(),
            run_id=run_id,
            artifact_id=self.artifact_id,
        )
        engine.db.add(execution)
        engine.db.flush()

        # When fresh=True (rejection with no specific feedback), omit previous
        # content so the LLM generates from scratch using current inputs rather
        # than conservatively preserving the old output.
        current_content = None if self.fresh else (artifact.content if artifact.content else None)

        return StageExecutionContext(
            project_id=project_id,
            stage_def=stage_def,
            config=config,
            execution=execution,
            run_id=run_id,
            pipeline_run=None,  # Standalone, no PipelineRun
            input_artifacts=input_artifacts,
            trigger="revision",
            human_notes=accumulated,
            current_content=current_content,
            error_artifact_status=original_artifact_status or ArtifactStatus.APPROVED,
            original_artifact_id=self.artifact_id,
            version_comment="Artifact revised",
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
