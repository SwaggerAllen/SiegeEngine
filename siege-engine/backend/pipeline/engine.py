"""
Pipeline engine that orchestrates stage execution.

Uses a "find next ready work" approach instead of linear stage iteration.
For fan-out stages, components are processed in dependency order — a component's
documents are only generated after all its upstream dependency components have
completed their full document cycle and received human approval.
"""

import logging
import uuid
from datetime import datetime

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

    def _get_config(self, project_id: str) -> PipelineConfig | None:
        """Return the PipelineConfig for a project, or None if missing."""
        return self.db.query(PipelineConfig).filter_by(project_id=project_id).first()

    def _mark_awaiting_review(self, execution: StageExecution, artifact_id: str | None) -> None:
        """Set execution and artifact status to AWAITING_REVIEW."""
        execution.status = StageStatus.AWAITING_REVIEW
        if artifact_id:
            artifact = self.db.get(Artifact, artifact_id)
            if artifact:
                artifact.status = ArtifactStatus.AWAITING_REVIEW

    def _mark_approved(self, execution: StageExecution, artifact_id: str | None) -> None:
        """Set execution and artifact status to APPROVED, record completion time."""
        execution.status = StageStatus.APPROVED
        execution.completed_at = datetime.utcnow()
        if artifact_id:
            artifact = self.db.get(Artifact, artifact_id)
            if artifact:
                artifact.status = ArtifactStatus.APPROVED

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

        carried = self._carry_over_approved(project_id, run_id)
        logger.info("Carried over %d approved executions into run %s", carried, run_id)

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

    def _carry_over_approved(self, project_id: str, new_run_id: str) -> int:
        """Carry over the most recent APPROVED execution for each (stage, component)
        across ALL previous runs.  Skips executions whose artifact is currently STALE.

        Returns the number of executions carried over.
        """
        from sqlalchemy import func

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

        self.db.commit()
        return carried

    def _should_pause(
        self,
        stage_def: StageDefinition,
        pipeline_run: PipelineRun | None,
    ) -> bool:
        """Determine if the pipeline should pause after executing this stage."""
        if not pipeline_run:
            # Legacy fallback — pause at every human-review stage
            return stage_def.human_review_enabled

        stop = pipeline_run.stop_point

        # Branching stages always pause if human review is on
        if stage_def.stage_key in BRANCHING_STAGES and pipeline_run.human_review:
            return True

        if stop == StopPoint.AFTER_ALL:
            return pipeline_run.human_review and stage_def.human_review_enabled

        elif stop == StopPoint.BEFORE_CODE:
            if stage_def.stage_key in ("code_generation", "code_review"):
                return True
            return pipeline_run.human_review and stage_def.human_review_enabled

        elif stop == StopPoint.AT_FAN_OUT:
            if stage_def.stage_key in BRANCHING_STAGES:
                return True
            return pipeline_run.human_review and stage_def.human_review_enabled

        elif stop == StopPoint.AFTER_TRIPLETS:
            triplet_ends = {"component_plans", "sub_component_plans"}
            if stage_def.stage_key in triplet_ends:
                return True
            if stage_def.stage_key in BRANCHING_STAGES:
                return True
            return pipeline_run.human_review and stage_def.human_review_enabled

        return False

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
        """
        stages = sorted(config.stages, key=lambda s: s.order_index)
        has_pending_work = False

        for stage_def in stages:
            # Check if stage is fully complete
            if self._stage_fully_complete(project_id, stage_def, run_id):
                continue

            # Check if any executions are still in-flight or awaiting review
            pending_count = (
                self.db.query(StageExecution)
                .filter_by(
                    project_id=project_id,
                    stage_key=stage_def.stage_key,
                    run_id=run_id,
                )
                .filter(
                    StageExecution.status.in_(
                        [
                            StageStatus.AWAITING_REVIEW,
                            StageStatus.RUNNING,
                            StageStatus.AI_REVIEW,
                        ]
                    )
                )
                .count()
            )
            if pending_count > 0:
                # Stage has pending work — note it but DON'T stop.
                # Continue scanning downstream stages for entities whose
                # dependencies are already met.
                has_pending_work = True
                logger.info(
                    "Stage %s has %d pending executions, scanning downstream",
                    stage_def.stage_key,
                    pending_count,
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
                    # Already has a non-rejected execution but stage not complete
                    # (could be failed) — skip to avoid re-running
                    has_pending_work = True
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
                if execution.status in (StageStatus.AWAITING_REVIEW, StageStatus.APPROVED):
                    if stage_def.stage_key not in BRANCHING_STAGES:
                        await self._post_generation_hook(project_id, stage_def, None, execution)

                # Check if pipeline should pause at this stage
                if execution.status == StageStatus.AWAITING_REVIEW:
                    has_pending_work = True
                    if self._should_pause(stage_def, pipeline_run):
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
                ready = self._get_ready_entities(project_id, stage_def, run_id)
                if not ready:
                    # No entities ready — check if any entities exist at all
                    all_entities = self._get_all_entities_for_stage(project_id, stage_def)
                    if not all_entities:
                        # No entities at all — skip this stage (e.g., no sub-components)
                        logger.info("No entities for stage %s, skipping", stage_def.stage_key)
                        continue
                    # Entities exist but none are ready — blocked on upstream deps.
                    # Continue scanning instead of stopping — downstream stages
                    # for already-approved entities may still be runnable.
                    has_pending_work = True
                    logger.info(
                        "Stage %s: entities exist but none ready, scanning downstream",
                        stage_def.stage_key,
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
                    if execution.status in (StageStatus.AWAITING_REVIEW, StageStatus.APPROVED):
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

                # Check if pipeline should pause at this stage
                if self._should_pause(stage_def, pipeline_run):
                    awaiting_review = (
                        self.db.query(StageExecution)
                        .filter_by(
                            project_id=project_id,
                            stage_key=stage_def.stage_key,
                            run_id=run_id,
                            status=StageStatus.AWAITING_REVIEW,
                        )
                        .count()
                    )
                    if awaiting_review > 0:
                        has_pending_work = True
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

        # If pending work exists, the pipeline isn't finished — just no new work to do
        if has_pending_work:
            return

        # If we get here, all stages are complete
        logger.info("Pipeline run_id=%s completed successfully", run_id)

        git_commit_sha = None
        if pipeline_run:
            pipeline_run.status = PipelineRunStatus.COMPLETED
            pipeline_run.completed_at = datetime.utcnow()
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

        try:
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
            )
            execution.artifact_id = artifact_id

            # AI Review
            if stage_def.ai_review_enabled:
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

                execution.status = StageStatus.AI_REVIEW
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

            should_await_review = stage_def.human_review_enabled and (
                not pipeline_run or pipeline_run.human_review
            )
            if should_await_review:
                self._mark_awaiting_review(execution, artifact_id)
            else:
                self._mark_approved(execution, artifact_id)

            self.db.commit()

            await ws_manager.broadcast(
                project_id,
                {
                    "type": "stage_awaiting_review" if should_await_review else "stage_completed",
                    "stage_key": stage_def.stage_key,
                    "component_key": component_key,
                    "artifact_id": artifact_id,
                },
            )

        except Exception as e:
            logger.exception(
                "Stage %s failed for component=%s: %s", stage_def.stage_key, component_key, e
            )
            execution.status = StageStatus.FAILED
            execution.error_message = str(e)
            execution.completed_at = datetime.utcnow()

            # Reset any artifact stuck in generating/ai_reviewing
            if execution.artifact_id:
                stuck_artifact = self.db.get(Artifact, execution.artifact_id)
                if stuck_artifact and stuck_artifact.status in (
                    ArtifactStatus.GENERATING,
                    ArtifactStatus.AI_REVIEWING,
                ):
                    stuck_artifact.status = ArtifactStatus.PENDING

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
        """If this stage has a rejected/stale artifact with feedback comments, return them.

        Checks both REJECTED (direct rejection) and STALE (cascade-rejected with
        saved feedback) artifacts so that saved feedback survives upstream rejections.
        """
        artifact_type_val = stage_def.output_artifact_type
        query = (
            self.db.query(Artifact)
            .filter_by(project_id=project_id)
            .filter(Artifact.status.in_([ArtifactStatus.REJECTED, ArtifactStatus.STALE]))
            .filter(Artifact.artifact_type == artifact_type_val)
        )
        if component_key:
            query = query.filter_by(component_key=component_key)
        artifact = query.first()
        if artifact:
            return self._get_feedback_notes(artifact.id)
        return None

    def _gather_inputs(
        self, project_id: str, stage_def: StageDefinition, component_key: str | None = None
    ) -> dict[str, str]:
        """Gather input artifact contents for a stage.

        For sub-component stages (component_key contains '.'), automatically
        resolves parent-level inputs by the parent key and sub-component-level
        inputs by the full key.
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
                    .filter(
                        Artifact.status.in_(
                            [
                                ArtifactStatus.APPROVED,
                                ArtifactStatus.AWAITING_REVIEW,
                            ]
                        )
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
                    .filter(
                        Artifact.status.in_(
                            [
                                ArtifactStatus.APPROVED,
                                ArtifactStatus.AWAITING_REVIEW,
                            ]
                        )
                    )
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
                        .filter(
                            Artifact.status.in_(
                                [
                                    ArtifactStatus.APPROVED,
                                    ArtifactStatus.AWAITING_REVIEW,
                                ]
                            )
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
                        .filter(
                            Artifact.status.in_(
                                [
                                    ArtifactStatus.APPROVED,
                                    ArtifactStatus.AWAITING_REVIEW,
                                ]
                            )
                        )
                        .first()
                    )
                    if dep_art and dep_art.content:
                        dep_parts.append(f"### {full_dep_key}\n\n{dep_art.content}")
                if dep_parts:
                    inputs["dependency_architectures"] = "\n\n---\n\n".join(dep_parts)

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
