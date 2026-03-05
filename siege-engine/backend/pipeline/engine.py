"""
Pipeline engine that orchestrates stage execution.

Instead of building a single LangGraph graph for the entire pipeline,
we use a simpler orchestration approach: iterate through stages in order,
run each one (with fan-out for component stages), and pause at review gates.

This is more maintainable and debuggable than a deeply nested LangGraph graph,
while still using LangGraph's LLM integration via langchain-anthropic.
"""

import logging
import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

from backend.models import (
    Artifact,
    ArtifactStatus,
    ArtifactType,
    ExecutionMode,
    FanOutStrategy,
    PipelineConfig,
    Project,
    StageDefinition,
    StageExecution,
    StageStatus,
)
from backend.pipeline.nodes.ai_review import ai_review
from backend.pipeline.nodes.extract_components import extract_components_robust
from backend.pipeline.nodes.generate import generate
from backend.websocket.manager import ws_manager


class PipelineEngine:
    def __init__(self, db: Session):
        self.db = db

    async def start_pipeline(
        self, project_id: str, execution_mode: ExecutionMode | None = None
    ) -> str:
        """Start a pipeline run. Returns run_id."""
        logger.info("start_pipeline called for project_id=%s, execution_mode=%s", project_id, execution_mode)

        project = self.db.get(Project, project_id)
        if not project or not project.pipeline_config:
            logger.error("Project or pipeline config not found for project_id=%s", project_id)
            raise ValueError("Project or pipeline config not found")

        config = project.pipeline_config
        if execution_mode:
            config.execution_mode = execution_mode
            self.db.flush()

        run_id = str(uuid.uuid4())
        stages = sorted(config.stages, key=lambda s: s.order_index)
        logger.info("Pipeline run_id=%s starting with %d stages: %s", run_id, len(stages), [s.stage_key for s in stages])
        components: list[dict] = []

        for stage_def in stages:
            logger.info("Processing stage: %s (order=%d, fan_out=%s)", stage_def.stage_key, stage_def.order_index, stage_def.fan_out_strategy.value)
            # Gather input artifacts
            input_artifacts = self._gather_inputs(project_id, stage_def)

            stage_failed = False

            if stage_def.fan_out_strategy == FanOutStrategy.COMPONENT:
                # Need components list
                if not components:
                    # Extract from system architecture
                    logger.info("Extracting components from system architecture for fan-out")
                    sys_arch = self._get_artifact_content(
                        project_id, ArtifactType.SYSTEM_ARCHITECTURE
                    )
                    if sys_arch:
                        components = await extract_components_robust(
                            sys_arch, config.default_model
                        )
                        logger.info("Extracted %d components: %s", len(components), [c.get("key", c) if isinstance(c, dict) else c for c in components])

                if not components:
                    logger.warning("No components found for fan-out stage %s", stage_def.stage_key)
                    await ws_manager.broadcast(project_id, {
                        "type": "stage_failed",
                        "stage_key": stage_def.stage_key,
                        "error": "No components found for fan-out",
                    })
                    stage_failed = True
                else:
                    # Fan out: run sequentially to avoid SQLAlchemy session conflicts
                    for comp in components:
                        comp_key = comp["key"] if isinstance(comp, dict) else comp
                        logger.info("Fan-out: running stage %s for component %s", stage_def.stage_key, comp_key)
                        rejected_notes = self._get_rejected_notes(project_id, stage_def, comp_key)
                        execution = StageExecution(
                            project_id=project_id,
                            stage_key=stage_def.stage_key,
                            component_key=comp_key,
                            status=StageStatus.RUNNING,
                            started_at=datetime.utcnow(),
                            run_id=run_id,
                        )
                        self.db.add(execution)
                        self.db.flush()

                        await self._run_stage(
                            project_id, stage_def, input_artifacts, comp_key, execution, run_id,
                            human_notes=rejected_notes,
                        )
                        if execution.status == StageStatus.FAILED:
                            stage_failed = True
                            break
            else:
                # Single artifact stage
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
                    project_id, stage_def, input_artifacts, None, execution, run_id,
                    human_notes=rejected_notes,
                )
                if execution.status == StageStatus.FAILED:
                    stage_failed = True

            # Stop the pipeline if a stage failed
            if stage_failed:
                logger.error("Pipeline stopped: stage %s failed", stage_def.stage_key)
                await ws_manager.broadcast(project_id, {
                    "type": "pipeline_completed",
                    "run_id": run_id,
                })
                return run_id

            # In gated mode, check if we need to pause for review
            if config.execution_mode == ExecutionMode.GATED:
                if stage_def.human_review_enabled:
                    # Check if any execution for this stage is awaiting review
                    awaiting = (
                        self.db.query(StageExecution)
                        .filter_by(
                            project_id=project_id,
                            stage_key=stage_def.stage_key,
                            run_id=run_id,
                            status=StageStatus.AWAITING_REVIEW,
                        )
                        .count()
                    )
                    logger.info("Gated mode: stage %s has %d executions awaiting review", stage_def.stage_key, awaiting)
                    if awaiting > 0:
                        # Pipeline pauses here. Will be resumed via resume_stage()
                        logger.info("Pipeline paused at stage %s for human review", stage_def.stage_key)
                        await ws_manager.broadcast(project_id, {
                            "type": "pipeline_paused",
                            "stage_key": stage_def.stage_key,
                            "run_id": run_id,
                            "message": f"Awaiting review for {stage_def.display_name}",
                        })
                        return run_id

        logger.info("Pipeline run_id=%s completed successfully", run_id)
        await ws_manager.broadcast(project_id, {
            "type": "pipeline_completed",
            "run_id": run_id,
        })
        return run_id

    async def resume_stage(
        self,
        execution_id: str,
        action: str,
        notes: str | None = None,
        edited_content: str | None = None,
    ):
        """Resume a paused stage after human review."""
        execution = self.db.get(StageExecution, execution_id)
        if not execution:
            raise ValueError("Execution not found")

        if action == "approved":
            # Mark artifact as approved
            if execution.artifact_id:
                artifact = self.db.get(Artifact, execution.artifact_id)
                if artifact:
                    if edited_content:
                        artifact.content = edited_content
                        artifact.version += 1
                    artifact.status = ArtifactStatus.APPROVED
                    artifact.human_review_notes = notes

            execution.status = StageStatus.APPROVED
            execution.completed_at = datetime.utcnow()
            self.db.commit()

            await ws_manager.broadcast(execution.project_id, {
                "type": "stage_completed",
                "stage_key": execution.stage_key,
                "component_key": execution.component_key,
                "status": action,
                "execution_id": execution_id,
            })

            # Check if all executions for this stage+run are resolved
            await self._check_and_continue(execution)

        elif action == "rejected":
            logger.info("Stage %s rejected (execution=%s), triggering regeneration",
                        execution.stage_key, execution_id)
            execution.status = StageStatus.REJECTED

            # Accumulate all prior review notes so the full history is
            # available to the next generation pass.
            accumulated_notes = notes
            if execution.artifact_id:
                artifact = self.db.get(Artifact, execution.artifact_id)
                if artifact:
                    artifact.status = ArtifactStatus.REJECTED
                    prior = artifact.human_review_notes
                    if prior and notes:
                        accumulated_notes = f"{prior}\n\n---\n\n{notes}"
                    elif prior:
                        accumulated_notes = prior
                    artifact.human_review_notes = accumulated_notes
            self.db.commit()

            await ws_manager.broadcast(execution.project_id, {
                "type": "stage_completed",
                "stage_key": execution.stage_key,
                "component_key": execution.component_key,
                "status": "rejected",
                "execution_id": execution_id,
            })

            # Re-run the stage with accumulated feedback
            await self._regenerate_stage(execution, accumulated_notes)

    async def _check_and_continue(self, execution: StageExecution):
        """Check if all executions for a stage are done, then continue pipeline."""
        pending = (
            self.db.query(StageExecution)
            .filter_by(
                project_id=execution.project_id,
                stage_key=execution.stage_key,
                run_id=execution.run_id,
            )
            .filter(StageExecution.status.in_([
                StageStatus.AWAITING_REVIEW,
                StageStatus.RUNNING,
                StageStatus.PENDING,
            ]))
            .count()
        )

        if pending == 0:
            # All executions for this stage are done, continue pipeline
            config = (
                self.db.query(PipelineConfig)
                .filter_by(project_id=execution.project_id)
                .first()
            )
            if not config:
                return

            stages = sorted(config.stages, key=lambda s: s.order_index)
            current_idx = next(
                (i for i, s in enumerate(stages) if s.stage_key == execution.stage_key),
                -1,
            )

            if current_idx < len(stages) - 1:
                # There are more stages - continue from next stage
                remaining_stages = stages[current_idx + 1:]
                await self._continue_pipeline(
                    execution.project_id, execution.run_id, remaining_stages, config
                )

    async def _regenerate_stage(
        self, old_execution: StageExecution, human_notes: str | None
    ):
        """Re-run a rejected stage with human feedback, then continue the pipeline."""
        project_id = old_execution.project_id
        config = (
            self.db.query(PipelineConfig)
            .filter_by(project_id=project_id)
            .first()
        )
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

        input_artifacts = self._gather_inputs(project_id, stage_def)

        # Create a new execution for the regeneration
        run_id = old_execution.run_id or str(uuid.uuid4())
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
        self.db.flush()

        logger.info("Regenerating stage %s (component=%s) with human feedback, new execution=%s",
                     old_execution.stage_key, old_execution.component_key, new_execution.id)

        await ws_manager.broadcast(project_id, {
            "type": "stage_progress",
            "stage_key": old_execution.stage_key,
            "component_key": old_execution.component_key,
            "step": "regenerating",
            "message": f"Regenerating {stage_def.display_name} with feedback...",
        })

        try:
            content, artifact_id = await generate(
                stage_def,
                input_artifacts,
                old_execution.component_key,
                self.db,
                human_notes=human_notes,
            )
            new_execution.artifact_id = artifact_id
            logger.info("Regeneration complete: artifact_id=%s, content length=%d",
                        artifact_id, len(content) if content else 0)

            # AI Review
            if stage_def.ai_review_enabled:
                await ws_manager.broadcast(project_id, {
                    "type": "stage_progress",
                    "stage_key": stage_def.stage_key,
                    "component_key": old_execution.component_key,
                    "step": "ai_reviewing",
                    "message": f"AI reviewing {stage_def.display_name}...",
                })
                new_execution.status = StageStatus.AI_REVIEW
                self.db.flush()

                feedback = await ai_review(
                    stage_def, content, input_artifacts,
                    review_prompt_overrides=config.review_prompt_overrides,
                )
                artifact = self.db.get(Artifact, artifact_id)
                if artifact:
                    artifact.ai_review_feedback = feedback
                    artifact.status = ArtifactStatus.AI_REVIEWING

            # Set to awaiting review (goes back to human review gate)
            if stage_def.human_review_enabled:
                new_execution.status = StageStatus.AWAITING_REVIEW
                artifact = self.db.get(Artifact, artifact_id)
                if artifact:
                    artifact.status = ArtifactStatus.AWAITING_REVIEW
            else:
                new_execution.status = StageStatus.APPROVED
                new_execution.completed_at = datetime.utcnow()
                artifact = self.db.get(Artifact, artifact_id)
                if artifact:
                    artifact.status = ArtifactStatus.APPROVED

            self.db.commit()

            await ws_manager.broadcast(project_id, {
                "type": "stage_awaiting_review"
                if stage_def.human_review_enabled
                else "stage_completed",
                "stage_key": stage_def.stage_key,
                "component_key": old_execution.component_key,
                "artifact_id": artifact_id,
            })

        except Exception as e:
            logger.exception("Regeneration failed for stage %s: %s", old_execution.stage_key, e)
            new_execution.status = StageStatus.FAILED
            new_execution.error_message = str(e)
            new_execution.completed_at = datetime.utcnow()
            self.db.commit()

            await ws_manager.broadcast(project_id, {
                "type": "stage_failed",
                "stage_key": old_execution.stage_key,
                "component_key": old_execution.component_key,
                "error": str(e),
            })

    async def revise_artifact(self, artifact_id: str, feedback: str):
        """Revise an approved/stale artifact using AI with human feedback."""
        artifact = self.db.get(Artifact, artifact_id)
        if not artifact:
            raise ValueError("Artifact not found")

        project_id = artifact.project_id
        config = (
            self.db.query(PipelineConfig)
            .filter_by(project_id=project_id)
            .first()
        )
        if not config:
            raise ValueError("Pipeline config not found")

        # Find the stage definition that produces this artifact type
        stage_def = next(
            (s for s in config.stages
             if s.output_artifact_type == artifact.artifact_type.value),
            None,
        )
        if not stage_def:
            raise ValueError(
                f"No stage definition for artifact type: {artifact.artifact_type.value}"
            )

        # Accumulate feedback with any prior notes
        prior = artifact.human_review_notes
        if prior and feedback:
            accumulated = f"{prior}\n\n---\n\n{feedback}"
        else:
            accumulated = feedback or prior

        # Mark artifact as generating
        artifact.status = ArtifactStatus.GENERATING
        artifact.human_review_notes = accumulated
        self.db.flush()

        input_artifacts = self._gather_inputs(project_id, stage_def)

        # Create a new execution
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
        self.db.flush()

        logger.info("Revising artifact %s (stage=%s, component=%s) with feedback",
                     artifact_id, stage_def.stage_key, artifact.component_key)

        await ws_manager.broadcast(project_id, {
            "type": "stage_started",
            "stage_key": stage_def.stage_key,
            "component_key": artifact.component_key,
        })

        try:
            content, new_artifact_id = await generate(
                stage_def,
                input_artifacts,
                artifact.component_key,
                self.db,
                human_notes=accumulated,
            )
            execution.artifact_id = new_artifact_id
            logger.info("Revision complete: artifact_id=%s, content length=%d",
                        new_artifact_id, len(content) if content else 0)

            # AI Review
            if stage_def.ai_review_enabled:
                await ws_manager.broadcast(project_id, {
                    "type": "stage_progress",
                    "stage_key": stage_def.stage_key,
                    "component_key": artifact.component_key,
                    "step": "ai_reviewing",
                    "message": f"AI reviewing {stage_def.display_name}...",
                })
                execution.status = StageStatus.AI_REVIEW
                self.db.flush()

                ai_feedback = await ai_review(
                    stage_def, content, input_artifacts,
                    review_prompt_overrides=config.review_prompt_overrides,
                )
                updated_artifact = self.db.get(Artifact, new_artifact_id)
                if updated_artifact:
                    updated_artifact.ai_review_feedback = ai_feedback
                    updated_artifact.status = ArtifactStatus.AI_REVIEWING

            # Always go back to awaiting review for revisions
            execution.status = StageStatus.AWAITING_REVIEW
            updated_artifact = self.db.get(Artifact, new_artifact_id)
            if updated_artifact:
                updated_artifact.status = ArtifactStatus.AWAITING_REVIEW

            self.db.commit()

            await ws_manager.broadcast(project_id, {
                "type": "stage_awaiting_review",
                "stage_key": stage_def.stage_key,
                "component_key": artifact.component_key,
                "artifact_id": new_artifact_id,
            })

        except Exception as e:
            logger.exception("Revision failed for artifact %s: %s", artifact_id, e)
            execution.status = StageStatus.FAILED
            execution.error_message = str(e)
            execution.completed_at = datetime.utcnow()
            # Restore artifact to approved so the user can try again
            artifact.status = ArtifactStatus.APPROVED
            self.db.commit()

            await ws_manager.broadcast(project_id, {
                "type": "stage_failed",
                "stage_key": stage_def.stage_key,
                "component_key": artifact.component_key,
                "error": str(e),
            })

    async def _continue_pipeline(
        self,
        project_id: str,
        run_id: str,
        remaining_stages: list[StageDefinition],
        config: PipelineConfig,
    ):
        """Continue pipeline execution from a specific stage."""
        components: list[dict] = []

        for stage_def in remaining_stages:
            input_artifacts = self._gather_inputs(project_id, stage_def)

            stage_failed = False

            if stage_def.fan_out_strategy == FanOutStrategy.COMPONENT:
                if not components:
                    sys_arch = self._get_artifact_content(
                        project_id, ArtifactType.SYSTEM_ARCHITECTURE
                    )
                    if sys_arch:
                        components = await extract_components_robust(
                            sys_arch, config.default_model
                        )

                if not components:
                    stage_failed = True
                else:
                    for comp in components:
                        comp_key = comp["key"] if isinstance(comp, dict) else comp
                        rejected_notes = self._get_rejected_notes(project_id, stage_def, comp_key)
                        execution = StageExecution(
                            project_id=project_id,
                            stage_key=stage_def.stage_key,
                            component_key=comp_key,
                            status=StageStatus.RUNNING,
                            started_at=datetime.utcnow(),
                            run_id=run_id,
                        )
                        self.db.add(execution)
                        self.db.flush()

                        await self._run_stage(
                            project_id, stage_def, input_artifacts, comp_key, execution, run_id,
                            human_notes=rejected_notes,
                        )
                        if execution.status == StageStatus.FAILED:
                            stage_failed = True
                            break
            else:
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
                    project_id, stage_def, input_artifacts, None, execution, run_id,
                    human_notes=rejected_notes,
                )
                if execution.status == StageStatus.FAILED:
                    stage_failed = True

            if stage_failed:
                logger.error("Pipeline stopped during continuation: stage %s failed", stage_def.stage_key)
                await ws_manager.broadcast(project_id, {
                    "type": "pipeline_completed",
                    "run_id": run_id,
                })
                return

            if config.execution_mode == ExecutionMode.GATED and stage_def.human_review_enabled:
                awaiting = (
                    self.db.query(StageExecution)
                    .filter_by(
                        project_id=project_id,
                        stage_key=stage_def.stage_key,
                        run_id=run_id,
                        status=StageStatus.AWAITING_REVIEW,
                    )
                    .count()
                )
                if awaiting > 0:
                    await ws_manager.broadcast(project_id, {
                        "type": "pipeline_paused",
                        "stage_key": stage_def.stage_key,
                        "run_id": run_id,
                    })
                    return

        await ws_manager.broadcast(project_id, {
            "type": "pipeline_completed",
            "run_id": run_id,
        })

    async def retry_stage(self, execution: StageExecution):
        """Re-run a failed stage execution."""
        project_id = execution.project_id
        config = (
            self.db.query(PipelineConfig)
            .filter_by(project_id=project_id)
            .first()
        )
        if not config:
            raise ValueError("Pipeline config not found")

        stage_def = next(
            (s for s in config.stages if s.stage_key == execution.stage_key),
            None,
        )
        if not stage_def:
            raise ValueError(f"Stage definition not found: {execution.stage_key}")

        input_artifacts = self._gather_inputs(project_id, stage_def)
        execution.status = StageStatus.RUNNING
        execution.error_message = None
        execution.retry_count = (execution.retry_count or 0) + 1
        self.db.flush()

        await self._run_stage(
            project_id, stage_def, input_artifacts, execution.component_key, execution,
            execution.run_id or str(uuid.uuid4()),
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
    ):
        """Run a single stage (generate → ai_review → set status)."""
        logger.info("_run_stage: stage=%s component=%s execution_id=%s human_notes=%s",
                     stage_def.stage_key, component_key, execution.id,
                     f"{len(human_notes)} chars" if human_notes else "None")
        logger.info("  input_artifacts keys: %s", list(input_artifacts.keys()))

        try:
            # Broadcast progress
            await ws_manager.broadcast(project_id, {
                "type": "stage_progress",
                "stage_key": stage_def.stage_key,
                "component_key": component_key,
                "step": "generating",
                "message": f"Generating {stage_def.display_name}...",
            })

            # Generate
            logger.info("  Calling generate() for stage=%s component=%s", stage_def.stage_key, component_key)
            content, artifact_id = await generate(
                stage_def, input_artifacts, component_key, self.db,
                human_notes=human_notes,
            )
            execution.artifact_id = artifact_id
            logger.info("  generate() returned artifact_id=%s, content length=%d", artifact_id, len(content) if content else 0)

            # AI Review
            if stage_def.ai_review_enabled:
                await ws_manager.broadcast(project_id, {
                    "type": "stage_progress",
                    "stage_key": stage_def.stage_key,
                    "component_key": component_key,
                    "step": "ai_reviewing",
                    "message": f"AI reviewing {stage_def.display_name}...",
                })

                execution.status = StageStatus.AI_REVIEW
                self.db.flush()

                feedback = await ai_review(
                    stage_def, content, input_artifacts,
                    review_prompt_overrides=stage_def.pipeline_config.review_prompt_overrides,
                )
                artifact = self.db.get(Artifact, artifact_id)
                if artifact:
                    artifact.ai_review_feedback = feedback
                    artifact.status = ArtifactStatus.AI_REVIEWING

            # Set to awaiting review
            logger.info("  Stage %s: human_review=%s ai_review=%s", stage_def.stage_key, stage_def.human_review_enabled, stage_def.ai_review_enabled)
            if stage_def.human_review_enabled:
                execution.status = StageStatus.AWAITING_REVIEW
                artifact = self.db.get(Artifact, artifact_id)
                if artifact:
                    artifact.status = ArtifactStatus.AWAITING_REVIEW
            else:
                execution.status = StageStatus.APPROVED
                execution.completed_at = datetime.utcnow()
                artifact = self.db.get(Artifact, artifact_id)
                if artifact:
                    artifact.status = ArtifactStatus.APPROVED

            self.db.commit()

            await ws_manager.broadcast(project_id, {
                "type": "stage_awaiting_review"
                if stage_def.human_review_enabled
                else "stage_completed",
                "stage_key": stage_def.stage_key,
                "component_key": component_key,
                "artifact_id": artifact_id,
            })

        except Exception as e:
            logger.exception("Stage %s failed for component=%s: %s", stage_def.stage_key, component_key, e)
            execution.status = StageStatus.FAILED
            execution.error_message = str(e)
            execution.completed_at = datetime.utcnow()
            self.db.commit()

            await ws_manager.broadcast(project_id, {
                "type": "stage_failed",
                "stage_key": stage_def.stage_key,
                "component_key": component_key,
                "error": str(e),
            })

    def _get_rejected_notes(
        self, project_id: str, stage_def: StageDefinition, component_key: str | None = None,
    ) -> str | None:
        """If this stage has a rejected artifact with human_review_notes, return them."""
        artifact_type_val = stage_def.output_artifact_type
        query = (
            self.db.query(Artifact)
            .filter_by(project_id=project_id, status=ArtifactStatus.REJECTED)
            .filter(Artifact.artifact_type == artifact_type_val)
        )
        if component_key:
            query = query.filter_by(component_key=component_key)
        artifact = query.first()
        if artifact and artifact.human_review_notes:
            logger.info("Found rejected artifact %s with review notes for stage %s",
                        artifact.id, stage_def.stage_key)
            return artifact.human_review_notes
        return None

    def _gather_inputs(
        self, project_id: str, stage_def: StageDefinition
    ) -> dict[str, str]:
        """Gather input artifact contents for a stage."""
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
        else:
            for stage_key in stage_def.input_stage_keys:
                artifact_type_val = _stage_key_to_artifact_type(stage_key)
                artifacts = (
                    self.db.query(Artifact)
                    .filter_by(project_id=project_id)
                    .filter(Artifact.artifact_type == artifact_type_val)
                    .filter(Artifact.status.in_([
                        ArtifactStatus.APPROVED,
                        ArtifactStatus.AWAITING_REVIEW,
                    ]))
                    .all()
                )
                if len(artifacts) == 1:
                    inputs[stage_key] = artifacts[0].content or ""
                elif len(artifacts) > 1:
                    # Multiple (fan-out results) - concatenate
                    combined = "\n\n---\n\n".join(
                        f"### {a.component_key or a.name}\n\n{a.content}"
                        for a in artifacts
                        if a.content
                    )
                    inputs[stage_key] = combined

        return inputs

    def _get_artifact_content(
        self, project_id: str, artifact_type: ArtifactType
    ) -> str | None:
        artifact = (
            self.db.query(Artifact)
            .filter_by(project_id=project_id, artifact_type=artifact_type)
            .first()
        )
        return artifact.content if artifact else None


def _stage_key_to_artifact_type(stage_key: str) -> ArtifactType:
    mapping = {
        "system_requirements": ArtifactType.SYSTEM_REQUIREMENTS,
        "component_requirements": ArtifactType.COMPONENT_REQUIREMENTS,
        "system_architecture": ArtifactType.SYSTEM_ARCHITECTURE,
        "component_architectures": ArtifactType.COMPONENT_ARCHITECTURE,
        "high_level_plan": ArtifactType.HIGH_LEVEL_PLAN,
        "component_plans": ArtifactType.COMPONENT_PLAN,
        "code_generation": ArtifactType.CODE,
        "code_review": ArtifactType.CODE_REVIEW,
    }
    return mapping.get(stage_key, ArtifactType.CODE)
