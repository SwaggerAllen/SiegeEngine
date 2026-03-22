"""Artifact operation mixin for PipelineEngine.

Handles resume_stage, revise_artifact, resolve_stale, prune_artifact,
retry_stage, and the cascade/invalidate helpers triggered by approvals
and rejections.
"""

import asyncio
import logging
import uuid
from datetime import datetime

from backend.models import (
    Artifact,
    ArtifactComment,
    ArtifactDependency,
    ArtifactStatus,
    PipelineConfig,
    PipelineRun,
    PipelineRunStatus,
    StageExecution,
    StageStatus,
    StopPoint,
)
from backend.pipeline import events as evt
from backend.pipeline.nodes.ai_review import ai_review
from backend.pipeline.nodes.generate import generate
from backend.websocket.manager import ws_manager

logger = logging.getLogger(__name__)


class ArtifactOpsMixin:
    """Mixin that handles artifact lifecycle operations."""

    async def resume_stage(
        self,
        execution_id: str,
        action: str,
        notes: str | None = None,
        edited_content: str | None = None,
        user_id: str | None = None,
    ):
        """Resume a paused stage after human review."""
        execution = self.db.get(StageExecution, execution_id)
        if not execution:
            raise ValueError("Execution not found")

        if action == "approved":
            if execution.artifact_id:
                artifact = self.db.get(Artifact, execution.artifact_id)
                if artifact:
                    if edited_content:
                        artifact.content = edited_content
                        artifact.version += 1

                        if artifact.file_path:
                            from backend.git_manager.service import git_manager
                            sha = git_manager.commit_artifact(
                                execution.project_id,
                                edited_content,
                                artifact.file_path,
                                f"Edit {artifact.name or artifact.file_path} v{artifact.version}",
                            )
                            artifact.git_commit_sha = sha
                            self.events.emit(
                                execution.project_id, evt.ARTIFACT_COMMITTED,
                                {
                                    "artifact_id": execution.artifact_id,
                                    "git_commit_sha": sha,
                                    "version": artifact.version,
                                    "artifact_type": artifact.artifact_type.value,
                                    "artifact_name": artifact.name,
                                    "scope": "content_edit",
                                },
                                run_id=execution.run_id,
                            )

                    if notes and notes.strip():
                        self.db.add(
                            ArtifactComment(
                                artifact_id=execution.artifact_id,
                                project_id=execution.project_id,
                                author_id=user_id,
                                content=notes.strip(),
                                comment_type="feedback",
                                artifact_version=artifact.version,
                            )
                        )
                        self.events.emit(
                            execution.project_id, evt.COMMENT_ADDED,
                            {
                                "artifact_id": execution.artifact_id,
                                "comment_type": "feedback",
                                "artifact_version": artifact.version,
                                "stage_key": execution.stage_key,
                                "component_key": execution.component_key,
                            },
                            run_id=execution.run_id,
                        )

            self._transition_execution(
                execution, StageStatus.APPROVED,
                artifact_status=ArtifactStatus.APPROVED,
                set_completed=True,
            )
            self.db.commit()

            await ws_manager.broadcast(
                execution.project_id,
                {
                    "type": "stage_completed",
                    "stage_key": execution.stage_key,
                    "component_key": execution.component_key,
                    "status": action,
                    "execution_id": execution_id,
                },
            )
            if notes and notes.strip() and execution.artifact_id:
                await ws_manager.broadcast(
                    execution.project_id,
                    {
                        "type": "comment_added",
                        "artifact_id": execution.artifact_id,
                    },
                )

            config = self._get_config(execution.project_id)
            if config:
                stage_def = next(
                    (s for s in config.stages if s.stage_key == execution.stage_key),
                    None,
                )
                if stage_def:
                    await self._post_generation_hook(
                        execution.project_id, stage_def, execution.component_key, execution
                    )

                    if (execution.retry_count or 0) > 0:
                        stale_ids = self._invalidate_stale_downstream(
                            execution.project_id,
                            execution.run_id,
                            stage_def.order_index,
                            config,
                        )
                        if stale_ids:
                            self.db.commit()
                            await ws_manager.broadcast(
                                execution.project_id,
                                {
                                    "type": "staleness_propagated",
                                    "stale_artifact_ids": stale_ids,
                                },
                            )

            # Approval is passive — it does NOT trigger run continuation.
            # Users must start a new run to generate downstream work.
            # But we DO need to complete the run if all stages are done
            # (e.g. a single-artifact regeneration run).
            await self._try_complete_run(execution)

        elif action == "rejected":
            logger.info(
                "Stage %s rejected (execution=%s), triggering regeneration",
                execution.stage_key,
                execution_id,
            )
            self._transition_execution(
                execution, StageStatus.REJECTED,
                artifact_status=ArtifactStatus.REJECTED,
            )

            # Also reject carried-over copies of this execution in other runs.
            # When a new pipeline run starts, _carry_over_approved duplicates
            # APPROVED executions into the new run.  If the user then rejects
            # the original, the copy stays APPROVED, causing the pipeline DAG
            # to show "approved" while the artifact is actually rejected.
            carried_copies = (
                self.db.query(StageExecution)
                .filter(
                    StageExecution.project_id == execution.project_id,
                    StageExecution.stage_key == execution.stage_key,
                    StageExecution.component_key == execution.component_key,
                    StageExecution.status == StageStatus.APPROVED,
                    StageExecution.id != execution.id,
                    StageExecution.artifact_id == execution.artifact_id,
                )
                .all()
            )
            for copy in carried_copies:
                self._transition_execution(copy, StageStatus.REJECTED)

            if notes and notes.strip() and execution.artifact_id:
                art = self.db.get(Artifact, execution.artifact_id)
                self.db.add(
                    ArtifactComment(
                        artifact_id=execution.artifact_id,
                        project_id=execution.project_id,
                        author_id=user_id,
                        content=notes.strip(),
                        comment_type="feedback",
                        artifact_version=art.version if art else None,
                    )
                )
                self.events.emit(
                    execution.project_id, evt.COMMENT_ADDED,
                    {
                        "artifact_id": execution.artifact_id,
                        "comment_type": "feedback",
                        "artifact_version": art.version if art else None,
                        "stage_key": execution.stage_key,
                        "component_key": execution.component_key,
                    },
                    run_id=execution.run_id,
                )

            config = self._get_config(execution.project_id)
            stale_artifact_ids = []
            if config:
                stage_def = next(
                    (s for s in config.stages if s.stage_key == execution.stage_key),
                    None,
                )
                if stage_def:
                    stale_artifact_ids = self._cascade_reject_downstream(
                        execution.project_id,
                        execution.run_id,
                        stage_def.order_index,
                        config,
                    )

            self.db.commit()

            await ws_manager.broadcast(
                execution.project_id,
                {
                    "type": "stage_completed",
                    "stage_key": execution.stage_key,
                    "component_key": execution.component_key,
                    "status": "rejected",
                    "execution_id": execution_id,
                    "artifact_id": execution.artifact_id,
                },
            )
            if notes and notes.strip() and execution.artifact_id:
                await ws_manager.broadcast(
                    execution.project_id,
                    {
                        "type": "comment_added",
                        "artifact_id": execution.artifact_id,
                    },
                )

            if stale_artifact_ids:
                await ws_manager.broadcast(
                    execution.project_id,
                    {
                        "type": "staleness_propagated",
                        "stale_artifact_ids": stale_artifact_ids,
                    },
                )

            await self._regenerate_stage(execution)

        elif action == "save_feedback":
            logger.info(
                "Saving feedback for stage %s (execution=%s)", execution.stage_key, execution_id
            )
            if execution.artifact_id:
                artifact = self.db.get(Artifact, execution.artifact_id)
                if artifact:
                    if edited_content:
                        artifact.content = edited_content
                        artifact.version += 1

                        if artifact.file_path:
                            from backend.git_manager.service import git_manager
                            sha = git_manager.commit_artifact(
                                execution.project_id,
                                edited_content,
                                artifact.file_path,
                                f"Edit {artifact.name or artifact.file_path} v{artifact.version}",
                            )
                            artifact.git_commit_sha = sha
                            self.events.emit(
                                execution.project_id, evt.ARTIFACT_COMMITTED,
                                {
                                    "artifact_id": execution.artifact_id,
                                    "git_commit_sha": sha,
                                    "version": artifact.version,
                                    "artifact_type": artifact.artifact_type.value,
                                    "artifact_name": artifact.name,
                                    "scope": "content_edit",
                                },
                                run_id=execution.run_id,
                            )

                    if notes and notes.strip():
                        self.db.add(
                            ArtifactComment(
                                artifact_id=execution.artifact_id,
                                project_id=execution.project_id,
                                author_id=user_id,
                                content=notes.strip(),
                                comment_type="feedback",
                                artifact_version=artifact.version,
                            )
                        )
                        self.events.emit(
                            execution.project_id, evt.COMMENT_ADDED,
                            {
                                "artifact_id": execution.artifact_id,
                                "comment_type": "feedback",
                                "artifact_version": artifact.version,
                                "stage_key": execution.stage_key,
                                "component_key": execution.component_key,
                            },
                            run_id=execution.run_id,
                        )
            self.db.commit()

            await ws_manager.broadcast(
                execution.project_id,
                {
                    "type": "feedback_saved",
                    "stage_key": execution.stage_key,
                    "component_key": execution.component_key,
                    "execution_id": execution_id,
                    "artifact_id": execution.artifact_id,
                },
            )
            # Also broadcast comment_added so CommentsPanel refreshes
            if notes and notes.strip() and execution.artifact_id:
                await ws_manager.broadcast(
                    execution.project_id,
                    {
                        "type": "comment_added",
                        "artifact_id": execution.artifact_id,
                    },
                )

    async def _check_and_continue(self, execution: StageExecution):
        """After approval, find and execute the next available work."""
        config = self._get_config(execution.project_id)
        if not config:
            return

        pipeline_run = self._lookup_pipeline_run(execution.run_id) if execution.run_id else None
        if not pipeline_run:
            logger.info(
                "No PipelineRun for run_id=%s (likely a revision), skipping continuation",
                execution.run_id,
            )
            return

        await self._find_and_execute_next(
            execution.project_id, execution.run_id, config, pipeline_run
        )

    def _cascade_reject_downstream(
        self,
        project_id: str,
        run_id: str,
        rejected_stage_order_index: int,
        config: PipelineConfig,
    ) -> list[str]:
        """Cascade-reject downstream AWAITING_REVIEW executions, mark their artifacts STALE.

        Returns list of stale artifact IDs for WS broadcast.
        """
        stages = sorted(config.stages, key=lambda s: s.order_index)
        stale_artifact_ids: list[str] = []

        for stage_def in stages:
            if stage_def.order_index <= rejected_stage_order_index:
                continue

            downstream_execs = (
                self.db.query(StageExecution)
                .filter_by(
                    project_id=project_id,
                    stage_key=stage_def.stage_key,
                    run_id=run_id,
                    status=StageStatus.AWAITING_REVIEW,
                )
                .all()
            )

            for exc in downstream_execs:
                logger.info(
                    "Cascade-rejecting downstream execution %s (stage=%s, component=%s)",
                    exc.id,
                    exc.stage_key,
                    exc.component_key,
                )
                self._transition_execution(
                    exc, StageStatus.REJECTED,
                    artifact_status=ArtifactStatus.STALE,
                )
                if exc.artifact_id:
                    stale_artifact_ids.append(exc.artifact_id)

        self.db.flush()
        return stale_artifact_ids

    def _invalidate_stale_downstream(
        self,
        project_id: str,
        run_id: str,
        approved_stage_order_index: int,
        config: PipelineConfig,
    ) -> list[str]:
        """After approving a regenerated stage, mark downstream artifacts as STALE.

        Executions are kept as APPROVED so that auto-generation does NOT
        re-trigger. The user must explicitly regenerate stale nodes.

        Returns list of stale artifact IDs for WS broadcast.
        """
        stages = sorted(config.stages, key=lambda s: s.order_index)
        stale_artifact_ids: list[str] = []

        for stage_def in stages:
            if stage_def.order_index <= approved_stage_order_index:
                continue

            downstream_execs = (
                self.db.query(StageExecution)
                .filter_by(
                    project_id=project_id,
                    stage_key=stage_def.stage_key,
                    run_id=run_id,
                    status=StageStatus.APPROVED,
                )
                .all()
            )

            for exc in downstream_execs:
                if exc.artifact_id:
                    logger.info(
                        "Marking downstream artifact %s as stale (stage=%s, component=%s)",
                        exc.artifact_id,
                        exc.stage_key,
                        exc.component_key,
                    )
                    self._mark_artifact_status(exc.artifact_id, ArtifactStatus.STALE)
                    stale_artifact_ids.append(exc.artifact_id)

        self.db.flush()

        # Emit staleness_propagated event
        if stale_artifact_ids:
            self.events.emit(
                project_id, evt.STALENESS_PROPAGATED,
                {"source_stage_order": approved_stage_order_index, "stale_ids": stale_artifact_ids},
            )

        return stale_artifact_ids

    async def _try_complete_run(self, execution: StageExecution):
        """Complete the pipeline run if all its executions are finished."""
        if not execution.run_id:
            return
        pipeline_run = self._lookup_pipeline_run(execution.run_id)
        if not pipeline_run or pipeline_run.status != PipelineRunStatus.RUNNING:
            return

        # Check if any executions in this run are still in-flight
        in_flight = (
            self.db.query(StageExecution)
            .filter(
                StageExecution.run_id == execution.run_id,
                StageExecution.status.in_([
                    StageStatus.RUNNING,
                    StageStatus.AI_REVIEW,
                    StageStatus.AWAITING_REVIEW,
                    StageStatus.PENDING,
                ]),
            )
            .count()
        )
        if in_flight > 0:
            return

        # Determine final status: FAILED if any execution failed, else COMPLETED
        has_failure = (
            self.db.query(StageExecution)
            .filter(
                StageExecution.run_id == execution.run_id,
                StageExecution.status == StageStatus.FAILED,
            )
            .count()
        ) > 0
        final_status = PipelineRunStatus.FAILED if has_failure else PipelineRunStatus.COMPLETED
        status_str = "failed" if has_failure else "completed"

        pipeline_run.status = final_status
        pipeline_run.completed_at = datetime.utcnow()

        # Emit event BEFORE commit so both are persisted atomically.
        # (Same pattern as the _run_stage fix — prevents projection drift
        # where the DB has a completed run but the event log doesn't.)
        self.events.emit(
            execution.project_id, evt.RUN_COMPLETED,
            {"run_id": execution.run_id, "status": status_str},
            run_id=execution.run_id,
        )
        self.db.commit()

        await ws_manager.broadcast(
            execution.project_id,
            {
                "type": "pipeline_completed",
                "run_id": execution.run_id,
            },
        )

    def _ensure_active_run(
        self, project_id: str, old_run_id: str | None
    ) -> tuple[str, PipelineRun | None]:
        """Return an active run for the given project, creating one if needed.

        If *old_run_id* refers to a RUNNING PipelineRun, reuse it.
        Otherwise create a new single-artifact run.  Returns (run_id, pipeline_run).
        """
        from sqlalchemy import func

        # Try to find the existing run
        if old_run_id:
            pipeline_run = self._lookup_pipeline_run(old_run_id)
            if pipeline_run and pipeline_run.status == PipelineRunStatus.RUNNING:
                return old_run_id, pipeline_run

        # Create a new single-artifact run for this regeneration
        max_num = (
            self.db.query(func.max(PipelineRun.run_number))
            .filter_by(project_id=project_id)
            .scalar()
        ) or 0

        new_run = PipelineRun(
            project_id=project_id,
            run_number=max_num + 1,
            stop_point=StopPoint.EVERY_ARTIFACT,
            ai_loops=1,
        )
        self.db.add(new_run)
        self.db.flush()

        self.events.emit(
            project_id, evt.RUN_CREATED,
            {
                "run_id": new_run.run_id,
                "run_number": new_run.run_number,
                "ai_loops": new_run.ai_loops,
                "stop_point": new_run.stop_point.value,
            },
            run_id=new_run.run_id,
        )

        logger.info(
            "Created regeneration run #%d (run_id=%s) for project %s",
            new_run.run_number, new_run.run_id, project_id,
        )
        return new_run.run_id, new_run

    async def _regenerate_stage(self, old_execution: StageExecution):
        """Re-run a rejected stage with human feedback from ArtifactComment records."""
        project_id = old_execution.project_id

        # Guard: skip if there's already a RUNNING execution for this stage.
        # This prevents duplicate regenerations from concurrent jobs (e.g.,
        # recover_stale_jobs re-queuing + user trigger, or rapid UI clicks).
        already_running = (
            self.db.query(StageExecution)
            .filter(
                StageExecution.project_id == project_id,
                StageExecution.stage_key == old_execution.stage_key,
                StageExecution.component_key == old_execution.component_key,
                StageExecution.status.in_([StageStatus.RUNNING, StageStatus.AI_REVIEW]),
            )
            .first()
        )
        if already_running:
            logger.warning(
                "Skipping regeneration for stage %s: execution %s is already running",
                old_execution.stage_key, already_running.id,
            )
            return

        config = self._get_config(project_id)
        if not config:
            logger.error("Cannot regenerate: pipeline config not found for project %s", project_id)
            return

        stage_def = next(
            (s for s in config.stages if s.stage_key == old_execution.stage_key),
            None,
        )
        if not stage_def:
            logger.error("Cannot regenerate: stage def not found for %s", old_execution.stage_key)
            return

        # Capture original artifact status BEFORE any mutations so we can
        # restore it on failure.
        original_artifact_status = None
        if old_execution.artifact_id:
            artifact = self.db.get(Artifact, old_execution.artifact_id)
            if artifact:
                original_artifact_status = artifact.status

        new_execution = None
        run_id = None

        try:
            input_artifacts = self._gather_inputs(
                project_id, stage_def, old_execution.component_key,
                include_stale=True,
            )

            # Ensure regeneration belongs to a run
            run_id, pipeline_run = self._ensure_active_run(
                project_id, old_execution.run_id
            )
            new_execution = StageExecution(
                project_id=project_id,
                stage_key=old_execution.stage_key,
                component_key=old_execution.component_key,
                status=StageStatus.RUNNING,
                started_at=datetime.utcnow(),
                run_id=run_id,
                retry_count=(old_execution.retry_count or 0) + 1,
                artifact_id=old_execution.artifact_id,
            )
            self.db.add(new_execution)
            # Flush to generate the execution ID before emitting the event.
            self.db.flush()

            if old_execution.artifact_id:
                self._mark_artifact_status(old_execution.artifact_id, ArtifactStatus.GENERATING)

            self.events.emit(
                project_id, evt.STAGE_STARTED,
                {
                    "execution_id": new_execution.id,
                    "stage_key": old_execution.stage_key,
                    "component_key": old_execution.component_key,
                    "artifact_id": new_execution.artifact_id,
                    "trigger": "rejection_regenerate",
                    "retry_count": new_execution.retry_count,
                },
                run_id=new_execution.run_id,
            )

            # Commit execution, artifact status, and STAGE_STARTED event
            # together so the snapshot and DB are always in sync.
            self.db.commit()

            logger.info(
                "Regenerating stage %s (component=%s) with human feedback, new execution=%s",
                old_execution.stage_key,
                old_execution.component_key,
                new_execution.id,
            )

            await ws_manager.broadcast(
                project_id,
                {
                    "type": "stage_started",
                    "stage_key": old_execution.stage_key,
                    "component_key": old_execution.component_key,
                },
            )

            feedback_notes = self._get_feedback_notes(old_execution.artifact_id)
            # Pass current content for incremental revision
            existing_content = None
            if old_execution.artifact_id:
                existing_artifact = self.db.get(Artifact, old_execution.artifact_id)
                if existing_artifact and existing_artifact.content:
                    existing_content = existing_artifact.content
            content, artifact_id = await generate(
                stage_def,
                input_artifacts,
                old_execution.component_key,
                self.db,
                human_notes=feedback_notes,
                current_content=existing_content,
                execution_id=new_execution.id,
            )
            new_execution.artifact_id = artifact_id

            regen_artifact = self.db.get(Artifact, artifact_id)
            if regen_artifact:
                divider = ArtifactComment(
                    artifact_id=artifact_id,
                    project_id=project_id,
                    author_id=None,
                    content=f"Artifact regenerated to v{regen_artifact.version}",
                    comment_type="system_event",
                    artifact_version=regen_artifact.version,
                )
                self.db.add(divider)

            if stage_def.ai_review_enabled:
                self.events.emit(
                    project_id, evt.GENERATION_PROGRESS,
                    {
                        "stage_key": stage_def.stage_key,
                        "component_key": old_execution.component_key,
                        "step": "ai_reviewing",
                    },
                    run_id=new_execution.run_id,
                )
                await ws_manager.broadcast(
                    project_id,
                    {
                        "type": "stage_progress",
                        "stage_key": stage_def.stage_key,
                        "component_key": old_execution.component_key,
                        "step": "ai_reviewing",
                        "message": f"AI reviewing {stage_def.display_name}...",
                    },
                )
                self._transition_execution(new_execution, StageStatus.AI_REVIEW)
                self.db.flush()

                feedback = await ai_review(
                    stage_def,
                    content,
                    input_artifacts,
                    review_prompt_overrides=config.review_prompt_overrides,
                )
                artifact = self.db.get(Artifact, artifact_id)
                if artifact:
                    artifact.ai_review_feedback = feedback
                    artifact.status = ArtifactStatus.AI_REVIEWING

            # All regenerated artifacts go to AWAITING_REVIEW
            self._transition_execution(
                new_execution, StageStatus.AWAITING_REVIEW,
                artifact_status=ArtifactStatus.AWAITING_REVIEW,
            )

            self.db.commit()

            await ws_manager.broadcast(
                project_id,
                {
                    "type": "stage_awaiting_review",
                    "stage_key": stage_def.stage_key,
                    "component_key": old_execution.component_key,
                    "artifact_id": artifact_id,
                },
            )

        except asyncio.CancelledError:
            logger.info(
                "Regeneration cancelled for stage %s (force-restart)",
                old_execution.stage_key,
            )
            if old_execution.artifact_id:
                stuck_artifact = self.db.get(Artifact, old_execution.artifact_id)
                if stuck_artifact and stuck_artifact.status in (
                    ArtifactStatus.GENERATING,
                    ArtifactStatus.AI_REVIEWING,
                ):
                    self._mark_artifact_status(
                        old_execution.artifact_id,
                        original_artifact_status or ArtifactStatus.REJECTED,
                    )

            if new_execution is not None:
                self._transition_execution(
                    new_execution, StageStatus.FAILED,
                    error_message="Cancelled by force-restart",
                    set_completed=True,
                )

            self.db.commit()

            # Complete the run if all executions are now terminal
            if new_execution is not None:
                await self._try_complete_run(new_execution)

            raise  # Let the worker loop see the CancelledError

        except Exception as e:
            logger.exception("Regeneration failed for stage %s: %s", old_execution.stage_key, e)
            # Restore old artifact from stuck generating/reviewing state
            if old_execution.artifact_id:
                stuck_artifact = self.db.get(Artifact, old_execution.artifact_id)
                if stuck_artifact and stuck_artifact.status in (
                    ArtifactStatus.GENERATING,
                    ArtifactStatus.AI_REVIEWING,
                ):
                    self._mark_artifact_status(
                        old_execution.artifact_id,
                        original_artifact_status or ArtifactStatus.REJECTED,
                    )

            if new_execution is not None:
                self._transition_execution(
                    new_execution, StageStatus.FAILED,
                    error_message=str(e),
                    set_completed=True,
                )

            self.db.commit()

            await ws_manager.broadcast(
                project_id,
                {
                    "type": "stage_failed",
                    "stage_key": old_execution.stage_key,
                    "component_key": old_execution.component_key,
                    "artifact_id": old_execution.artifact_id,
                    "artifact_status": "rejected",
                    "error": str(e),
                },
            )

            # Complete the run if all executions are now terminal
            if new_execution is not None:
                await self._try_complete_run(new_execution)

    async def resolve_stale(
        self,
        artifact_id: str,
        action: str,
        notes: str | None = None,
        edited_content: str | None = None,
        user_id: str | None = None,
    ):
        """Handle approve/reject/save_feedback for a stale or awaiting_review artifact.

        Input documents (project_doc) have no StageExecution and use this
        endpoint for direct artifact-based approval.
        """
        artifact = self.db.get(Artifact, artifact_id)
        if not artifact:
            raise ValueError("Artifact not found")
        if artifact.status not in (ArtifactStatus.STALE, ArtifactStatus.AWAITING_REVIEW):
            raise ValueError(
                f"Artifact is not stale or awaiting_review"
                f" (status={artifact.status.value})"
            )

        project_id = artifact.project_id

        if action == "save_feedback":
            if edited_content:
                artifact.content = edited_content
                artifact.version += 1

                if artifact.file_path:
                    from backend.git_manager.service import git_manager
                    sha = git_manager.commit_artifact(
                        project_id,
                        edited_content,
                        artifact.file_path,
                        f"Edit {artifact.name or artifact.file_path} v{artifact.version}",
                    )
                    artifact.git_commit_sha = sha
                    self.events.emit(
                        project_id, evt.ARTIFACT_COMMITTED,
                        {
                            "artifact_id": artifact_id,
                            "git_commit_sha": sha,
                            "version": artifact.version,
                            "artifact_type": artifact.artifact_type.value,
                            "artifact_name": artifact.name,
                            "scope": "content_edit",
                        },
                    )

            if notes and notes.strip():
                self.db.add(
                    ArtifactComment(
                        artifact_id=artifact_id,
                        project_id=project_id,
                        author_id=user_id,
                        content=notes.strip(),
                        comment_type="feedback",
                        artifact_version=artifact.version,
                    )
                )
                self.events.emit(
                    project_id, evt.COMMENT_ADDED,
                    {
                        "artifact_id": artifact_id,
                        "comment_type": "feedback",
                        "artifact_version": artifact.version,
                    },
                )
            self.db.commit()

            await ws_manager.broadcast(
                project_id,
                {
                    "type": "feedback_saved",
                    "stage_key": "",
                    "artifact_id": artifact_id,
                },
            )
            if notes and notes.strip():
                await ws_manager.broadcast(
                    project_id,
                    {
                        "type": "comment_added",
                        "artifact_id": artifact_id,
                    },
                )
            return

        if action == "approved":
            if edited_content:
                artifact.content = edited_content
                artifact.version += 1

                if artifact.file_path:
                    from backend.git_manager.service import git_manager
                    sha = git_manager.commit_artifact(
                        project_id,
                        edited_content,
                        artifact.file_path,
                        f"Edit {artifact.name or artifact.file_path} v{artifact.version}",
                    )
                    artifact.git_commit_sha = sha
                    self.events.emit(
                        project_id, evt.ARTIFACT_COMMITTED,
                        {
                            "artifact_id": artifact_id,
                            "git_commit_sha": sha,
                            "version": artifact.version,
                            "artifact_type": artifact.artifact_type.value,
                            "artifact_name": artifact.name,
                            "scope": "content_edit",
                        },
                    )

            if notes and notes.strip():
                self.db.add(
                    ArtifactComment(
                        artifact_id=artifact_id,
                        project_id=project_id,
                        author_id=user_id,
                        content=notes.strip(),
                        comment_type="feedback",
                        artifact_version=artifact.version,
                    )
                )
                self.events.emit(
                    project_id, evt.COMMENT_ADDED,
                    {
                        "artifact_id": artifact_id,
                        "comment_type": "feedback",
                        "artifact_version": artifact.version,
                    },
                )
            self._mark_artifact_status(artifact_id, ArtifactStatus.APPROVED)

            # Emit stale_resolved event
            self.events.emit(
                project_id, evt.STALE_RESOLVED,
                {
                    "artifact_id": artifact_id,
                    "action": "approved",
                    "stage_key": artifact.artifact_type.value,
                    "component_key": artifact.component_key,
                },
            )

            # Sync the owning execution to APPROVED so the DAG node status
            # matches the artifact badge (fixes rejected-execution / approved-
            # artifact mismatch).
            execution = (
                self.db.query(StageExecution)
                .filter_by(artifact_id=artifact_id)
                .order_by(StageExecution.started_at.desc())
                .first()
            )
            if execution and execution.status != StageStatus.APPROVED:
                self._transition_execution(
                    execution, StageStatus.APPROVED,
                    set_completed=True,
                )

            self.db.commit()

            if artifact.artifact_type.value == "component_map":
                self._store_components(project_id, artifact.content)
                self.db.commit()
            elif artifact.artifact_type.value == "sub_component_map" and artifact.component_key:
                self._store_sub_components(project_id, artifact.component_key, artifact.content)
                self.db.commit()

            await ws_manager.broadcast(
                project_id,
                {
                    "type": "stage_completed",
                    "stage_key": artifact.artifact_type.value,
                    "component_key": artifact.component_key,
                    "artifact_id": artifact_id,
                    "status": "approved",
                },
            )
            if notes and notes.strip():
                await ws_manager.broadcast(
                    project_id,
                    {
                        "type": "comment_added",
                        "artifact_id": artifact_id,
                    },
                )

            # Approval is passive — does not trigger run continuation.
            # But complete the run if all stages are done.
            if execution:
                await self._try_complete_run(execution)

            return

        if action == "rejected":
            feedback = notes.strip() if notes and notes.strip() else "Regenerate this artifact."
            await self.revise_artifact(artifact_id, feedback, user_id=user_id)
            return

        raise ValueError(f"Unknown action: {action}")

    async def regen_downstream(
        self,
        artifact_id: str,
    ):
        """Start a scoped run to regenerate already-generated downstream nodes.

        Creates a new PipelineRun scoped from the given artifact's stage,
        with regen_generated_only=True so only nodes that already have content
        are regenerated. The source artifact is NOT approved — use the separate
        approve action for that.
        """
        from sqlalchemy import func

        artifact = self.db.get(Artifact, artifact_id)
        if not artifact:
            raise ValueError("Artifact not found")

        project_id = artifact.project_id

        config = self._get_config(project_id)
        if not config:
            raise ValueError("Pipeline config not found")
        source_stage = next(
            (s for s in config.stages if s.output_artifact_type == artifact.artifact_type.value),
            None,
        )
        if not source_stage:
            raise ValueError(
                f"No stage definition for artifact type: {artifact.artifact_type.value}"
            )

        source_order = source_stage.order_index
        downstream_stage_keys = {
            s.stage_key for s in config.stages if s.order_index > source_order
        }

        if not downstream_stage_keys:
            logger.info("No downstream stages to regen for artifact %s", artifact_id)
            return

        max_num = (
            self.db.query(func.max(PipelineRun.run_number))
            .filter_by(project_id=project_id)
            .scalar()
        ) or 0
        regen_run = PipelineRun(
            project_id=project_id,
            run_number=max_num + 1,
            ai_loops=1,
            stop_point=StopPoint.BEFORE_CODE,
            start_stage_key=source_stage.stage_key,
            start_component_key=artifact.component_key,
            regen_generated_only=True,
        )
        self.db.add(regen_run)
        self.db.commit()

        # Carry over all approved executions from previous runs
        self._carry_over_approved(project_id, regen_run.run_id)

        # Delete carried-over executions for downstream stages (they need regen)
        (
            self.db.query(StageExecution)
            .filter(
                StageExecution.run_id == regen_run.run_id,
                StageExecution.stage_key.in_(downstream_stage_keys),
            )
            .delete(synchronize_session="fetch")
        )
        self.db.commit()

        # Find parent run for cascade relationship
        parent_execution = (
            self.db.query(StageExecution)
            .filter_by(artifact_id=artifact_id)
            .order_by(StageExecution.started_at.desc())
            .first()
        )
        parent_run_id = parent_execution.run_id if parent_execution else None

        # Emit event
        self.events.emit(
            project_id, evt.CASCADE_STARTED,
            {
                "run_id": regen_run.run_id,
                "source_artifact_id": artifact_id,
                "parent_run_id": parent_run_id,
            },
            run_id=regen_run.run_id,
        )

        await ws_manager.broadcast(
            project_id,
            {
                "type": "regen_downstream_started",
                "source_artifact_id": artifact_id,
                "run_id": regen_run.run_id,
            },
        )

        from backend.pipeline.queue import enqueue
        enqueue(self.db, "start_pipeline", {
            "project_id": project_id,
            "pipeline_run_id": regen_run.id,
        })

    def prune_artifact(self, project_id: str, artifact_id: str):
        """Remove an artifact and its associated records from the project.

        Deletes the artifact, its dependency edges, comments, and stage executions.
        Preserves the ComponentDefinition so the fanout parent still knows the
        entity exists and will regenerate it on the next pipeline run.
        Does NOT cascade to downstream artifacts (component plans, code, etc.).
        """
        artifact = self.db.get(Artifact, artifact_id)
        if not artifact:
            raise ValueError("Artifact not found")
        if artifact.project_id != project_id:
            raise ValueError("Artifact does not belong to this project")
        if artifact.status in (ArtifactStatus.GENERATING, ArtifactStatus.AI_REVIEWING):
            raise ValueError("Cannot prune an artifact that is currently being generated")

        component_key = artifact.component_key

        (
            self.db.query(ArtifactDependency)
            .filter(
                (ArtifactDependency.upstream_artifact_id == artifact_id)
                | (ArtifactDependency.downstream_artifact_id == artifact_id)
            )
            .delete(synchronize_session="fetch")
        )

        (
            self.db.query(ArtifactComment)
            .filter(ArtifactComment.artifact_id == artifact_id)
            .delete(synchronize_session="fetch")
        )

        # Delete stage executions — both those referencing this artifact directly
        # and orphaned retries for the same stage+component (artifact_id=NULL).
        stage_keys_for_artifact = {
            e.stage_key
            for e in self.db.query(StageExecution)
            .filter_by(project_id=project_id, artifact_id=artifact_id)
            .all()
        }
        if stage_keys_for_artifact:
            q = self.db.query(StageExecution).filter(
                StageExecution.project_id == project_id,
                StageExecution.stage_key.in_(stage_keys_for_artifact),
            )
            if component_key is not None:
                q = q.filter(StageExecution.component_key == component_key)
            else:
                q = q.filter(StageExecution.component_key.is_(None))
            q.delete(synchronize_session="fetch")
        # Safety net: also delete any remaining executions with matching artifact_id
        (
            self.db.query(StageExecution)
            .filter_by(project_id=project_id, artifact_id=artifact_id)
            .delete()
        )

        # NOTE: We intentionally do NOT delete the ComponentDefinition here.
        # Prune resets a node to "not yet generated" so the pipeline will
        # regenerate it on the next run.  To truly remove a component, edit
        # the parent fanout document instead.

        self.db.delete(artifact)
        self.db.commit()

        # Emit artifact_pruned event
        self.events.emit(
            project_id, evt.ARTIFACT_PRUNED,
            {
                "artifact_id": artifact_id,
                "stage_key": artifact.artifact_type.value,
                "component_key": component_key,
            },
        )

        logger.info(
            "Pruned artifact %s (component_key=%s) from project %s",
            artifact_id,
            component_key,
            project_id,
        )

    async def revise_artifact(self, artifact_id: str, feedback: str, user_id: str | None = None):
        """Revise an approved/stale artifact using AI with human feedback."""
        artifact = self.db.get(Artifact, artifact_id)
        if not artifact:
            raise ValueError("Artifact not found")

        # Guard: skip if there's already a RUNNING execution for this artifact.
        # Prevents duplicate revisions from rapid UI clicks.
        already_running = (
            self.db.query(StageExecution)
            .filter(
                StageExecution.artifact_id == artifact_id,
                StageExecution.status.in_([StageStatus.RUNNING, StageStatus.AI_REVIEW]),
            )
            .first()
        )
        if already_running:
            logger.warning(
                "Skipping revision for artifact %s: execution %s is already running",
                artifact_id, already_running.id,
            )
            return

        # Capture original status for error recovery
        original_artifact_status = artifact.status

        project_id = artifact.project_id
        config = self._get_config(project_id)
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

        if feedback and feedback.strip():
            self.db.add(
                ArtifactComment(
                    artifact_id=artifact_id,
                    project_id=project_id,
                    author_id=user_id,
                    content=feedback.strip(),
                    comment_type="feedback",
                    artifact_version=artifact.version,
                )
            )
            self.db.flush()

        accumulated = self._get_feedback_notes(artifact_id)

        self._mark_artifact_status(artifact_id, ArtifactStatus.GENERATING)
        self.db.flush()

        # Emit artifact_revised event
        self.events.emit(
            project_id, evt.ARTIFACT_REVISED,
            {
                "artifact_id": artifact_id,
                "stage_key": stage_def.stage_key,
                "component_key": artifact.component_key,
                "feedback": feedback,
            },
        )

        input_artifacts = self._gather_inputs(
            project_id, stage_def, artifact.component_key, include_stale=True,
        )

        run_id = str(uuid.uuid4())
        execution = StageExecution(
            project_id=project_id,
            stage_key=stage_def.stage_key,
            component_key=artifact.component_key,
            status=StageStatus.RUNNING,
            started_at=datetime.utcnow(),
            run_id=run_id,
            artifact_id=artifact_id,
        )
        self.db.add(execution)
        self.db.commit()

        logger.info(
            "Revising artifact %s (stage=%s, component=%s) with feedback",
            artifact_id,
            stage_def.stage_key,
            artifact.component_key,
        )

        self.events.emit(
            project_id, evt.STAGE_STARTED,
            {
                "execution_id": execution.id,
                "stage_key": stage_def.stage_key,
                "component_key": artifact.component_key,
                "artifact_id": artifact_id,
                "trigger": "revision",
                "retry_count": execution.retry_count,
                "artifact_type": artifact.artifact_type.value,
                "artifact_name": artifact.name,
                "version": artifact.version,
            },
            run_id=run_id,
        )

        await ws_manager.broadcast(
            project_id,
            {
                "type": "stage_started",
                "stage_key": stage_def.stage_key,
                "component_key": artifact.component_key,
            },
        )

        try:
            # Pass current content for incremental revision
            existing_content = artifact.content if artifact.content else None
            content, new_artifact_id = await generate(
                stage_def,
                input_artifacts,
                artifact.component_key,
                self.db,
                human_notes=accumulated,
                current_content=existing_content,
                execution_id=execution.id,
            )
            execution.artifact_id = new_artifact_id

            revised_artifact = self.db.get(Artifact, new_artifact_id)
            if revised_artifact:
                divider = ArtifactComment(
                    artifact_id=artifact_id,
                    project_id=project_id,
                    author_id=None,
                    content=f"Artifact revised to v{revised_artifact.version}",
                    comment_type="system_event",
                    artifact_version=revised_artifact.version,
                )
                self.db.add(divider)

            if stage_def.ai_review_enabled:
                self.events.emit(
                    project_id, evt.GENERATION_PROGRESS,
                    {
                        "stage_key": stage_def.stage_key,
                        "component_key": artifact.component_key,
                        "step": "ai_reviewing",
                    },
                    run_id=run_id,
                )
                await ws_manager.broadcast(
                    project_id,
                    {
                        "type": "stage_progress",
                        "stage_key": stage_def.stage_key,
                        "component_key": artifact.component_key,
                        "step": "ai_reviewing",
                        "message": f"AI reviewing {stage_def.display_name}...",
                    },
                )
                self._transition_execution(execution, StageStatus.AI_REVIEW)
                self.db.flush()

                ai_feedback = await ai_review(
                    stage_def,
                    content,
                    input_artifacts,
                    review_prompt_overrides=config.review_prompt_overrides,
                )
                updated_artifact = self.db.get(Artifact, new_artifact_id)
                if updated_artifact:
                    updated_artifact.ai_review_feedback = ai_feedback
                    updated_artifact.status = ArtifactStatus.AI_REVIEWING

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
                    "component_key": artifact.component_key,
                    "artifact_id": new_artifact_id,
                },
            )

        except Exception as e:
            logger.exception("Revision failed for artifact %s: %s", artifact_id, e)
            self._transition_execution(
                execution, StageStatus.FAILED,
                error_message=str(e),
                set_completed=True,
            )
            self._mark_artifact_status(
                artifact_id, original_artifact_status or ArtifactStatus.APPROVED,
            )
            self.db.commit()

            await ws_manager.broadcast(
                project_id,
                {
                    "type": "stage_failed",
                    "stage_key": stage_def.stage_key,
                    "component_key": artifact.component_key,
                    "artifact_id": artifact_id,
                    "artifact_status": (
                        original_artifact_status.value
                        if original_artifact_status
                        else "approved"
                    ),
                    "error": str(e),
                },
            )

        finally:
            # Signal the frontend that this single-artifact revision is done
            # so it clears is_running.
            await ws_manager.broadcast(
                project_id,
                {
                    "type": "pipeline_completed",
                    "run_id": run_id,
                },
            )

    async def retry_stage(self, execution: StageExecution):
        """Re-run a failed stage execution.

        Creates a NEW execution record (rather than reusing the old one) so
        that each run gets its own execution and retry counts don't accumulate
        across runs.  The old execution stays in its terminal state.
        """
        project_id = execution.project_id

        # Guard: skip if there's already a RUNNING execution for this stage.
        already_running = (
            self.db.query(StageExecution)
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
            logger.warning(
                "Skipping retry for stage %s: execution %s is already running",
                execution.stage_key, already_running.id,
            )
            return

        config = self._get_config(project_id)
        if not config:
            raise ValueError("Pipeline config not found")

        stage_def = next(
            (s for s in config.stages if s.stage_key == execution.stage_key),
            None,
        )
        if not stage_def:
            raise ValueError(f"Stage definition not found: {execution.stage_key}")

        # Ensure we have an active run — reuse an existing RUNNING run or
        # create a new single-artifact run so the execution is always tracked.
        run_id, pipeline_run = self._ensure_active_run(project_id, execution.run_id)

        if execution.artifact_id:
            artifact = self.db.get(Artifact, execution.artifact_id)
            if artifact and artifact.status != ArtifactStatus.PENDING:
                self._mark_artifact_status(execution.artifact_id, ArtifactStatus.PENDING)

        # Gather feedback notes and current content so the retry builds on
        # the previous version rather than generating from scratch.
        feedback_notes = (
            self._get_feedback_notes(execution.artifact_id)
            if execution.artifact_id
            else None
        )
        current_content = None
        if execution.artifact_id:
            existing_artifact = self.db.get(Artifact, execution.artifact_id)
            if existing_artifact and existing_artifact.content:
                current_content = existing_artifact.content

        # Create a NEW execution instead of reusing the old one.  This avoids
        # reusing the same execution across multiple runs (which caused
        # duplicate stage_started events and unbounded retry_count growth).
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
        self.db.add(new_execution)
        self.db.flush()

        input_artifacts = self._gather_inputs(project_id, stage_def, execution.component_key)

        await ws_manager.broadcast(
            project_id,
            {
                "type": "stage_started",
                "stage_key": execution.stage_key,
                "component_key": execution.component_key,
            },
        )

        # _run_stage emits the STAGE_STARTED event itself, so we don't call
        # _transition_execution here (which would emit a duplicate event).
        await self._run_stage(
            project_id,
            stage_def,
            input_artifacts,
            new_execution.component_key,
            new_execution,
            run_id,
            human_notes=feedback_notes,
            current_content=current_content,
            config=config,
            pipeline_run=pipeline_run,
            trigger="force_restart",
        )

        # Complete the run if the execution finished (success or failure).
        # Without this, the run stays stuck as RUNNING forever when the
        # stage fails — nobody else is watching for this run to finish.
        await self._try_complete_run(new_execution)
