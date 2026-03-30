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

from backend.git_manager.service import git_manager as _git_manager
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
from backend.pipeline import events as evt
from backend.pipeline.artifact_ops import ArtifactOpsMixin
from backend.pipeline.component_manager import ComponentManagerMixin
from backend.pipeline.event_store import EventStore
from backend.pipeline.nodes.ai_review import ai_review
from backend.pipeline.nodes.generate import generate
from backend.pipeline.readiness import (
    ReadinessMixin,
)
from backend.pipeline.stage_execution import (
    StageExecutionContext,
    StageExecutionStrategy,
)
from backend.websocket.manager import ws_manager

logger = logging.getLogger(__name__)


def _commit_review_to_git(project_id: str, artifact: "Artifact", feedback: dict):
    """Write AI review feedback as a markdown file in the project's git repo."""
    if not artifact.file_path or not feedback.get("document"):
        return
    review_path = f"reviews/{artifact.file_path}"
    quality = feedback.get("overall_quality", "?")
    recommendation = feedback.get("recommendation", "?")
    content = (
        f"---\nquality: {quality}\nrecommendation: {recommendation}\n---\n\n{feedback['document']}"
    )
    try:
        _git_manager.commit_artifact(
            project_id,
            content,
            review_path,
            f"AI review for {artifact.name} (quality: {quality}/10, {recommendation})",
        )
    except Exception:
        logger.exception("Failed to commit AI review to git for %s", artifact.name)


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
        """Transition execution status, emit event, then update DB as projection.

        Events are emitted FIRST so the snapshot (single source of truth) updates
        before DB models. DB writes are projections for query convenience.
        Does NOT broadcast websocket events — callers handle that themselves.
        """
        old_status = execution.status

        logger.debug(
            "Transition exec %s: %s -> %s (artifact: %s)",
            execution.id,
            old_status.value,
            new_status.value,
            artifact_status.value if artifact_status else "unchanged",
        )

        # 1. Emit event FIRST (updates snapshot via reducer)
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

        # 2. DB projections (not authoritative — snapshot is source of truth)
        execution.status = new_status
        if set_completed:
            execution.completed_at = datetime.utcnow()
        if error_message is not None:
            execution.error_message = error_message

        if artifact_status is not None and execution.artifact_id:
            artifact = self.db.get(Artifact, execution.artifact_id)
            if artifact:
                artifact.status = artifact_status

    def _mark_artifact_status(self, artifact_id: str, new_status: ArtifactStatus) -> None:
        """DB projection: update artifact status for query convenience.

        NOT authoritative — the snapshot (via events) is the source of truth.
        Callers must also emit the corresponding event that updates the snapshot.
        """
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
                project_id,
                evt.RUN_CREATED,
                {
                    "run_id": run_id,
                    "run_number": pipeline_run.run_number,
                    "ai_loops": pipeline_run.ai_loops,
                    "stop_point": (
                        pipeline_run.stop_point.value if pipeline_run.stop_point else "end_of_phase"
                    ),
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
            project_id,
            evt.RUN_CREATED,
            {
                "run_id": new_run_id,
                "run_number": pipeline_run.run_number,
                "ai_loops": pipeline_run.ai_loops,
                "stop_point": (
                    pipeline_run.stop_point.value if pipeline_run.stop_point else "end_of_phase"
                ),
                "start_stage_key": pipeline_run.start_stage_key,
                "start_component_key": pipeline_run.start_component_key,
            },
            run_id=new_run_id,
        )

        # Carry over all approved work (searches across all runs)
        carried = self._carry_over_approved(project_id, new_run_id)

        # Additionally carry over AWAITING_REVIEW executions from the previous run
        # Read stale artifact IDs from snapshot (source of truth)
        _snap = self.events.get_snapshot(project_id)
        _stale_dict = getattr(_snap, "artifact_stale", None) or {}
        stale_artifact_ids = {aid for aid, is_stale in _stale_dict.items() if is_stale}
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

        stage_def = next((s for s in config.stages if s.stage_key == stage_key), None)
        if not stage_def:
            raise ValueError(f"Stage definition not found: {stage_key}")

        # Reuse an existing RUNNING run or create a new one so the
        # execution is always associated with a proper PipelineRun.
        latest_run = (
            self.db.query(PipelineRun)
            .filter_by(project_id=project_id)
            .order_by(PipelineRun.run_number.desc())
            .first()
        )
        run_id, pipeline_run = self._ensure_active_run(
            project_id, latest_run.run_id if latest_run else None
        )

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
        """Trigger a single (non-fan-out) stage via ManualTriggerStrategy."""
        from backend.pipeline.stage_execution import ManualTriggerStrategy

        strategy = ManualTriggerStrategy(
            project_id=project_id,
            stage_def=stage_def,
            run_id=run_id,
            config=config,
            pipeline_run=pipeline_run,
            component_key=component_key,
        )
        execution = await self.execute_strategy(strategy)
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
        """Trigger a fan-out stage for ready entities (or a specific one).

        Creates a ManualTriggerStrategy per entity and calls
        execute_strategy for each.
        """
        from backend.pipeline.stage_execution import ManualTriggerStrategy, SkipExecution

        stage_key = stage_def.stage_key

        if component_key:
            entity_keys = [component_key]
        else:
            entity_keys = self._get_ready_entities(project_id, stage_def, run_id)
            if not entity_keys:
                all_entities = self._get_all_entities_for_stage(project_id, stage_def)
                if not all_entities:
                    raise ValueError(f"No entities found for fan-out stage {stage_key}")
                raise ValueError(
                    f"No entities are ready for stage {stage_key}. "
                    f"{len(all_entities)} entities exist but are blocked on "
                    f"upstream dependencies or already have non-rejected executions."
                )

        execution_ids = []
        for entity_key in entity_keys:
            strategy = ManualTriggerStrategy(
                project_id=project_id,
                stage_def=stage_def,
                run_id=run_id,
                config=config,
                pipeline_run=pipeline_run,
                component_key=entity_key,
            )
            try:
                execution = await self.execute_strategy(strategy)
            except SkipExecution:
                continue
            execution_ids.append(execution.id)

            if execution.status == StageStatus.FAILED:
                logger.error(
                    "Stopping trigger: entity %s failed",
                    entity_key,
                )
                break

        if not execution_ids:
            raise ValueError(f"All entities for stage {stage_key} are already running")

        return execution_ids

    def _carry_over_approved(self, project_id: str, new_run_id: str) -> int:
        """Carry over the most recent APPROVED execution for each (stage, component)
        across ALL previous runs.  Skips executions whose artifact is currently stale.

        Returns the number of executions carried over.
        """
        from sqlalchemy import func

        # Reconcile mismatches: if an artifact is APPROVED but its owning
        # execution is AWAITING_REVIEW or REJECTED, sync the execution so
        # it gets carried over instead of silently dropping it.
        #
        # Only reconcile executions that plausibly represent the current
        # state of the artifact (AWAITING_REVIEW, REJECTED).  Old FAILED
        # retries should NOT be promoted to APPROVED — they are genuinely
        # failed attempts and promoting them emits spurious events.
        mismatched = (
            self.db.query(StageExecution)
            .filter_by(project_id=project_id)
            .filter(StageExecution.run_id != new_run_id)
            .filter(StageExecution.artifact_id.isnot(None))
            .filter(
                StageExecution.status.in_(
                    [
                        StageStatus.AWAITING_REVIEW,
                        StageStatus.REJECTED,
                    ]
                )
            )
            .join(Artifact, StageExecution.artifact_id == Artifact.id)
            .filter(Artifact.status == ArtifactStatus.APPROVED)
            .all()
        )
        for ex in mismatched:
            logger.warning(
                "Reconciling status mismatch: execution %s (stage=%s, status=%s) "
                "has approved artifact %s — setting execution to APPROVED",
                ex.id,
                ex.stage_key,
                ex.status.value,
                ex.artifact_id,
            )
            self._transition_execution(
                ex,
                StageStatus.APPROVED,
                set_completed=not ex.completed_at,
            )
        if mismatched:
            self.db.flush()

        # Read stale artifact IDs from snapshot (source of truth)
        _snap = self.events.get_snapshot(project_id)
        _stale_dict2 = getattr(_snap, "artifact_stale", None) or {}
        stale_artifact_ids = {aid for aid, is_stale in _stale_dict2.items() if is_stale}

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
                project_id,
                evt.CARRIED_OVER,
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
            await self._post_generation_hook(project_id, stage_def, exec_.component_key, exec_)
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

        Uses a while loop to re-scan after each pass, so that generating one
        entity (e.g. component A's architecture) can unlock dependent entities
        (e.g. component B that depends on A) in the same run.

        Key behaviors:
        - Dependencies are satisfied by "generated" status (not just approved)
        - AWAITING_REVIEW nodes do NOT block downstream generation
        - Only RUNNING/AI_REVIEW states represent truly in-flight work
        - Run scope is filtered by start_stage_key/start_component_key
        - Stop point is checked BEFORE executing a stage, not after
        """
        stages = sorted(config.stages, key=lambda s: s.order_index)

        _pass_num = 0
        while True:
            _pass_num += 1
            did_work = False
            has_inflight_work = False
            hit_pause_boundary = False
            pause_stage_def = None

            logger.info(
                "[orchestrator] === Pass %d === run_id=%s start_stage=%s stop_point=%s",
                _pass_num,
                run_id,
                pipeline_run.start_stage_key if pipeline_run else None,
                pipeline_run.stop_point.value if pipeline_run and pipeline_run.stop_point else None,
            )

            for stage_def in stages:
                # Skip stages outside run scope
                if not self._is_in_run_scope(stage_def, None, pipeline_run):
                    continue

                # Check if stage is fully generated (has content for all entities)
                if self._stage_fully_generated(project_id, stage_def, run_id):
                    logger.info("Stage %s: fully generated, skipping", stage_def.stage_key)
                    continue

                # Check stop point BEFORE executing — prevents running stages
                # past the phase boundary (e.g. extract_sub_components when the
                # run should stop after component_architectures).
                should_pause = self._should_pause(stage_def, pipeline_run, project_id)
                if should_pause:
                    _start_order = (
                        self._get_start_order(pipeline_run, project_id) if pipeline_run else -1
                    )
                    _phase_complete = (
                        self._starting_phase_complete(pipeline_run, project_id)
                        if pipeline_run
                        else False
                    )
                    logger.info(
                        "[orchestrator] Stage %s (order=%d) past stop point — "
                        "start_order=%d, starting_phase_complete=%s, effective_order=%d",
                        stage_def.stage_key,
                        stage_def.order_index,
                        _start_order,
                        _phase_complete,
                        _start_order + (1 if _phase_complete else 0),
                    )
                    hit_pause_boundary = True
                    pause_stage_def = stage_def
                    break  # Don't look at later stages either

                logger.info(
                    "Stage %s: not fully generated (fan_out=%s), checking readiness",
                    stage_def.stage_key,
                    stage_def.fan_out_strategy.value if stage_def.fan_out_strategy else "none",
                )

                # Check if any executions are still truly in-flight (RUNNING/AI_REVIEW)
                # First check THIS run (for run-completion flow control)
                inflight_in_run = (
                    self.db.query(StageExecution)
                    .filter_by(
                        project_id=project_id,
                        stage_key=stage_def.stage_key,
                        run_id=run_id,
                    )
                    .filter(StageExecution.status.in_([StageStatus.RUNNING, StageStatus.AI_REVIEW]))
                    .count()
                )
                if inflight_in_run > 0:
                    has_inflight_work = True
                    logger.info(
                        "Stage %s has %d in-flight executions in this run, scanning downstream",
                        stage_def.stage_key,
                        inflight_in_run,
                    )
                    continue

                # Then check ALL runs to prevent duplicate cross-run executions.
                # A stage running in another run should not be started again here.
                inflight_anywhere = (
                    self.db.query(StageExecution)
                    .filter(
                        StageExecution.project_id == project_id,
                        StageExecution.stage_key == stage_def.stage_key,
                        StageExecution.status.in_([StageStatus.RUNNING, StageStatus.AI_REVIEW]),
                    )
                    .count()
                )
                if inflight_anywhere > 0:
                    logger.info(
                        "Stage %s has %d in-flight executions in other runs, "
                        "skipping to prevent duplicate generation",
                        stage_def.stage_key,
                        inflight_anywhere,
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

                    # Guard: skip if this stage is already running in ANY run
                    # (belt-and-suspenders with the stage-level check above)
                    already_running = (
                        self.db.query(StageExecution)
                        .filter(
                            StageExecution.project_id == project_id,
                            StageExecution.stage_key == stage_def.stage_key,
                            StageExecution.component_key.is_(None),
                            StageExecution.status.in_([StageStatus.RUNNING, StageStatus.AI_REVIEW]),
                        )
                        .first()
                    )
                    if already_running:
                        logger.info(
                            "Stage %s already running (execution %s), skipping",
                            stage_def.stage_key,
                            already_running.id,
                        )
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

                    ctx = StageExecutionContext(
                        project_id=project_id,
                        stage_def=stage_def,
                        config=config,
                        execution=execution,
                        run_id=run_id,
                        pipeline_run=pipeline_run,
                        input_artifacts=input_artifacts,
                        human_notes=rejected_notes,
                    )
                    await self._run_stage(ctx)
                    did_work = True

                    if execution.status == StageStatus.FAILED:
                        # Run completion is handled by _run_stage's finally block.
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

                elif fan_out in (
                    FanOutStrategy.COMPONENT,
                    FanOutStrategy.SUB_COMPONENT,
                    FanOutStrategy.LEAF,
                ):
                    all_entities_for_log = self._get_all_entities_for_stage(project_id, stage_def)
                    ready = self._get_ready_entities(
                        project_id, stage_def, run_id, pipeline_run=pipeline_run
                    )
                    logger.info(
                        "[orchestrator] Stage %s fan-out: %d total entities, %d ready: %s",
                        stage_def.stage_key,
                        len(all_entities_for_log),
                        len(ready),
                        ready[:10],
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
                        # Guard: skip if this entity is already running in ANY run
                        already_running = (
                            self.db.query(StageExecution)
                            .filter(
                                StageExecution.project_id == project_id,
                                StageExecution.stage_key == stage_def.stage_key,
                                StageExecution.component_key == entity_key,
                                StageExecution.status.in_(
                                    [StageStatus.RUNNING, StageStatus.AI_REVIEW]
                                ),
                            )
                            .first()
                        )
                        if already_running:
                            logger.info(
                                "Entity %s/%s already running (execution %s), skipping",
                                stage_def.stage_key,
                                entity_key,
                                already_running.id,
                            )
                            continue

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

                        ctx = StageExecutionContext(
                            project_id=project_id,
                            stage_def=stage_def,
                            config=config,
                            execution=execution,
                            run_id=run_id,
                            pipeline_run=pipeline_run,
                            input_artifacts=input_artifacts,
                            human_notes=rejected_notes,
                        )
                        await self._run_stage(ctx)
                        did_work = True

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
                        # Run completion is handled by _run_stage's finally block.
                        logger.error("Pipeline stopped: stage %s failed", stage_def.stage_key)
                        await ws_manager.broadcast(
                            project_id,
                            {
                                "type": "pipeline_completed",
                                "run_id": run_id,
                            },
                        )
                        return

            # --- End of stage scan ---

            logger.info(
                "[orchestrator] Pass %d result: did_work=%s, "
                "has_inflight=%s, hit_pause=%s (stage=%s)",
                _pass_num,
                did_work,
                has_inflight_work,
                hit_pause_boundary,
                pause_stage_def.stage_key if pause_stage_def else None,
            )

            # If we did work this pass, re-scan: generating entities may have
            # unlocked dependent entities (e.g. component B depends on A's
            # architecture, which was just generated).
            if did_work:
                logger.info("Work completed in this pass, re-scanning for newly-ready entities")
                continue

            # No new work was done.  Decide whether to pause or complete.
            if hit_pause_boundary:
                # All work before the stop point is done — emit pause.
                self.events.emit(
                    project_id,
                    evt.PIPELINE_PAUSED,
                    {"stage_key": pause_stage_def.stage_key, "run_id": run_id},
                    run_id=run_id,
                )
                await ws_manager.broadcast(
                    project_id,
                    {
                        "type": "pipeline_paused",
                        "stage_key": pause_stage_def.stage_key,
                        "run_id": run_id,
                        "message": f"Awaiting review for {pause_stage_def.display_name}",
                    },
                )
                return

            if has_inflight_work:
                # In-flight work exists but no new work to start — wait
                return

            # No more work anywhere — exit the while loop and complete
            break

        # --- All stages done, no inflight work, no pause boundary ---

        # If we get here, all stages are complete
        logger.info("Pipeline run_id=%s completed successfully", run_id)

        git_commit_sha = None
        if pipeline_run:
            pipeline_run.status = PipelineRunStatus.COMPLETED
            pipeline_run.completed_at = datetime.utcnow()

            # Emit event BEFORE commit so both are persisted atomically.
            self.events.emit(
                project_id,
                evt.RUN_COMPLETED,
                {"run_id": run_id, "status": "completed"},
                run_id=run_id,
            )
            self.db.commit()

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
                    project_id,
                    evt.ARTIFACT_COMMITTED,
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

    async def execute_strategy(
        self,
        strategy: "StageExecutionStrategy",
    ) -> StageExecution:
        """Execute a stage using the given strategy.

        The strategy handles preparation (creating execution, gathering
        inputs, etc.).  This method calls _run_stage which handles the
        shared lifecycle (event emission, generation, error handling,
        run completion).

        Raises SkipExecution if the strategy decides to skip (e.g.
        already-running guard).  Callers decide how to handle it:
        - Fan-out loops: catch and continue to next entity
        - Single triggers: let it propagate as an error
        """
        ctx = await strategy.prepare(self)

        await ws_manager.broadcast(
            ctx.project_id,
            {
                "type": "stage_started",
                "stage_key": ctx.stage_def.stage_key,
                "component_key": ctx.execution.component_key,
            },
        )

        await self._run_stage(ctx)
        return ctx.execution

    def _recover_artifact_on_error(self, ctx: "StageExecutionContext"):
        """Restore artifact status after a failed stage execution.

        Uses the context's error_artifact_status and original_artifact_id
        to determine what to restore.  Falls back to unsticking
        GENERATING/AI_REVIEWING → PENDING for first-generation stages.
        """
        fallback_status = ctx.error_artifact_status or ArtifactStatus.PENDING

        # Restore the original artifact if it's stuck in a transient state.
        target_id = ctx.original_artifact_id or (
            ctx.execution.artifact_id if ctx.execution else None
        )
        if target_id:
            stuck = self.db.get(Artifact, target_id)
            if stuck and stuck.status in (
                ArtifactStatus.GENERATING,
                ArtifactStatus.AI_REVIEWING,
            ):
                self._mark_artifact_status(target_id, fallback_status)

    async def _run_stage(
        self,
        ctx: "StageExecutionContext",
    ):
        """Run a single stage (generate -> ai_review -> set status).

        This is THE single path for all stage execution.  It handles:
        - STAGE_STARTED event emission
        - Generation + AI review
        - Error handling (STAGE_FAILED)
        - Run completion (_try_complete_run) in the finally block

        Callers provide a StageExecutionContext (built by a strategy or
        directly by the orchestrator).  Never call this without a context.
        """
        # Unpack context for readability within the method body.
        project_id = ctx.project_id
        stage_def = ctx.stage_def
        input_artifacts = ctx.input_artifacts
        component_key = ctx.execution.component_key
        execution = ctx.execution
        run_id = ctx.run_id
        human_notes = ctx.human_notes
        current_content = ctx.current_content
        pipeline_run = ctx.pipeline_run
        trigger = ctx.trigger

        logger.info(
            "_run_stage: stage=%s component=%s execution_id=%s human_notes=%s",
            stage_def.stage_key,
            component_key,
            execution.id,
            f"{len(human_notes)} chars" if human_notes else "None",
        )
        logger.info("  input_artifacts keys: %s", list(input_artifacts.keys()))

        # Stream backend logs to connected WebSocket clients
        from backend.websocket.log_handler import WebSocketLogHandler

        log_streamer = WebSocketLogHandler(project_id)
        log_streamer.install()

        # Emit stage_started event BEFORE committing so the event and the
        # RUNNING execution are persisted in the same transaction.  Previously
        # the commit came first, creating a window where the DB had a RUNNING
        # execution with no corresponding event (projection drift).
        self.events.emit(
            project_id,
            evt.STAGE_STARTED,
            {
                "execution_id": execution.id,
                "stage_key": stage_def.stage_key,
                "component_key": component_key,
                "artifact_id": execution.artifact_id,
                "trigger": trigger,
                "retry_count": execution.retry_count,
            },
            run_id=execution.run_id,
        )

        # Keep the DB artifact status in sync with the snapshot (which the
        # reducer just set to "generating").  Without this, a crash between
        # here and generate() leaves the DB stale.
        if execution.artifact_id:
            artifact = self.db.get(Artifact, execution.artifact_id)
            if artifact:
                artifact.status = ArtifactStatus.GENERATING

        # Commit the RUNNING execution + STAGE_STARTED event together so
        # other sessions (DAG endpoint) can see them atomically.
        self.db.commit()

        try:  # the finally below uninstalls log_streamer
            self.events.emit(
                project_id,
                evt.GENERATION_PROGRESS,
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

            # Record version comment (for regeneration/revision triggers)
            gen_artifact = self.db.get(Artifact, artifact_id)
            if ctx.version_comment and gen_artifact:
                from backend.models import ArtifactComment

                self.db.add(
                    ArtifactComment(
                        artifact_id=artifact_id,
                        project_id=project_id,
                        author_id=None,
                        content=f"{ctx.version_comment} to v{gen_artifact.version}",
                        comment_type="system_event",
                        artifact_version=gen_artifact.version,
                    )
                )

            # Record artifact git commit in event trail
            if gen_artifact and gen_artifact.git_commit_sha:
                self.events.emit(
                    project_id,
                    evt.ARTIFACT_COMMITTED,
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
                    project_id,
                    evt.GENERATION_PROGRESS,
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
                    execution,
                    StageStatus.AI_REVIEW,
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
                    _commit_review_to_git(project_id, artifact, feedback)

                # Self-improvement loops: refine with AI feedback
                ai_loops = pipeline_run.ai_loops if pipeline_run else 1
                if feedback and ai_loops > 1:
                    for loop_i in range(1, ai_loops):
                        self.events.emit(
                            project_id,
                            evt.GENERATION_PROGRESS,
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
                            _commit_review_to_git(project_id, artifact, feedback)

            # All generated artifacts go to AWAITING_REVIEW — only human
            # approval can move them to APPROVED.
            self._transition_execution(
                execution,
                StageStatus.AWAITING_REVIEW,
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
                "Stage %s cancelled for component=%s (force-restart)",
                stage_def.stage_key,
                component_key,
            )
            self._recover_artifact_on_error(ctx)
            self._transition_execution(
                execution,
                StageStatus.FAILED,
                error_message="Cancelled by force-restart",
                set_completed=True,
            )
            self.db.commit()
            raise  # Let the worker loop see the CancelledError

        except Exception as e:
            logger.exception(
                "Stage %s failed for component=%s: %s", stage_def.stage_key, component_key, e
            )
            self._recover_artifact_on_error(ctx)
            self._transition_execution(
                execution,
                StageStatus.FAILED,
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

        finally:
            log_streamer.uninstall()

            # Always attempt to complete the run after stage execution.
            # This is the single place that guarantees run completion
            # regardless of which code path called _run_stage (pipeline
            # start, force-restart, manual trigger, etc.).
            # _try_complete_run is a no-op if the run still has in-flight
            # work, so it's safe to call unconditionally.
            try:
                await self._try_complete_run(execution)
            except Exception:
                logger.exception(
                    "Failed to complete run after stage %s",
                    execution.stage_key,
                )

            # For standalone executions (no PipelineRun, e.g. revision),
            # broadcast pipeline_completed so the frontend clears is_running.
            if not ctx.pipeline_run:
                try:
                    await ws_manager.broadcast(
                        project_id,
                        {
                            "type": "pipeline_completed",
                            "run_id": run_id,
                        },
                    )
                except Exception:
                    pass

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
        self,
        project_id: str,
        stage_def: StageDefinition,
        component_key: str | None = None,
    ) -> dict[str, str]:
        """Gather input artifact contents for a stage.

        For sub-component stages (component_key contains '.'), automatically
        resolves parent-level inputs by the parent key and sub-component-level
        inputs by the full key.

        Always includes artifacts with content regardless of status — the most
        recent version of each input is used so that regeneration and revision
        flows never receive incomplete context.
        """

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
            inputs = self._inject_input_documents(project_id, "feature_expansion", inputs)
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
                    .first()
                )
                if artifact and artifact.content:
                    inputs[stage_key] = artifact.content
            else:
                # Project-level or aggregated input
                artifacts = (
                    self.db.query(Artifact)
                    .filter_by(project_id=project_id, artifact_type=artifact_type)
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

        docs = self.db.query(InputDocument).filter_by(project_id=project_id).all()
        matching = [d for d in docs if stage_key in (d.inject_into_stages or [])]
        if matching:
            doc_parts = [f"### {d.name} ({d.doc_type})\n\n{d.content}" for d in matching]
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
        "feature_expansion": ArtifactType.FEATURE_EXPANSION,
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
