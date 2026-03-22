"""
Pipeline engine that orchestrates stage execution.

Uses a "find next ready work" approach instead of linear stage iteration.
For fan-out stages, components are processed in dependency order — a component's
documents are only generated after all its upstream dependency components have
completed their full document cycle and received human approval.
"""

import asyncio
import logging
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from backend.models import (
    Artifact,
    ArtifactComment,
    ArtifactStatus,
    ArtifactType,
    ComponentDefinition,
    FanOutStrategy,
    PipelineConfig,
    PipelineRun,
    PipelineRunStatus,
    Project,
    StageDefinition,
    StageExecution,
    StageStatus,
    StopPoint,
)
from backend.pipeline.artifact_ops import ArtifactOpsMixin
from backend.pipeline.component_manager import ComponentManagerMixin
from backend.pipeline.event_store import EventStore
from backend.pipeline import events as evt
from backend.pipeline.nodes.ai_review import ai_review
from backend.pipeline.nodes.generate import generate
from backend.pipeline.readiness import (
    ReadinessMixin,
)
from backend.websocket.manager import ws_manager

logger = logging.getLogger(__name__)

# Extraction stages that define downstream branching structure —
# always pause for human review regardless of execution mode.
BRANCHING_STAGES = {"extract_components", "extract_sub_components"}

# Map stage keys to the artifact type they produce (for readiness checks)
_STAGE_TO_PLAN_TYPE = {
    "component_plans": ArtifactType.COMPONENT_PLAN,
    "sub_component_plans": ArtifactType.SUB_COMPONENT_PLAN,
}


