"""Artifact operation mixin for PipelineEngine.

Handles resume_stage, revise_artifact, resolve_stale, prune_artifact,
retry_stage, and the cascade/invalidate helpers triggered by approvals
and rejections.
"""

import logging
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
                        artifact.prev_git_commit_sha = artifact.git_commit_sha
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
                                execution.project_id,
                                evt.ARTIFACT_COMMITTED,
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
                            execution.project_id,
                            evt.COMMENT_ADDED,
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
                execution,
                StageStatus.APPROVED,
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
                execution,
                StageStatus.REJECTED,
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
                    execution.project_id,
                    evt.COMMENT_ADDED,
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

            # Rejection no longer auto-regenerates. Users can explicitly
            # regenerate via the separate "Regenerate" button (force restart).

        elif action == "save_feedback":
            logger.info(
                "Saving feedback for stage %s (execution=%s)", execution.stage_key, execution_id
            )
            if execution.artifact_id:
                artifact = self.db.get(Artifact, execution.artifact_id)
                if artifact:
                    if edited_content:
                        artifact.prev_git_commit_sha = artifact.git_commit_sha
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
                                execution.project_id,
                                evt.ARTIFACT_COMMITTED,
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
                            execution.project_id,
                            evt.COMMENT_ADDED,
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
        """Cascade-reject downstream AWAITING_REVIEW executions, mark their artifacts as stale.

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
                    exc,
                    StageStatus.REJECTED,
                )
                if exc.artifact_id:
                    art = self.db.get(Artifact, exc.artifact_id)
                    if art:
                        art.is_stale = True
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
        """After approving a regenerated stage, mark downstream artifacts as stale.

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
                    art = self.db.get(Artifact, exc.artifact_id)
                    if art:
                        art.is_stale = True
                    stale_artifact_ids.append(exc.artifact_id)

        self.db.flush()

        # Emit staleness_propagated event
        if stale_artifact_ids:
            self.events.emit(
                project_id,
                evt.STALENESS_PROPAGATED,
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
                StageExecution.status.in_(
                    [
                        StageStatus.RUNNING,
                        StageStatus.AI_REVIEW,
                        StageStatus.AWAITING_REVIEW,
                        StageStatus.PENDING,
                    ]
                ),
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
            execution.project_id,
            evt.RUN_COMPLETED,
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
            project_id,
            evt.RUN_CREATED,
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
            new_run.run_number,
            new_run.run_id,
            project_id,
        )
        return new_run.run_id, new_run

    async def _regenerate_stage(self, old_execution: StageExecution):
        """Re-run a rejected stage via RejectionRegenerateStrategy."""
        from backend.pipeline.stage_execution import (
            RejectionRegenerateStrategy,
            SkipExecution,
        )

        strategy = RejectionRegenerateStrategy(old_execution)
        try:
            await self.execute_strategy(strategy)
        except SkipExecution as e:
            logger.warning("Skipping regeneration: %s", e)

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
        allowed = (ArtifactStatus.AWAITING_REVIEW, ArtifactStatus.REJECTED)
        if not artifact.is_stale and artifact.status not in allowed:
            raise ValueError(
                f"Artifact is not stale, awaiting_review, or rejected"
                f" (status={artifact.status.value}, is_stale={artifact.is_stale})"
            )

        project_id = artifact.project_id

        if action == "save_feedback":
            if edited_content:
                artifact.prev_git_commit_sha = artifact.git_commit_sha
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
                        project_id,
                        evt.ARTIFACT_COMMITTED,
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
                    project_id,
                    evt.COMMENT_ADDED,
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
                artifact.prev_git_commit_sha = artifact.git_commit_sha
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
                        project_id,
                        evt.ARTIFACT_COMMITTED,
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
                    project_id,
                    evt.COMMENT_ADDED,
                    {
                        "artifact_id": artifact_id,
                        "comment_type": "feedback",
                        "artifact_version": artifact.version,
                    },
                )
            self._mark_artifact_status(artifact_id, ArtifactStatus.APPROVED)
            artifact.is_stale = False

            # Emit stale_resolved event
            self.events.emit(
                project_id,
                evt.STALE_RESOLVED,
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
                    execution,
                    StageStatus.APPROVED,
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
            feedback = notes.strip() if notes and notes.strip() else None
            await self.revise_artifact(
                artifact_id,
                feedback or "Regenerate this artifact.",
                user_id=user_id,
                fresh=feedback is None,
            )
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
        downstream_stage_keys = {s.stage_key for s in config.stages if s.order_index > source_order}

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
            project_id,
            evt.CASCADE_STARTED,
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

        enqueue(
            self.db,
            "start_pipeline",
            {
                "project_id": project_id,
                "pipeline_run_id": regen_run.id,
            },
        )

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
            project_id,
            evt.ARTIFACT_PRUNED,
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

    async def revise_artifact(
        self,
        artifact_id: str,
        feedback: str,
        user_id: str | None = None,
        fresh: bool = False,
    ):
        """Revise an approved/stale artifact via ArtifactRevisionStrategy.

        If *fresh* is True, omit the previous content from the prompt so the
        LLM generates from scratch using current inputs rather than doing a
        conservative revision of the old output.
        """
        from backend.pipeline.stage_execution import (
            ArtifactRevisionStrategy,
            SkipExecution,
        )

        strategy = ArtifactRevisionStrategy(artifact_id, feedback, user_id, fresh=fresh)
        try:
            await self.execute_strategy(strategy)
        except SkipExecution as e:
            logger.warning("Skipping revision: %s", e)

    async def retry_stage(self, execution: StageExecution):
        """Re-run a failed stage execution via ForceRestartStrategy.

        Creates a NEW execution record (rather than reusing the old one) so
        that each run gets its own execution and retry counts don't accumulate
        across runs.  The old execution stays in its terminal state.

        All setup logic (guard, run creation, input gathering) is in
        ForceRestartStrategy.prepare().  Lifecycle (event emission, error
        handling, run completion) is in _run_stage.
        """
        from backend.pipeline.stage_execution import ForceRestartStrategy, SkipExecution

        strategy = ForceRestartStrategy(execution)
        try:
            await self.execute_strategy(strategy)
        except SkipExecution as e:
            logger.warning("Skipping retry: %s", e)
