"""
Pipeline engine that orchestrates stage execution.

Instead of building a single LangGraph graph for the entire pipeline,
we use a simpler orchestration approach: iterate through stages in order,
run each one (with fan-out for component stages), and pause at review gates.

This is more maintainable and debuggable than a deeply nested LangGraph graph,
while still using LangGraph's LLM integration via langchain-anthropic.
"""

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

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
        project = self.db.get(Project, project_id)
        if not project or not project.pipeline_config:
            raise ValueError("Project or pipeline config not found")

        config = project.pipeline_config
        if execution_mode:
            config.execution_mode = execution_mode
            self.db.flush()

        run_id = str(uuid.uuid4())
        stages = sorted(config.stages, key=lambda s: s.order_index)
        components: list[dict] = []

        for stage_def in stages:
            # Gather input artifacts
            input_artifacts = self._gather_inputs(project_id, stage_def)

            if stage_def.fan_out_strategy == FanOutStrategy.COMPONENT:
                # Need components list
                if not components:
                    # Extract from system architecture
                    sys_arch = self._get_artifact_content(
                        project_id, ArtifactType.SYSTEM_ARCHITECTURE
                    )
                    if sys_arch:
                        components = await extract_components_robust(
                            sys_arch, config.default_model
                        )

                if not components:
                    await ws_manager.broadcast(project_id, {
                        "type": "stage_failed",
                        "stage_key": stage_def.stage_key,
                        "error": "No components found for fan-out",
                    })
                    continue

                # Fan out: run sequentially to avoid SQLAlchemy session conflicts
                for comp in components:
                    comp_key = comp["key"] if isinstance(comp, dict) else comp
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
                        stage_def, input_artifacts, comp_key, execution, run_id
                    )
            else:
                # Single artifact stage
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
                    stage_def, input_artifacts, None, execution, run_id
                )

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
                    if awaiting > 0:
                        # Pipeline pauses here. Will be resumed via resume_stage()
                        await ws_manager.broadcast(project_id, {
                            "type": "pipeline_paused",
                            "stage_key": stage_def.stage_key,
                            "run_id": run_id,
                            "message": f"Awaiting review for {stage_def.display_name}",
                        })
                        return run_id

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

        elif action == "rejected":
            execution.status = StageStatus.REJECTED
            if execution.artifact_id:
                artifact = self.db.get(Artifact, execution.artifact_id)
                if artifact:
                    artifact.status = ArtifactStatus.REJECTED
                    artifact.human_review_notes = notes

        self.db.commit()

        await ws_manager.broadcast(execution.project_id, {
            "type": "stage_completed",
            "stage_key": execution.stage_key,
            "component_key": execution.component_key,
            "status": action,
            "execution_id": execution_id,
        })

        # Check if all executions for this stage+run are resolved
        if action == "approved":
            await self._check_and_continue(execution)

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
                    continue

                for comp in components:
                    comp_key = comp["key"] if isinstance(comp, dict) else comp
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
                        stage_def, input_artifacts, comp_key, execution, run_id
                    )
            else:
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
                    stage_def, input_artifacts, None, execution, run_id
                )

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
            stage_def, input_artifacts, execution.component_key, execution,
            execution.run_id or str(uuid.uuid4()),
        )

    async def _run_stage(
        self,
        stage_def: StageDefinition,
        input_artifacts: dict[str, str],
        component_key: str | None,
        execution: StageExecution,
        run_id: str,
    ):
        """Run a single stage (generate → ai_review → set status)."""
        project_id = stage_def.pipeline_config.project_id

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
            content, artifact_id = await generate(
                stage_def, input_artifacts, component_key, self.db
            )
            execution.artifact_id = artifact_id

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

                feedback = await ai_review(stage_def, content, input_artifacts)
                artifact = self.db.get(Artifact, artifact_id)
                if artifact:
                    artifact.ai_review_feedback = feedback
                    artifact.status = ArtifactStatus.AI_REVIEWING

            # Set to awaiting review
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
        "system_architecture": ArtifactType.SYSTEM_ARCHITECTURE,
        "component_architectures": ArtifactType.COMPONENT_ARCHITECTURE,
        "high_level_plan": ArtifactType.HIGH_LEVEL_PLAN,
        "component_plans": ArtifactType.COMPONENT_PLAN,
        "code_generation": ArtifactType.CODE,
    }
    return mapping.get(stage_key, ArtifactType.CODE)
