"""Artifact operation mixin for PipelineEngine.

Handles resume_stage, revise_artifact, resolve_stale, prune_artifact,
retry_stage, and the cascade/invalidate helpers triggered by approvals
and rejections.
"""

import logging
import uuid
from datetime import datetime

from backend.models import (
    Artifact,
    ArtifactComment,
    ArtifactDependency,
    ArtifactStatus,
    ComponentDefinition,
    PipelineConfig,
    StageExecution,
    StageStatus,
)
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
                    artifact.status = ArtifactStatus.APPROVED

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

            execution.status = StageStatus.APPROVED
            execution.completed_at = datetime.utcnow()
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

            await self._check_and_continue(execution)

        elif action == "rejected":
            logger.info(
                "Stage %s rejected (execution=%s), triggering regeneration",
                execution.stage_key,
                execution_id,
            )
            execution.status = StageStatus.REJECTED

            if execution.artifact_id:
                artifact = self.db.get(Artifact, execution.artifact_id)
                if artifact:
                    artifact.status = ArtifactStatus.REJECTED

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
                copy.status = StageStatus.REJECTED

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
                exc.status = StageStatus.REJECTED

                if exc.artifact_id:
                    artifact = self.db.get(Artifact, exc.artifact_id)
                    if artifact:
                        artifact.status = ArtifactStatus.STALE
                        stale_artifact_ids.append(artifact.id)

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
                    artifact = self.db.get(Artifact, exc.artifact_id)
                    if artifact:
                        logger.info(
                            "Marking downstream artifact %s as stale (stage=%s, component=%s)",
                            artifact.id,
                            exc.stage_key,
                            exc.component_key,
                        )
                        artifact.status = ArtifactStatus.STALE
                        stale_artifact_ids.append(artifact.id)

        self.db.flush()
        return stale_artifact_ids

    async def _regenerate_stage(self, old_execution: StageExecution):
        """Re-run a rejected stage with human feedback from ArtifactComment records."""
        project_id = old_execution.project_id
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

        input_artifacts = self._gather_inputs(project_id, stage_def, old_execution.component_key)

        original_artifact_status = None
        if old_execution.artifact_id:
            artifact = self.db.get(Artifact, old_execution.artifact_id)
            if artifact:
                original_artifact_status = artifact.status
                artifact.status = ArtifactStatus.GENERATING

        run_id = old_execution.run_id or str(uuid.uuid4())
        pipeline_run = self._lookup_pipeline_run(run_id) if run_id else None
        new_execution = StageExecution(
            project_id=project_id,
            stage_key=old_execution.stage_key,
            component_key=old_execution.component_key,
            status=StageStatus.RUNNING,
            started_at=datetime.utcnow(),
            run_id=run_id,
            retry_count=(old_execution.retry_count or 0) + 1,
        )
        self.db.add(new_execution)
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

        try:
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
                new_execution.status = StageStatus.AI_REVIEW
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

            should_await_review = stage_def.human_review_enabled and (
                not pipeline_run or pipeline_run.human_review
            )
            if should_await_review:
                self._mark_awaiting_review(new_execution, artifact_id)
            else:
                self._mark_approved(new_execution, artifact_id)

            self.db.commit()

            await ws_manager.broadcast(
                project_id,
                {
                    "type": "stage_awaiting_review" if should_await_review else "stage_completed",
                    "stage_key": stage_def.stage_key,
                    "component_key": old_execution.component_key,
                    "artifact_id": artifact_id,
                },
            )

        except Exception as e:
            logger.exception("Regeneration failed for stage %s: %s", old_execution.stage_key, e)
            new_execution.status = StageStatus.FAILED
            new_execution.error_message = str(e)
            new_execution.completed_at = datetime.utcnow()

            if old_execution.artifact_id:
                stuck_artifact = self.db.get(Artifact, old_execution.artifact_id)
                if stuck_artifact and stuck_artifact.status in (
                    ArtifactStatus.GENERATING,
                    ArtifactStatus.AI_REVIEWING,
                ):
                    stuck_artifact.status = original_artifact_status or ArtifactStatus.REJECTED

            self.db.commit()

            await ws_manager.broadcast(
                project_id,
                {
                    "type": "stage_failed",
                    "stage_key": old_execution.stage_key,
                    "component_key": old_execution.component_key,
                    "error": str(e),
                },
            )

    async def resolve_stale(
        self,
        artifact_id: str,
        action: str,
        notes: str | None = None,
        edited_content: str | None = None,
        user_id: str | None = None,
    ):
        """Handle approve/reject/save_feedback for a stale artifact."""
        artifact = self.db.get(Artifact, artifact_id)
        if not artifact:
            raise ValueError("Artifact not found")
        if artifact.status != ArtifactStatus.STALE:
            raise ValueError(f"Artifact is not stale (status={artifact.status.value})")

        project_id = artifact.project_id

        if action == "save_feedback":
            if edited_content:
                artifact.content = edited_content
                artifact.version += 1
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
            self.db.commit()
            return

        if action == "approved":
            if edited_content:
                artifact.content = edited_content
                artifact.version += 1
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
            artifact.status = ArtifactStatus.APPROVED
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
            return

        if action == "rejected":
            feedback = notes.strip() if notes and notes.strip() else "Regenerate this artifact."
            await self.revise_artifact(artifact_id, feedback, user_id=user_id)
            return

        raise ValueError(f"Unknown action: {action}")

    def prune_artifact(self, project_id: str, artifact_id: str):
        """Remove an artifact and its associated records from the project.

        Deletes the artifact, its dependency edges, comments, and stage executions.
        If the artifact has a component_key, also removes the ComponentDefinition.
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

        (
            self.db.query(StageExecution)
            .filter_by(project_id=project_id, artifact_id=artifact_id)
            .delete()
        )

        if component_key:
            (
                self.db.query(ComponentDefinition)
                .filter_by(project_id=project_id, key=component_key, parent_key=None)
                .delete()
            )

        self.db.delete(artifact)
        self.db.commit()

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

        artifact.status = ArtifactStatus.GENERATING
        self.db.flush()

        input_artifacts = self._gather_inputs(project_id, stage_def, artifact.component_key)

        run_id = str(uuid.uuid4())
        execution = StageExecution(
            project_id=project_id,
            stage_key=stage_def.stage_key,
            component_key=artifact.component_key,
            status=StageStatus.RUNNING,
            started_at=datetime.utcnow(),
            run_id=run_id,
        )
        self.db.add(execution)
        self.db.commit()

        logger.info(
            "Revising artifact %s (stage=%s, component=%s) with feedback",
            artifact_id,
            stage_def.stage_key,
            artifact.component_key,
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
                execution.status = StageStatus.AI_REVIEW
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

            self._mark_awaiting_review(execution, new_artifact_id)

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
            execution.status = StageStatus.FAILED
            execution.error_message = str(e)
            execution.completed_at = datetime.utcnow()
            artifact.status = ArtifactStatus.APPROVED
            self.db.commit()

            await ws_manager.broadcast(
                project_id,
                {
                    "type": "stage_failed",
                    "stage_key": stage_def.stage_key,
                    "component_key": artifact.component_key,
                    "error": str(e),
                },
            )

    async def retry_stage(self, execution: StageExecution):
        """Re-run a failed stage execution."""
        project_id = execution.project_id
        config = self._get_config(project_id)
        if not config:
            raise ValueError("Pipeline config not found")

        stage_def = next(
            (s for s in config.stages if s.stage_key == execution.stage_key),
            None,
        )
        if not stage_def:
            raise ValueError(f"Stage definition not found: {execution.stage_key}")

        pipeline_run = self._lookup_pipeline_run(execution.run_id) if execution.run_id else None

        if execution.artifact_id:
            artifact = self.db.get(Artifact, execution.artifact_id)
            if artifact and artifact.status in (
                ArtifactStatus.GENERATING,
                ArtifactStatus.AI_REVIEWING,
                ArtifactStatus.REJECTED,
            ):
                artifact.status = ArtifactStatus.PENDING

        # Gather feedback notes and current content so the retry builds on
        # the previous version rather than generating from scratch.
        feedback_notes = self._get_feedback_notes(execution.artifact_id) if execution.artifact_id else None
        current_content = None
        if execution.artifact_id:
            existing_artifact = self.db.get(Artifact, execution.artifact_id)
            if existing_artifact and existing_artifact.content:
                current_content = existing_artifact.content

        input_artifacts = self._gather_inputs(project_id, stage_def, execution.component_key)
        execution.status = StageStatus.RUNNING
        execution.error_message = None
        execution.retry_count = (execution.retry_count or 0) + 1
        self.db.flush()

        await self._run_stage(
            project_id,
            stage_def,
            input_artifacts,
            execution.component_key,
            execution,
            execution.run_id or str(uuid.uuid4()),
            human_notes=feedback_notes,
            current_content=current_content,
            config=config,
            pipeline_run=pipeline_run,
        )