class PipelineEngine(ArtifactOpsMixin, ComponentManagerMixin, ReadinessMixin):
    def __init__(self, db: Session):
        self.db = db
        self.events = EventStore(db)

    def _get_config(self, project_id: str) -> PipelineConfig | None:
        """Return the PipelineConfig for a project, or None if missing."""
        return self.db.query(PipelineConfig).filter_by(project_id=project_id).first()

    def _transition_execution(
        self,
        execution: StageExecution,
        new_status: StageStatus,
        *,
        artifact_status: ArtifactStatus | None = None,
        error_message: str | None = None,
        set_completed: bool = False,
        trigger: str | None = None,
    ) -> None:
        """Atomically transition execution status and optionally its artifact.

        Centralises all status mutations so execution and artifact stay in sync.
        Does NOT broadcast websocket events — callers handle that themselves.
        """
        old_status = execution.status
        execution.status = new_status
        if set_completed:
            execution.completed_at = datetime.utcnow()
        if error_message is not None:
            execution.error_message = error_message

        if artifact_status is not None and execution.artifact_id:
            artifact = self.db.get(Artifact, execution.artifact_id)
            if artifact:
                artifact.status = artifact_status

        logger.debug(
            "Transition exec %s: %s -> %s (artifact: %s)",
            execution.id, old_status.value, new_status.value,
            artifact_status.value if artifact_status else "unchanged",
        )

        # Emit corresponding event
        event_type = _status_to_event_type(new_status)
        if event_type:
            payload: dict[str, Any] = {
                "execution_id": execution.id,
                "stage_key": execution.stage_key,
                "component_key": execution.component_key,
                "artifact_id": execution.artifact_id,
                "error": error_message,
                "retry_count": execution.retry_count,
            }
            if trigger:
                payload["trigger"] = trigger
            # Include artifact metadata when available
            if execution.artifact_id:
                artifact = self.db.get(Artifact, execution.artifact_id)
                if artifact:
                    payload["artifact_type"] = artifact.artifact_type.value
                    payload["artifact_name"] = artifact.name
                    payload["version"] = artifact.version
            self.events.emit(
                execution.project_id,
                event_type,
                payload,
                run_id=execution.run_id,
            )

    def _mark_artifact_status(self, artifact_id: str, new_status: ArtifactStatus) -> None:
        """Update an artifact's status without touching any execution."""
        artifact = self.db.get(Artifact, artifact_id)
        if artifact:
            artifact.status = new_status

    async def start_pipeline(
        self,
        project_id: str,
        pipeline_run_id: str | None = None,
    ) -> str:
        """Start a pipeline run. Returns run_id.

        Carries over APPROVED (non-stale) executions so that already-approved
        work is preserved.  Only non-approved stages are re-processed.
        """
        logger.info(
            "start_pipeline called for project_id=%s, pipeline_run_id=%s",
            project_id,
            pipeline_run_id,
        )

        project = self.db.get(Project, project_id)
        if not project or not project.pipeline_config:
            logger.error("Project or pipeline config not found for project_id=%s", project_id)
            raise ValueError("Project or pipeline config not found")

        config = project.pipeline_config

        # Load PipelineRun if provided (new flow), otherwise legacy fallback
        pipeline_run = self.db.get(PipelineRun, pipeline_run_id) if pipeline_run_id else None
        run_id = pipeline_run.run_id if pipeline_run else str(uuid.uuid4())

        # Emit run_created event
        if pipeline_run:
            self.events.emit(
                project_id, evt.RUN_CREATED,
                {
                    "run_id": run_id,
                    "run_number": pipeline_run.run_number,
                    "ai_loops": pipeline_run.ai_loops,
                    "stop_point": pipeline_run.stop_point.value if pipeline_run.stop_point else "end_of_phase",
                    "start_stage_key": pipeline_run.start_stage_key,
                    "start_component_key": pipeline_run.start_component_key,
                },
                run_id=run_id,
            )

        carried = self._carry_over_approved(project_id, run_id)
        logger.info("Carried over %d approved executions into run %s", carried, run_id)

        # Re-populate component/sub-component definitions from carried-over
        # branching stages.  _store_components only runs via _post_generation_hook
        # during the original execution — carry-over doesn't re-run it, so the
        # ComponentDefinition rows may be missing (e.g. after DB issues or the
        # first run being in a bad state).
        await self._ensure_branching_definitions(project_id, config, run_id)

        stages = sorted(config.stages, key=lambda s: s.order_index)
        logger.info(
            "Pipeline run_id=%s (run #%s) starting with %d stages: %s",
            run_id,
            pipeline_run.run_number if pipeline_run else "?",
            len(stages),
            [s.stage_key for s in stages],
        )

        await self._find_and_execute_next(project_id, run_id, config, pipeline_run)
        return run_id

    async def resume_run(
        self,
        project_id: str,
        pipeline_run_id: str,
        prev_run_id: str,
    ) -> str:
        """Resume a pipeline by carrying over work from a previous run.

        Carries over APPROVED executions (non-stale) from across all runs,
        plus AWAITING_REVIEW executions from the specific previous run.
        """
        logger.info(
            "resume_run called: project_id=%s, pipeline_run_id=%s, prev_run_id=%s",
            project_id,
            pipeline_run_id,
            prev_run_id,
        )

        project = self.db.get(Project, project_id)
        if not project or not project.pipeline_config:
            raise ValueError("Project or pipeline config not found")

        config = project.pipeline_config
        pipeline_run = self.db.get(PipelineRun, pipeline_run_id)
        if not pipeline_run:
            raise ValueError("PipelineRun not found")

        new_run_id = pipeline_run.run_id

        # Emit run_created event for resumed run
        self.events.emit(
            project_id, evt.RUN_CREATED,
            {
                "run_id": new_run_id,
                "run_number": pipeline_run.run_number,
                "ai_loops": pipeline_run.ai_loops,
                "stop_point": pipeline_run.stop_point.value if pipeline_run.stop_point else "end_of_phase",
                "start_stage_key": pipeline_run.start_stage_key,
                "start_component_key": pipeline_run.start_component_key,
            },
            run_id=new_run_id,
        )

        # Carry over all approved work (searches across all runs)
        carried = self._carry_over_approved(project_id, new_run_id)

        # Additionally carry over AWAITING_REVIEW executions from the previous run
        stale_artifact_ids = {
            a.id
            for a in self.db.query(Artifact)
            .filter_by(project_id=project_id, status=ArtifactStatus.STALE)
            .all()
        }
        review_execs = (
            self.db.query(StageExecution)
            .filter_by(
                project_id=project_id, run_id=prev_run_id, status=StageStatus.AWAITING_REVIEW
            )
            .all()
        )
        review_carried = 0
        for prev_exec in review_execs:
            if prev_exec.artifact_id and prev_exec.artifact_id in stale_artifact_ids:
                continue
            # Check we didn't already carry this over as approved
            already = (
                self.db.query(StageExecution)
                .filter_by(
                    project_id=project_id,
                    run_id=new_run_id,
                    stage_key=prev_exec.stage_key,
                    component_key=prev_exec.component_key,
                )
                .first()
            )
            if already:
                continue
            new_exec = StageExecution(
                project_id=project_id,
                stage_key=prev_exec.stage_key,
                component_key=prev_exec.component_key,
                status=StageStatus.AWAITING_REVIEW,
                artifact_id=prev_exec.artifact_id,
                started_at=prev_exec.started_at,
                completed_at=prev_exec.completed_at,
                run_id=new_run_id,
                retry_count=0,
            )
            self.db.add(new_exec)
            review_carried += 1

        self.db.commit()
        logger.info(
            "Carried over %d approved + %d in-review executions into run %s",
            carried,
            review_carried,
            new_run_id,
        )

        await self._ensure_branching_definitions(project_id, config, new_run_id)

        stages = sorted(config.stages, key=lambda s: s.order_index)
        logger.info(
            "Resume run_id=%s (run #%s) with %d stages: %s",
            new_run_id,
            pipeline_run.run_number,
            len(stages),
            [s.stage_key for s in stages],
        )

        await self._find_and_execute_next(project_id, new_run_id, config, pipeline_run)
        return new_run_id

    async def trigger_stage(
        self,
        project_id: str,
        stage_key: str,
        component_key: str | None = None,
    ) -> str | list[str]:
        """Manually trigger a stage, creating executions as needed.

        For fan-out stages (COMPONENT, SUB_COMPONENT, LEAF), this finds all
        ready entities and triggers them — or a single entity if component_key
        is provided.  For non-fan-out stages it triggers the single execution.

        Returns the execution_id (or list of ids for fan-out).
        """
        config = self._get_config(project_id)
        if not config:
            raise ValueError("Pipeline config not found")

        stage_def = next(
            (s for s in config.stages if s.stage_key == stage_key), None
        )
        if not stage_def:
            raise ValueError(f"Stage definition not found: {stage_key}")

        # Find the latest run for this project
        pipeline_run = (
            self.db.query(PipelineRun)
            .filter_by(project_id=project_id)
            .order_by(PipelineRun.run_number.desc())
            .first()
        )
        run_id = pipeline_run.run_id if pipeline_run else str(uuid.uuid4())

        fan_out = stage_def.fan_out_strategy
        if fan_out in (
            FanOutStrategy.COMPONENT,
            FanOutStrategy.SUB_COMPONENT,
            FanOutStrategy.LEAF,
        ):
            return await self._trigger_fan_out_stage(
                project_id, stage_def, run_id, config, pipeline_run, component_key
            )

        return await self._trigger_single_stage(
            project_id, stage_def, run_id, config, pipeline_run, component_key
        )

    async def _trigger_single_stage(
        self,
        project_id: str,
        stage_def: StageDefinition,
        run_id: str,
        config: PipelineConfig,
        pipeline_run: PipelineRun | None,
        component_key: str | None,
    ) -> str:
        """Trigger a single (non-fan-out) stage."""
        stage_key = stage_def.stage_key

        # Check for an already-running execution
        existing = (
            self.db.query(StageExecution)
            .filter_by(
                project_id=project_id,
                stage_key=stage_key,
                component_key=component_key,
                run_id=run_id,
            )
            .filter(
                StageExecution.status.in_(
                    [StageStatus.RUNNING, StageStatus.AI_REVIEW]
                )
            )
            .first()
        )
        if existing:
            raise ValueError(
                f"Stage {stage_key} (component={component_key}) is already "
                f"running (execution {existing.id})"
            )

        input_artifacts = self._gather_inputs(project_id, stage_def, component_key)

        # Gather any prior feedback
        feedback_notes = None
        prev_exec = (
            self.db.query(StageExecution)
            .filter_by(
                project_id=project_id,
                stage_key=stage_key,
                component_key=component_key,
            )
            .order_by(StageExecution.started_at.desc())
            .first()
        )
        current_content = None
        if prev_exec and prev_exec.artifact_id:
            feedback_notes = self._get_feedback_notes(prev_exec.artifact_id)
            prev_artifact = self.db.get(Artifact, prev_exec.artifact_id)
            if prev_artifact and prev_artifact.content:
                current_content = prev_artifact.content

        execution = StageExecution(
            project_id=project_id,
            stage_key=stage_key,
            component_key=component_key,
            status=StageStatus.RUNNING,
            started_at=datetime.utcnow(),
            run_id=run_id,
        )
        self.db.add(execution)
        self.db.flush()

        logger.info(
            "Manually triggered stage %s (component=%s) execution=%s",
            stage_key, component_key, execution.id,
        )

        await self._run_stage(
            project_id,
            stage_def,
            input_artifacts,
            component_key,
            execution,
            run_id,
            human_notes=feedback_notes,
            current_content=current_content,
            config=config,
            pipeline_run=pipeline_run,
        )
        return execution.id

    async def _trigger_fan_out_stage(
        self,
        project_id: str,
        stage_def: StageDefinition,
        run_id: str,
        config: PipelineConfig,
        pipeline_run: PipelineRun | None,
        component_key: str | None,
    ) -> list[str]:
        """Trigger a fan-out stage for ready entities (or a specific one)."""
        stage_key = stage_def.stage_key

        if component_key:
            # Trigger a specific entity
            entity_keys = [component_key]
        else:
            # Find all ready entities
            entity_keys = self._get_ready_entities(project_id, stage_def, run_id)
            if not entity_keys:
                all_entities = self._get_all_entities_for_stage(project_id, stage_def)
                if not all_entities:
                    raise ValueError(
                        f"No entities found for fan-out stage {stage_key}"
                    )
                raise ValueError(
                    f"No entities are ready for stage {stage_key}. "
                    f"{len(all_entities)} entities exist but are blocked on "
                    f"upstream dependencies or already have non-rejected executions."
                )

        execution_ids = []
        for entity_key in entity_keys:
            # Check for an already-running execution
            existing = (
                self.db.query(StageExecution)
                .filter_by(
                    project_id=project_id,
                    stage_key=stage_key,
                    component_key=entity_key,
                    run_id=run_id,
                )
                .filter(
                    StageExecution.status.in_(
                        [StageStatus.RUNNING, StageStatus.AI_REVIEW]
                    )
                )
                .first()
            )
            if existing:
                logger.info(
                    "Skipping %s/%s — already running (execution %s)",
                    stage_key, entity_key, existing.id,
                )
                continue

            input_artifacts = self._gather_inputs(project_id, stage_def, entity_key)

            # Gather any prior feedback
            feedback_notes = None
            current_content = None
            prev_exec = (
                self.db.query(StageExecution)
                .filter_by(
                    project_id=project_id,
                    stage_key=stage_key,
                    component_key=entity_key,
                )
                .order_by(StageExecution.started_at.desc())
                .first()
            )
            if prev_exec and prev_exec.artifact_id:
                feedback_notes = self._get_feedback_notes(prev_exec.artifact_id)
                prev_artifact = self.db.get(Artifact, prev_exec.artifact_id)
                if prev_artifact and prev_artifact.content:
                    current_content = prev_artifact.content

            execution = StageExecution(
                project_id=project_id,
                stage_key=stage_key,
                component_key=entity_key,
                status=StageStatus.RUNNING,
                started_at=datetime.utcnow(),
                run_id=run_id,
            )
            self.db.add(execution)
            self.db.flush()

            logger.info(
                "Manually triggered fan-out stage %s entity=%s execution=%s",
                stage_key, entity_key, execution.id,
            )

            await self._run_stage(
                project_id,
                stage_def,
                input_artifacts,
                entity_key,
                execution,
                run_id,
                human_notes=feedback_notes,
                current_content=current_content,
                config=config,
                pipeline_run=pipeline_run,
            )
            execution_ids.append(execution.id)

            if execution.status == StageStatus.FAILED:
                logger.error(
                    "Stopping trigger: entity %s failed", entity_key
                )
                break

        if not execution_ids:
            raise ValueError(
                f"All entities for stage {stage_key} are already running"
            )

        return execution_ids

    def _carry_over_approved(self, project_id: str, new_run_id: str) -> int:
        """Carry over the most recent APPROVED execution for each (stage, component)
        across ALL previous runs.  Skips executions whose artifact is currently STALE.

        Returns the number of executions carried over.
        """
        from sqlalchemy import func

        # Reconcile mismatches: if an artifact is APPROVED but its latest
        # execution is not, sync the execution so it gets carried over
        # instead of silently dropping it.
        mismatched = (
            self.db.query(StageExecution)
            .filter_by(project_id=project_id)
            .filter(StageExecution.run_id != new_run_id)
            .filter(StageExecution.artifact_id.isnot(None))
            .filter(StageExecution.status != StageStatus.APPROVED)
            .join(Artifact, StageExecution.artifact_id == Artifact.id)
            .filter(Artifact.status == ArtifactStatus.APPROVED)
            .all()
        )
        for ex in mismatched:
            logger.warning(
                "Reconciling status mismatch: execution %s (stage=%s, status=%s) "
                "has approved artifact %s — setting execution to APPROVED",
                ex.id, ex.stage_key, ex.status.value, ex.artifact_id,
            )
            self._transition_execution(
                ex, StageStatus.APPROVED,
                set_completed=not ex.completed_at,
            )
        if mismatched:
            self.db.flush()

        stale_artifact_ids = {
            a.id
            for a in self.db.query(Artifact)
            .filter_by(project_id=project_id, status=ArtifactStatus.STALE)
            .all()
        }

        # For each (stage_key, component_key), find the most recent APPROVED
        # execution across all runs (by completed_at desc).
        # Use a subquery to get the max id per group.
        subq = (
            self.db.query(
                StageExecution.stage_key,
                func.coalesce(StageExecution.component_key, "").label("ck"),
                func.max(StageExecution.completed_at).label("max_completed"),
            )
            .filter_by(project_id=project_id, status=StageStatus.APPROVED)
            .filter(StageExecution.run_id != new_run_id)
            .group_by(StageExecution.stage_key, func.coalesce(StageExecution.component_key, ""))
            .subquery()
        )

        best_execs = (
            self.db.query(StageExecution)
            .filter_by(project_id=project_id, status=StageStatus.APPROVED)
            .filter(StageExecution.run_id != new_run_id)
            .join(
                subq,
                (StageExecution.stage_key == subq.c.stage_key)
                & (func.coalesce(StageExecution.component_key, "") == subq.c.ck)
                & (StageExecution.completed_at == subq.c.max_completed),
            )
            .all()
        )

        carried = 0
        seen = set()
        for prev_exec in best_execs:
            key = (prev_exec.stage_key, prev_exec.component_key)
            if key in seen:
                continue  # deduplicate ties
            seen.add(key)

            if prev_exec.artifact_id and prev_exec.artifact_id in stale_artifact_ids:
                logger.info(
                    "Skipping stale execution (stage=%s, component=%s, artifact=%s)",
                    prev_exec.stage_key,
                    prev_exec.component_key,
                    prev_exec.artifact_id,
                )
                continue

            logger.info(
                "Carrying over execution: stage=%s component=%s artifact=%s",
                prev_exec.stage_key,
                prev_exec.component_key,
                prev_exec.artifact_id,
            )
            new_exec = StageExecution(
                project_id=project_id,
                stage_key=prev_exec.stage_key,
                component_key=prev_exec.component_key,
                status=StageStatus.APPROVED,
                artifact_id=prev_exec.artifact_id,
                started_at=prev_exec.started_at,
                completed_at=prev_exec.completed_at,
                run_id=new_run_id,
                retry_count=0,
            )
            self.db.add(new_exec)
            carried += 1

            # Emit carried_over event
            self.events.emit(
                project_id, evt.CARRIED_OVER,
                {
                    "execution_id": new_exec.id,
                    "stage_key": new_exec.stage_key,
                    "component_key": new_exec.component_key,
                    "artifact_id": new_exec.artifact_id,
                    "from_run_id": prev_exec.run_id,
                    "to_run_id": new_run_id,
                },
                run_id=new_run_id,
            )

        self.db.commit()
        return carried

    async def _ensure_branching_definitions(
        self, project_id: str, config: PipelineConfig, run_id: str
    ):
        """Re-populate component/sub-component definitions if missing.

        When a branching stage (extract_components, extract_sub_components) is
        carried over from a previous run, the ComponentDefinition rows may not
        exist — _store_components only runs during the original
        _post_generation_hook.  This method detects that gap and re-runs the
        hook so fan-out stages can find their entities.
        """
        for stage_def in config.stages:
            if stage_def.stage_key not in BRANCHING_STAGES:
                continue

            exec_ = (
                self.db.query(StageExecution)
                .filter_by(
                    project_id=project_id,
                    stage_key=stage_def.stage_key,
                    run_id=run_id,
                    status=StageStatus.APPROVED,
                )
                .first()
            )
            if not exec_ or not exec_.artifact_id:
                continue

            # Check if definitions already exist
            if stage_def.stage_key == "extract_components":
                existing = self._get_components(project_id)
                if existing:
                    continue
            elif stage_def.stage_key == "extract_sub_components":
                existing = self._get_sub_component_defs(project_id)
                if existing:
                    continue

            logger.info(
                "Re-populating definitions for carried-over %s (artifact=%s)",
                stage_def.stage_key,
                exec_.artifact_id,
            )
            await self._post_generation_hook(
                project_id, stage_def, exec_.component_key, exec_
            )
            self.db.commit()

    def _should_pause(
        self,
        stage_def: StageDefinition,
        pipeline_run: PipelineRun | None,
        project_id: str | None = None,
    ) -> bool:
        """Determine if the pipeline should pause after executing this stage.

        Stop points control when the run halts generation:
        - EVERY_ARTIFACT: stop after every wave of generation
        - BEFORE_CODE: stop before code_generation/code_review stages
        - END_OF_PHASE: stop when work moves past the starting phase
        """
        if not pipeline_run:
            return True  # No run context — always pause

        stop = pipeline_run.stop_point

        if stop == StopPoint.EVERY_ARTIFACT:
            return True

        if stop == StopPoint.BEFORE_CODE:
            return stage_def.stage_key in ("code_generation", "code_review")

        if stop == StopPoint.END_OF_PHASE:
            start_order = self._get_start_order(pipeline_run, project_id)
            # If starting phase is already fully generated, target the next phase
            if project_id and self._starting_phase_complete(pipeline_run, project_id):
                start_order += 1
            return stage_def.order_index > start_order

        # Legacy stop points — treat as end_of_phase
        return True

    def _get_start_order(self, pipeline_run: PipelineRun, project_id: str | None = None) -> int:
        """Get the order_index of the run's starting stage."""
        from backend.pipeline.readiness import _STAGE_KEY_TO_ORDER
        if pipeline_run.start_stage_key:
            return _STAGE_KEY_TO_ORDER.get(pipeline_run.start_stage_key, 0)
        # No explicit start — start from beginning
        return 0

    def _starting_phase_complete(self, pipeline_run: PipelineRun, project_id: str) -> bool:
        """Check if the starting phase of a run is already fully generated."""
        if not pipeline_run.start_stage_key:
            return False
        config = self._get_config(project_id)
        if not config:
            return False
        stage_def = next(
            (s for s in config.stages if s.stage_key == pipeline_run.start_stage_key), None
        )
        if not stage_def:
            return False
        return self._stage_fully_generated(project_id, stage_def, pipeline_run.run_id)

    async def _find_and_execute_next(
        self,
        project_id: str,
        run_id: str,
        config: PipelineConfig,
        pipeline_run: PipelineRun | None = None,
    ):
        """Find the next executable work item across all stages and execute it.

        Scans the full DAG rather than stopping at the first incomplete stage,
        so downstream entities whose dependencies are met can progress even while
        sibling entities in earlier stages are still awaiting review.

        Key behaviors:
        - Dependencies are satisfied by "generated" status (not just approved)
        - AWAITING_REVIEW nodes do NOT block downstream generation
        - Only RUNNING/AI_REVIEW states represent truly in-flight work
        - Run scope is filtered by start_stage_key/start_component_key
        - Stop point controls when the run halts
        """
        stages = sorted(config.stages, key=lambda s: s.order_index)
        has_inflight_work = False
        generated_work_this_pass = False

        for stage_def in stages:
            # Skip stages outside run scope
            if not self._is_in_run_scope(stage_def, None, pipeline_run):
                continue

            # Check if stage is fully generated (has content for all entities)
            if self._stage_fully_generated(project_id, stage_def, run_id):
                logger.info("Stage %s: fully generated, skipping", stage_def.stage_key)
                continue
            logger.info(
                "Stage %s: not fully generated (fan_out=%s), checking readiness",
                stage_def.stage_key,
                stage_def.fan_out_strategy.value if stage_def.fan_out_strategy else "none",
            )

            # Check if any executions are still truly in-flight (RUNNING/AI_REVIEW)
            inflight_count = (
                self.db.query(StageExecution)
                .filter_by(
                    project_id=project_id,
                    stage_key=stage_def.stage_key,
                    run_id=run_id,
                )
                .filter(
                    StageExecution.status.in_(
                        [StageStatus.RUNNING, StageStatus.AI_REVIEW]
                    )
                )
                .count()
            )
            if inflight_count > 0:
                has_inflight_work = True
                logger.info(
                    "Stage %s has %d in-flight executions, scanning downstream",
                    stage_def.stage_key,
                    inflight_count,
                )
                continue

            fan_out = stage_def.fan_out_strategy

            if fan_out == FanOutStrategy.NONE:
                # Single artifact stage — check if already has an execution
                existing = (
                    self.db.query(StageExecution)
                    .filter_by(
                        project_id=project_id,
                        stage_key=stage_def.stage_key,
                        run_id=run_id,
                    )
                    .filter(StageExecution.status.notin_([StageStatus.REJECTED]))
                    .first()
                )
                if existing:
                    # Already has a non-rejected execution (awaiting_review, approved, failed)
                    if existing.status == StageStatus.FAILED:
                        has_inflight_work = True
                    continue

                # Check scope for non-fan-out
                if not self._is_in_run_scope(stage_def, None, pipeline_run):
                    continue

                # regen_generated_only: skip if entity doesn't already have content
                if pipeline_run and pipeline_run.regen_generated_only:
                    if not self._entity_already_generated(
                        project_id, stage_def.stage_key, None
                    ):
                        continue

                # Execute single stage
                input_artifacts = self._gather_inputs(project_id, stage_def)
                rejected_notes = self._get_rejected_notes(project_id, stage_def)
                execution = StageExecution(
                    project_id=project_id,
                    stage_key=stage_def.stage_key,
                    status=StageStatus.RUNNING,
                    started_at=datetime.utcnow(),
                    run_id=run_id,
                )
                self.db.add(execution)
                self.db.flush()

                await self._run_stage(
                    project_id,
                    stage_def,
                    input_artifacts,
                    None,
                    execution,
                    run_id,
                    human_notes=rejected_notes,
                    config=config,
                    pipeline_run=pipeline_run,
                )

                if execution.status == StageStatus.FAILED:
                    logger.error("Pipeline stopped: stage %s failed", stage_def.stage_key)
                    await ws_manager.broadcast(
                        project_id,
                        {
                            "type": "pipeline_completed",
                            "run_id": run_id,
                        },
                    )
                    return

                # Post-generation hooks (deferred for branching stages until approval)
                if execution.status == StageStatus.AWAITING_REVIEW:
                    if stage_def.stage_key not in BRANCHING_STAGES:
                        await self._post_generation_hook(project_id, stage_def, None, execution)

                generated_work_this_pass = True

                # Check if pipeline should pause at this stage
                if self._should_pause(stage_def, pipeline_run, project_id):
                    self.events.emit(
                        project_id, evt.PIPELINE_PAUSED,
                        {"stage_key": stage_def.stage_key, "run_id": run_id},
                        run_id=run_id,
                    )
                    await ws_manager.broadcast(
                        project_id,
                        {
                            "type": "pipeline_paused",
                            "stage_key": stage_def.stage_key,
                            "run_id": run_id,
                            "message": f"Awaiting review for {stage_def.display_name}",
                        },
                    )
                    return

            elif fan_out in (
                FanOutStrategy.COMPONENT,
                FanOutStrategy.SUB_COMPONENT,
                FanOutStrategy.LEAF,
            ):
                ready = self._get_ready_entities(
                    project_id, stage_def, run_id, pipeline_run=pipeline_run
                )
                if not ready:
                    # No entities ready — check if any entities exist at all
                    all_entities = self._get_all_entities_for_stage(project_id, stage_def)
                    if not all_entities:
                        logger.info("No entities for stage %s, skipping", stage_def.stage_key)
                        continue
                    # Log why entities aren't ready
                    for ek in all_entities[:5]:
                        ex = (
                            self.db.query(StageExecution)
                            .filter_by(
                                project_id=project_id,
                                stage_key=stage_def.stage_key,
                                run_id=run_id,
                                component_key=ek,
                            )
                            .filter(StageExecution.status.notin_([StageStatus.REJECTED]))
                            .first()
                        )
                        logger.info(
                            "  entity %s not ready: existing_exec=%s (status=%s)",
                            ek,
                            ex.id if ex else None,
                            ex.status.value if ex else "n/a",
                        )
                    logger.info(
                        "Stage %s: %d entities exist but none ready, scanning downstream",
                        stage_def.stage_key,
                        len(all_entities),
                    )
                    continue

                # Execute ready entities
                stage_failed = False
                for entity_key in ready:
                    input_artifacts = self._gather_inputs(project_id, stage_def, entity_key)
                    rejected_notes = self._get_rejected_notes(project_id, stage_def, entity_key)
                    execution = StageExecution(
                        project_id=project_id,
                        stage_key=stage_def.stage_key,
                        component_key=entity_key,
                        status=StageStatus.RUNNING,
                        started_at=datetime.utcnow(),
                        run_id=run_id,
                    )
                    self.db.add(execution)
                    self.db.flush()

                    await self._run_stage(
                        project_id,
                        stage_def,
                        input_artifacts,
                        entity_key,
                        execution,
                        run_id,
                        human_notes=rejected_notes,
                        config=config,
                        pipeline_run=pipeline_run,
                    )

                    if execution.status == StageStatus.FAILED:
                        stage_failed = True
                        break

                    # Post-generation hooks (deferred for branching stages until approval)
                    if execution.status == StageStatus.AWAITING_REVIEW:
                        if stage_def.stage_key not in BRANCHING_STAGES:
                            await self._post_generation_hook(
                                project_id, stage_def, entity_key, execution
                            )

                if stage_failed:
                    logger.error("Pipeline stopped: stage %s failed", stage_def.stage_key)
                    await ws_manager.broadcast(
                        project_id,
                        {
                            "type": "pipeline_completed",
                            "run_id": run_id,
                        },
                    )
                    return

                generated_work_this_pass = True

                # Check if pipeline should pause at this stage
                if self._should_pause(stage_def, pipeline_run, project_id):
                    self.events.emit(
                        project_id, evt.PIPELINE_PAUSED,
                        {"stage_key": stage_def.stage_key, "run_id": run_id},
                        run_id=run_id,
                    )
                    await ws_manager.broadcast(
                        project_id,
                        {
                            "type": "pipeline_paused",
                            "stage_key": stage_def.stage_key,
                            "run_id": run_id,
                            "message": f"Awaiting review for {stage_def.display_name}",
                        },
                    )
                    return

        # If in-flight work exists, the pipeline isn't finished — just no new work to do
        if has_inflight_work:
            return

        # If we get here, all stages are complete
        logger.info("Pipeline run_id=%s completed successfully", run_id)

        git_commit_sha = None
        if pipeline_run:
            pipeline_run.status = PipelineRunStatus.COMPLETED
            pipeline_run.completed_at = datetime.utcnow()
            self.db.commit()

            # Emit run_completed event
            self.events.emit(
                project_id, evt.RUN_COMPLETED,
                {"run_id": run_id, "status": "completed"},
                run_id=run_id,
            )

            # Git checkpoint: commit siege-state.json + any remaining changes
            try:
                from backend.git_manager.service import git_manager
                from backend.pipeline.checkpoint import build_siege_state

                siege_state = build_siege_state(self.db, project_id, pipeline_run)
                git_commit_sha = git_manager.checkpoint_run(
                    project_id,
                    siege_state,
                    f"Run #{pipeline_run.run_number} completed",
                )
                pipeline_run.git_commit_sha = git_commit_sha
                self.db.commit()

                # Record git checkpoint in event trail
                self.events.emit(
                    project_id, evt.ARTIFACT_COMMITTED,
                    {
                        "git_commit_sha": git_commit_sha,
                        "run_id": run_id,
                        "run_number": pipeline_run.run_number,
                        "scope": "run_checkpoint",
                    },
                    run_id=run_id,
                )

                # Auto-push if configured
                project = self.db.get(Project, project_id)
                if project and project.auto_push_enabled and project.remote_url:
                    try:
                        git_manager.push_current_branch(project_id)
                        logger.info(
                            "Auto-pushed run #%d for project %s",
                            pipeline_run.run_number,
                            project_id,
                        )
                    except Exception as push_err:
                        logger.warning("Auto-push failed for project %s: %s", project_id, push_err)
            except Exception as ckpt_err:
                logger.error("Checkpoint failed for run #%d: %s", pipeline_run.run_number, ckpt_err)

        await ws_manager.broadcast(
            project_id,
            {
                "type": "pipeline_completed",
                "run_id": run_id,
                "run_number": pipeline_run.run_number if pipeline_run else None,
                "git_commit_sha": git_commit_sha,
            },
        )

    async def _run_stage(
        self,
        project_id: str,
        stage_def: StageDefinition,
        input_artifacts: dict[str, str],
        component_key: str | None,
        execution: StageExecution,
        run_id: str,
        human_notes: str | None = None,
        current_content: str | None = None,
        config: PipelineConfig | None = None,
        pipeline_run: PipelineRun | None = None,
    ):
        """Run a single stage (generate -> ai_review -> set status)."""
        logger.info(
            "_run_stage: stage=%s component=%s execution_id=%s human_notes=%s",
            stage_def.stage_key,
            component_key,
            execution.id,
            f"{len(human_notes)} chars" if human_notes else "None",
        )
        logger.info("  input_artifacts keys: %s", list(input_artifacts.keys()))

        # Commit the RUNNING execution so other sessions (DAG endpoint) can see it
        self.db.commit()

        # Emit stage_started event for event history
        self.events.emit(
            project_id, evt.STAGE_STARTED,
            {
                "execution_id": execution.id,
                "stage_key": stage_def.stage_key,
                "component_key": component_key,
                "artifact_id": execution.artifact_id,
                "trigger": "pipeline_run",
                "retry_count": execution.retry_count,
            },
            run_id=execution.run_id,
        )

        try:
            self.events.emit(
                project_id, evt.GENERATION_PROGRESS,
                {
                    "stage_key": stage_def.stage_key,
                    "component_key": component_key,
                    "step": "generating",
                },
                run_id=execution.run_id,
            )
            await ws_manager.broadcast(
                project_id,
                {
                    "type": "stage_progress",
                    "stage_key": stage_def.stage_key,
                    "component_key": component_key,
                    "step": "generating",
                    "message": f"Generating {stage_def.display_name}...",
                },
            )

            content, artifact_id = await generate(
                stage_def,
                input_artifacts,
                component_key,
                self.db,
                human_notes=human_notes,
                current_content=current_content,
                execution_id=execution.id,
            )
            execution.artifact_id = artifact_id

            # Record artifact git commit in event trail
            gen_artifact = self.db.get(Artifact, artifact_id)
            if gen_artifact and gen_artifact.git_commit_sha:
                self.events.emit(
                    project_id, evt.ARTIFACT_COMMITTED,
                    {
                        "artifact_id": artifact_id,
                        "git_commit_sha": gen_artifact.git_commit_sha,
                        "version": gen_artifact.version,
                        "artifact_type": gen_artifact.artifact_type.value,
                        "artifact_name": gen_artifact.name,
                        "scope": "generation",
                    },
                    run_id=execution.run_id,
                )

            # AI Review
            if stage_def.ai_review_enabled:
                self.events.emit(
                    project_id, evt.GENERATION_PROGRESS,
                    {
                        "stage_key": stage_def.stage_key,
                        "component_key": component_key,
                        "step": "ai_reviewing",
                    },
                    run_id=execution.run_id,
                )
                await ws_manager.broadcast(
                    project_id,
                    {
                        "type": "stage_progress",
                        "stage_key": stage_def.stage_key,
                        "component_key": component_key,
                        "step": "ai_reviewing",
                        "message": f"AI reviewing {stage_def.display_name}...",
                    },
                )

                self._transition_execution(
                    execution, StageStatus.AI_REVIEW,
                    artifact_status=None,
                )
                self.db.flush()

                feedback = await ai_review(
                    stage_def,
                    content,
                    input_artifacts,
                    review_prompt_overrides=stage_def.pipeline_config.review_prompt_overrides,
                )
                artifact = self.db.get(Artifact, artifact_id)
                if artifact:
                    artifact.ai_review_feedback = feedback
                    artifact.status = ArtifactStatus.AI_REVIEWING

                # Self-improvement loops: refine with AI feedback
                ai_loops = pipeline_run.ai_loops if pipeline_run else 1
                if feedback and ai_loops > 1:
                    for loop_i in range(1, ai_loops):
                        self.events.emit(
                            project_id, evt.GENERATION_PROGRESS,
                            {
                                "stage_key": stage_def.stage_key,
                                "component_key": component_key,
                                "step": "self_improvement",
                                "loop": loop_i + 1,
                                "total_loops": ai_loops,
                            },
                            run_id=execution.run_id,
                        )
                        await ws_manager.broadcast(
                            project_id,
                            {
                                "type": "stage_progress",
                                "stage_key": stage_def.stage_key,
                                "component_key": component_key,
                                "step": "self_improvement",
                                "message": (
                                    f"Self-improvement loop {loop_i + 1}/{ai_loops}"
                                    f" for {stage_def.display_name}..."
                                ),
                            },
                        )

                        content, artifact_id = await generate(
                            stage_def,
                            input_artifacts,
                            component_key,
                            self.db,
                            feedback=feedback,
                            human_notes=human_notes,
                            execution_id=execution.id,
                        )
                        execution.artifact_id = artifact_id

                        # Re-review
                        feedback = await ai_review(
                            stage_def,
                            content,
                            input_artifacts,
                            review_prompt_overrides=stage_def.pipeline_config.review_prompt_overrides,
                        )
                        artifact = self.db.get(Artifact, artifact_id)
                        if artifact:
                            artifact.ai_review_feedback = feedback

            # All generated artifacts go to AWAITING_REVIEW — only human
            # approval can move them to APPROVED.
            self._transition_execution(
                execution, StageStatus.AWAITING_REVIEW,
                artifact_status=ArtifactStatus.AWAITING_REVIEW,
            )

            self.db.commit()

            await ws_manager.broadcast(
                project_id,
                {
                    "type": "stage_awaiting_review",
                    "stage_key": stage_def.stage_key,
                    "component_key": component_key,
                    "artifact_id": artifact_id,
                },
            )

        except asyncio.CancelledError:
            logger.info(
                "Stage %s cancelled for component=%s (force-restart)", stage_def.stage_key, component_key
            )
            # Unstick artifact status so the retry can start clean
            art_status = None
            if execution.artifact_id:
                stuck_artifact = self.db.get(Artifact, execution.artifact_id)
                if stuck_artifact and stuck_artifact.status in (
                    ArtifactStatus.GENERATING,
                    ArtifactStatus.AI_REVIEWING,
                ):
                    art_status = ArtifactStatus.PENDING

            self._transition_execution(
                execution, StageStatus.FAILED,
                artifact_status=art_status,
                error_message="Cancelled by force-restart",
                set_completed=True,
            )
            self.db.commit()
            raise  # Let the worker loop see the CancelledError

        except Exception as e:
            logger.exception(
                "Stage %s failed for component=%s: %s", stage_def.stage_key, component_key, e
            )
            # Determine safe artifact status: unstick GENERATING/AI_REVIEWING → PENDING
            art_status = None
            if execution.artifact_id:
                stuck_artifact = self.db.get(Artifact, execution.artifact_id)
                if stuck_artifact and stuck_artifact.status in (
                    ArtifactStatus.GENERATING,
                    ArtifactStatus.AI_REVIEWING,
                ):
                    art_status = ArtifactStatus.PENDING

            self._transition_execution(
                execution, StageStatus.FAILED,
                artifact_status=art_status,
                error_message=str(e),
                set_completed=True,
            )

            self.db.commit()

            await ws_manager.broadcast(
                project_id,
                {
                    "type": "stage_failed",
                    "stage_key": stage_def.stage_key,
                    "component_key": component_key,
                    "error": str(e),
                },
            )

    def _lookup_pipeline_run(self, run_id: str) -> PipelineRun | None:
        """Look up a PipelineRun by its run_id."""
        return self.db.query(PipelineRun).filter_by(run_id=run_id).first()

    def _get_feedback_notes(self, artifact_id: str) -> str | None:
        """Build accumulated feedback from ArtifactComment records (feedback only).

        Queries only comment_type='feedback' — never regular comments or system events.
        """
        feedbacks = (
            self.db.query(ArtifactComment)
            .filter_by(artifact_id=artifact_id, comment_type="feedback")
            .order_by(ArtifactComment.created_at.asc())
            .all()
        )
        if not feedbacks:
            return None
        return "\n\n---\n\n".join(f.content for f in feedbacks)

    def _get_rejected_notes(
        self,
        project_id: str,
        stage_def: StageDefinition,
        component_key: str | None = None,
    ) -> str | None:
        """If this stage has a rejected artifact with feedback comments, return them.

        Only checks REJECTED artifacts (explicit user rejection).  STALE artifacts
        are excluded because their feedback was written about content generated from
        a different upstream context and may conflict with the current inputs
        (e.g. after an upstream revert).
        """
        artifact_type_val = stage_def.output_artifact_type
        query = (
            self.db.query(Artifact)
            .filter_by(project_id=project_id)
            .filter(Artifact.status == ArtifactStatus.REJECTED)
            .filter(Artifact.artifact_type == artifact_type_val)
        )
        if component_key:
            query = query.filter_by(component_key=component_key)
        artifact = query.first()
        if artifact:
            return self._get_feedback_notes(artifact.id)
        return None

    def _gather_inputs(
        self, project_id: str, stage_def: StageDefinition, component_key: str | None = None,
        *, include_stale: bool = False,
    ) -> dict[str, str]:
        """Gather input artifact contents for a stage.

        For sub-component stages (component_key contains '.'), automatically
        resolves parent-level inputs by the parent key and sub-component-level
        inputs by the full key.

        When *include_stale* is True, STALE artifacts are also accepted as
        inputs.  This is used during regeneration/revision flows where the
        caller explicitly wants to use whatever content is available rather
        than failing due to missing context.
        """
        _accepted_statuses = [ArtifactStatus.APPROVED, ArtifactStatus.AWAITING_REVIEW]
        if include_stale:
            _accepted_statuses.append(ArtifactStatus.STALE)

        inputs: dict[str, str] = {}

        if not stage_def.input_stage_keys:
            # First stage: use project doc
            project_doc = (
                self.db.query(Artifact)
                .filter_by(
                    project_id=project_id,
                    artifact_type=ArtifactType.PROJECT_DOC,
                )
                .first()
            )
            if project_doc:
                inputs["project_doc"] = project_doc.content or ""
            # Include input documents for the first stage
            inputs = self._inject_input_documents(project_id, "system_requirements", inputs)
            return inputs

        # Determine if this is a sub-component entity
        parent_key = None
        if component_key and "." in component_key:
            parent_key = component_key.split(".")[0]

        for stage_key in stage_def.input_stage_keys:
            artifact_type = _stage_key_to_artifact_type(stage_key)

            # Determine which component_key to filter by
            filter_key = None
            if component_key:
                if _is_sub_component_stage(stage_key) and parent_key:
                    # Sub-component input for sub-component entity → use full key
                    filter_key = component_key
                elif _is_component_stage(stage_key) and parent_key:
                    # Component-level input for sub-component entity → use parent key
                    filter_key = parent_key
                elif _is_component_stage(stage_key) or _is_sub_component_stage(stage_key):
                    # Component-level input for component entity
                    filter_key = component_key

            if filter_key:
                artifact = (
                    self.db.query(Artifact)
                    .filter_by(
                        project_id=project_id,
                        artifact_type=artifact_type,
                        component_key=filter_key,
                    )
                    .filter(Artifact.status.in_(_accepted_statuses))
                    .first()
                )
                if artifact and artifact.content:
                    inputs[stage_key] = artifact.content
            else:
                # Project-level or aggregated input
                artifacts = (
                    self.db.query(Artifact)
                    .filter_by(project_id=project_id, artifact_type=artifact_type)
                    .filter(Artifact.status.in_(_accepted_statuses))
                    .all()
                )
                if len(artifacts) == 1:
                    inputs[stage_key] = artifacts[0].content or ""
                elif len(artifacts) > 1:
                    combined = "\n\n---\n\n".join(
                        f"### {a.component_key or a.name}\n\n{a.content}"
                        for a in artifacts
                        if a.content
                    )
                    inputs[stage_key] = combined

        # Inject dependency component/sub-component architectures
        if component_key and not parent_key:
            # Top-level component — get dependency architectures
            comp_def = (
                self.db.query(ComponentDefinition)
                .filter_by(project_id=project_id, key=component_key, parent_key=None)
                .first()
            )
            if comp_def and comp_def.dependencies:
                dep_parts = []
                for dep_key in comp_def.dependencies:
                    dep_art = (
                        self.db.query(Artifact)
                        .filter_by(
                            project_id=project_id,
                            artifact_type=ArtifactType.COMPONENT_ARCHITECTURE,
                            component_key=dep_key,
                        )
                        .filter(Artifact.status.in_(_accepted_statuses))
                        .first()
                    )
                    if dep_art and dep_art.content:
                        dep_parts.append(f"### {dep_key}\n\n{dep_art.content}")
                if dep_parts:
                    inputs["dependency_architectures"] = "\n\n---\n\n".join(dep_parts)

        elif component_key and parent_key:
            # Sub-component — get sibling dependency architectures
            sc_def = (
                self.db.query(ComponentDefinition)
                .filter_by(
                    project_id=project_id,
                    key=component_key.split(".")[-1],
                    parent_key=parent_key,
                )
                .first()
            )
            if sc_def and sc_def.dependencies:
                dep_parts = []
                for dep_key in sc_def.dependencies:
                    full_dep_key = f"{parent_key}.{dep_key}"
                    dep_art = (
                        self.db.query(Artifact)
                        .filter_by(
                            project_id=project_id,
                            artifact_type=ArtifactType.SUB_COMPONENT_ARCHITECTURE,
                            component_key=full_dep_key,
                        )
                        .filter(Artifact.status.in_(_accepted_statuses))
                        .first()
                    )
                    if dep_art and dep_art.content:
                        dep_parts.append(f"### {full_dep_key}\n\n{dep_art.content}")
                if dep_parts:
                    inputs["dependency_architectures"] = "\n\n---\n\n".join(dep_parts)

        # Inject input documents for stages that opt in
        inputs = self._inject_input_documents(project_id, stage_def.stage_key, inputs)

        return inputs

    def _inject_input_documents(
        self, project_id: str, stage_key: str, inputs: dict[str, str]
    ) -> dict[str, str]:
        """Add input documents configured to inject into this stage."""
        from backend.models import InputDocument

        docs = (
            self.db.query(InputDocument)
            .filter_by(project_id=project_id)
            .all()
        )
        matching = [d for d in docs if stage_key in (d.inject_into_stages or [])]
        if matching:
            doc_parts = [
                f"### {d.name} ({d.doc_type})\n\n{d.content}"
                for d in matching
            ]
            inputs["input_documents"] = "\n\n---\n\n".join(doc_parts)
        return inputs

    def _get_artifact_content(self, project_id: str, artifact_type: ArtifactType) -> str | None:
        artifact = (
            self.db.query(Artifact)
            .filter_by(project_id=project_id, artifact_type=artifact_type)
            .first()
        )
        return artifact.content if artifact else None


# Helper functions

_COMPONENT_STAGES = {
    "component_architectures",
    "component_plans",
    "extract_sub_components",
}
_SUB_COMPONENT_STAGES = {
    "sub_component_architectures",
    "sub_component_plans",
}


def _is_component_stage(stage_key: str) -> bool:
    return stage_key in _COMPONENT_STAGES


def _is_sub_component_stage(stage_key: str) -> bool:
    return stage_key in _SUB_COMPONENT_STAGES


def _status_to_event_type(status: StageStatus) -> str | None:
    """Map a StageStatus to its corresponding event type."""
    return {
        StageStatus.RUNNING: evt.STAGE_STARTED,
        StageStatus.AI_REVIEW: evt.AI_REVIEW_STARTED,
        StageStatus.AWAITING_REVIEW: evt.AWAITING_HUMAN_REVIEW,
        StageStatus.APPROVED: evt.HUMAN_APPROVED,
        StageStatus.REJECTED: evt.HUMAN_REJECTED,
        StageStatus.FAILED: evt.STAGE_FAILED,
        StageStatus.SKIPPED: evt.STAGE_SKIPPED,
    }.get(status)


def _stage_key_to_artifact_type(stage_key: str) -> ArtifactType:
    mapping = {
        "system_requirements": ArtifactType.SYSTEM_REQUIREMENTS,
        "component_requirements": ArtifactType.COMPONENT_REQUIREMENTS,
        "system_architecture": ArtifactType.SYSTEM_ARCHITECTURE,
        "component_architectures": ArtifactType.COMPONENT_ARCHITECTURE,
        "component_plans": ArtifactType.COMPONENT_PLAN,
        "extract_components": ArtifactType.COMPONENT_MAP,
        "extract_sub_components": ArtifactType.SUB_COMPONENT_MAP,
        "sub_component_requirements": ArtifactType.SUB_COMPONENT_REQUIREMENTS,
        "sub_component_architectures": ArtifactType.SUB_COMPONENT_ARCHITECTURE,
        "sub_component_plans": ArtifactType.SUB_COMPONENT_PLAN,
        "code_generation": ArtifactType.CODE,
        "code_review": ArtifactType.CODE_REVIEW,
    }
    return mapping.get(stage_key, ArtifactType.CODE)
