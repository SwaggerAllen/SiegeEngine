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

logger = logging.getLogger(__name__)

from backend.models import (
    Artifact,
    ArtifactComment,
    ArtifactStatus,
    ArtifactType,
    ComponentDefinition,
    ExecutionMode,
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
from backend.pipeline.nodes.ai_review import ai_review
from backend.pipeline.nodes.extract_components import (
    inject_setup_component,
    parse_components_from_content,
    parse_sub_components_from_content,
    validate_dependency_dag,
)
from backend.pipeline.nodes.generate import generate
from backend.websocket.manager import ws_manager


# Stage keys grouped by level for readiness checks
COMPONENT_STAGE_ORDER = [
    "component_requirements", "component_architectures", "component_plans",
]
SUB_COMPONENT_STAGE_ORDER = [
    "sub_component_requirements", "sub_component_architectures", "sub_component_plans",
]

# Extraction stages that define downstream branching structure —
# always pause for human review regardless of execution mode.
BRANCHING_STAGES = {"extract_components", "extract_sub_components"}

# Map stage keys to the artifact type they produce (for readiness checks)
_STAGE_TO_PLAN_TYPE = {
    "component_plans": ArtifactType.COMPONENT_PLAN,
    "sub_component_plans": ArtifactType.SUB_COMPONENT_PLAN,
}


class PipelineEngine:
    def __init__(self, db: Session):
        self.db = db

    async def start_pipeline(
        self, project_id: str, pipeline_run_id: str | None = None,
    ) -> str:
        """Start a pipeline run. Returns run_id.

        Carries over APPROVED (non-stale) executions from the most recent run
        so that already-approved work is preserved.  Only non-approved stages
        (awaiting review, rejected, failed, pending) are re-processed.
        """
        logger.info("start_pipeline called for project_id=%s, pipeline_run_id=%s", project_id, pipeline_run_id)

        project = self.db.get(Project, project_id)
        if not project or not project.pipeline_config:
            logger.error("Project or pipeline config not found for project_id=%s", project_id)
            raise ValueError("Project or pipeline config not found")

        config = project.pipeline_config

        # Load PipelineRun if provided (new flow), otherwise legacy fallback
        pipeline_run = self.db.get(PipelineRun, pipeline_run_id) if pipeline_run_id else None
        run_id = pipeline_run.run_id if pipeline_run else str(uuid.uuid4())

        # Carry over APPROVED executions from the most recent previous run
        # so we don't regenerate already-approved artifacts.
        prev_run = (
            self.db.query(PipelineRun)
            .filter_by(project_id=project_id)
            .filter(PipelineRun.id != pipeline_run_id)
            .order_by(PipelineRun.run_number.desc())
            .first()
        )
        if prev_run:
            stale_artifact_ids = {
                a.id for a in
                self.db.query(Artifact)
                .filter_by(project_id=project_id, status=ArtifactStatus.STALE)
                .all()
            }
            prev_approved = (
                self.db.query(StageExecution)
                .filter_by(project_id=project_id, run_id=prev_run.run_id,
                           status=StageStatus.APPROVED)
                .all()
            )
            carried = 0
            for prev_exec in prev_approved:
                if prev_exec.artifact_id and prev_exec.artifact_id in stale_artifact_ids:
                    continue
                new_exec = StageExecution(
                    project_id=project_id,
                    stage_key=prev_exec.stage_key,
                    component_key=prev_exec.component_key,
                    status=StageStatus.APPROVED,
                    artifact_id=prev_exec.artifact_id,
                    started_at=prev_exec.started_at,
                    completed_at=prev_exec.completed_at,
                    run_id=run_id,
                    retry_count=0,
                )
                self.db.add(new_exec)
                carried += 1
            self.db.commit()
            logger.info("Carried over %d approved executions from run %s", carried, prev_run.run_id)

        stages = sorted(config.stages, key=lambda s: s.order_index)
        logger.info(
            "Pipeline run_id=%s (run #%s) starting with %d stages: %s",
            run_id, pipeline_run.run_number if pipeline_run else "?",
            len(stages), [s.stage_key for s in stages],
        )

        await self._find_and_execute_next(project_id, run_id, config, pipeline_run)
        return run_id

    async def resume_run(
        self, project_id: str, pipeline_run_id: str, prev_run_id: str,
    ) -> str:
        """Resume a pipeline by carrying over work from a previous run.

        Copies APPROVED + AWAITING_REVIEW executions from the previous run,
        so the engine only re-processes stale/failed/missing nodes.
        """
        logger.info(
            "resume_run called: project_id=%s, pipeline_run_id=%s, prev_run_id=%s",
            project_id, pipeline_run_id, prev_run_id,
        )

        project = self.db.get(Project, project_id)
        if not project or not project.pipeline_config:
            raise ValueError("Project or pipeline config not found")

        config = project.pipeline_config
        pipeline_run = self.db.get(PipelineRun, pipeline_run_id)
        if not pipeline_run:
            raise ValueError("PipelineRun not found")

        new_run_id = pipeline_run.run_id

        # Find all executions from the previous run that should carry over
        prev_executions = (
            self.db.query(StageExecution)
            .filter_by(project_id=project_id, run_id=prev_run_id)
            .filter(StageExecution.status.in_([
                StageStatus.APPROVED,
                StageStatus.AWAITING_REVIEW,
            ]))
            .all()
        )

        # Check which artifacts are stale — these should NOT be carried over
        stale_artifact_ids = set()
        stale_artifacts = (
            self.db.query(Artifact)
            .filter_by(project_id=project_id, status=ArtifactStatus.STALE)
            .all()
        )
        for art in stale_artifacts:
            stale_artifact_ids.add(art.id)

        carried = 0
        review_carried = 0
        for prev_exec in prev_executions:
            # Skip executions whose artifacts are stale
            if prev_exec.artifact_id and prev_exec.artifact_id in stale_artifact_ids:
                logger.info(
                    "Skipping stale execution %s (stage=%s, component=%s)",
                    prev_exec.id, prev_exec.stage_key, prev_exec.component_key,
                )
                continue

            # Create a copy for the new run
            new_exec = StageExecution(
                project_id=project_id,
                stage_key=prev_exec.stage_key,
                component_key=prev_exec.component_key,
                status=prev_exec.status,
                artifact_id=prev_exec.artifact_id,
                started_at=prev_exec.started_at,
                completed_at=prev_exec.completed_at,
                run_id=new_run_id,
                retry_count=0,
            )
            self.db.add(new_exec)
            if prev_exec.status == StageStatus.AWAITING_REVIEW:
                review_carried += 1
            else:
                carried += 1

        self.db.commit()
        logger.info(
            "Carried over %d approved + %d in-review executions from prev run %s to new run %s",
            carried, review_carried, prev_run_id, new_run_id,
        )

        stages = sorted(config.stages, key=lambda s: s.order_index)
        logger.info(
            "Resume run_id=%s (run #%s) with %d stages: %s",
            new_run_id, pipeline_run.run_number,
            len(stages), [s.stage_key for s in stages],
        )

        await self._find_and_execute_next(project_id, new_run_id, config, pipeline_run)
        return new_run_id

    def _should_pause(
        self, stage_def: StageDefinition, pipeline_run: PipelineRun | None,
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
            triplet_ends = {"high_level_plan", "component_plans", "sub_component_plans"}
            if stage_def.stage_key in triplet_ends:
                return True
            if stage_def.stage_key in BRANCHING_STAGES:
                return True
            return pipeline_run.human_review and stage_def.human_review_enabled

        return False

    async def _find_and_execute_next(
        self, project_id: str, run_id: str, config: PipelineConfig,
        pipeline_run: PipelineRun | None = None,
    ):
        """Find the next executable work item across all stages and execute it.

        Scans the full DAG rather than stopping at the first incomplete stage,
        so downstream entities whose dependencies are met can progress even while
        sibling entities in earlier stages are still awaiting review.
        """
        stages = sorted(config.stages, key=lambda s: s.order_index)
        has_pending_work = False
        did_execute = False

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
                .filter(StageExecution.status.in_([
                    StageStatus.AWAITING_REVIEW,
                    StageStatus.RUNNING,
                    StageStatus.AI_REVIEW,
                ]))
                .count()
            )
            if pending_count > 0:
                # Stage has pending work — note it but DON'T stop.
                # Continue scanning downstream stages for entities whose
                # dependencies are already met.
                has_pending_work = True
                logger.info("Stage %s has %d pending executions, scanning downstream", stage_def.stage_key, pending_count)
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
                did_execute = True

                await self._run_stage(
                    project_id, stage_def, input_artifacts, None, execution, run_id,
                    human_notes=rejected_notes, config=config, pipeline_run=pipeline_run,
                )

                if execution.status == StageStatus.FAILED:
                    logger.error("Pipeline stopped: stage %s failed", stage_def.stage_key)
                    await ws_manager.broadcast(project_id, {
                        "type": "pipeline_completed", "run_id": run_id,
                    })
                    return

                # Post-generation hooks (deferred for branching stages until approval)
                if execution.status in (StageStatus.AWAITING_REVIEW, StageStatus.APPROVED):
                    if stage_def.stage_key not in BRANCHING_STAGES:
                        await self._post_generation_hook(project_id, stage_def, None, execution)

                # Check if pipeline should pause at this stage
                if execution.status == StageStatus.AWAITING_REVIEW:
                    has_pending_work = True
                    if self._should_pause(stage_def, pipeline_run):
                        await ws_manager.broadcast(project_id, {
                            "type": "pipeline_paused",
                            "stage_key": stage_def.stage_key,
                            "run_id": run_id,
                            "message": f"Awaiting review for {stage_def.display_name}",
                        })
                        return

            elif fan_out in (FanOutStrategy.COMPONENT, FanOutStrategy.SUB_COMPONENT, FanOutStrategy.LEAF):
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
                    logger.info("Stage %s: entities exist but none ready, scanning downstream", stage_def.stage_key)
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
                    did_execute = True

                    await self._run_stage(
                        project_id, stage_def, input_artifacts, entity_key, execution, run_id,
                        human_notes=rejected_notes, config=config, pipeline_run=pipeline_run,
                    )

                    if execution.status == StageStatus.FAILED:
                        stage_failed = True
                        break

                    # Post-generation hooks (deferred for branching stages until approval)
                    if execution.status in (StageStatus.AWAITING_REVIEW, StageStatus.APPROVED):
                        if stage_def.stage_key not in BRANCHING_STAGES:
                            await self._post_generation_hook(project_id, stage_def, entity_key, execution)

                if stage_failed:
                    logger.error("Pipeline stopped: stage %s failed", stage_def.stage_key)
                    await ws_manager.broadcast(project_id, {
                        "type": "pipeline_completed", "run_id": run_id,
                    })
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
                        await ws_manager.broadcast(project_id, {
                            "type": "pipeline_paused",
                            "stage_key": stage_def.stage_key,
                            "run_id": run_id,
                            "message": f"Awaiting review for {stage_def.display_name}",
                        })
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
                from backend.pipeline.checkpoint import build_siege_state
                from backend.git_manager.service import git_manager

                siege_state = build_siege_state(self.db, project_id, pipeline_run)
                git_commit_sha = git_manager.checkpoint_run(
                    project_id, siege_state,
                    f"Run #{pipeline_run.run_number} completed",
                )
                pipeline_run.git_commit_sha = git_commit_sha
                self.db.commit()

                # Auto-push if configured
                project = self.db.get(Project, project_id)
                if project and project.auto_push_enabled and project.remote_url:
                    try:
                        git_manager.push_current_branch(project_id)
                        logger.info("Auto-pushed run #%d for project %s", pipeline_run.run_number, project_id)
                    except Exception as push_err:
                        logger.warning("Auto-push failed for project %s: %s", project_id, push_err)
            except Exception as ckpt_err:
                logger.error("Checkpoint failed for run #%d: %s", pipeline_run.run_number, ckpt_err)

        await ws_manager.broadcast(project_id, {
            "type": "pipeline_completed",
            "run_id": run_id,
            "run_number": pipeline_run.run_number if pipeline_run else None,
            "git_commit_sha": git_commit_sha,
        })

    def _stage_fully_complete(
        self, project_id: str, stage_def: StageDefinition, run_id: str
    ) -> bool:
        """Check if a stage is fully complete (all expected entities approved)."""
        fan_out = stage_def.fan_out_strategy

        if fan_out == FanOutStrategy.NONE:
            approved = (
                self.db.query(StageExecution)
                .filter_by(
                    project_id=project_id,
                    stage_key=stage_def.stage_key,
                    run_id=run_id,
                    status=StageStatus.APPROVED,
                )
                .count()
            )
            return approved > 0

        # Fan-out stages: check if ALL entities have approved executions
        all_entities = self._get_all_entities_for_stage(project_id, stage_def)
        if not all_entities:
            # No entities yet — stage isn't complete but also can't have work
            # For extract_sub_components with COMPONENT fan-out, check if all components done
            return False

        for entity_key in all_entities:
            approved = (
                self.db.query(StageExecution)
                .filter_by(
                    project_id=project_id,
                    stage_key=stage_def.stage_key,
                    run_id=run_id,
                    component_key=entity_key,
                    status=StageStatus.APPROVED,
                )
                .count()
            )
            if approved == 0:
                return False

        return True

    def _get_all_entities_for_stage(
        self, project_id: str, stage_def: StageDefinition
    ) -> list[str]:
        """Get all entity keys that should be processed for a fan-out stage."""
        fan_out = stage_def.fan_out_strategy

        if fan_out == FanOutStrategy.COMPONENT:
            comps = self._get_components(project_id)
            # Inject setup component for relevant stages
            if stage_def.stage_key in ("component_plans", "code_generation", "code_review"):
                comps = inject_setup_component(comps)
            return [c["key"] for c in comps]

        elif fan_out == FanOutStrategy.SUB_COMPONENT:
            return [sc.key for sc in self._get_sub_component_defs(project_id)]

        elif fan_out == FanOutStrategy.LEAF:
            return self._get_leaf_keys(project_id)

        return []

    def _get_ready_entities(
        self, project_id: str, stage_def: StageDefinition, run_id: str
    ) -> list[str]:
        """Get entity keys that are ready to be processed for a fan-out stage."""
        fan_out = stage_def.fan_out_strategy
        ready = []

        if fan_out == FanOutStrategy.COMPONENT:
            comps = self._get_components(project_id)
            if stage_def.stage_key in ("component_plans", "code_generation", "code_review"):
                comps = inject_setup_component(comps)

            for comp in comps:
                key = comp["key"]
                if self._is_component_ready(project_id, key, stage_def, run_id, comp.get("dependencies", [])):
                    ready.append(key)

        elif fan_out == FanOutStrategy.SUB_COMPONENT:
            sub_comps = self._get_sub_component_defs(project_id)
            for sc in sub_comps:
                # Sub-component key in artifacts is "parent_key.sub_key"
                full_key = f"{sc.parent_key}.{sc.key}"
                deps = sc.dependencies or []
                # Deps are sibling keys, need full paths
                full_deps = [f"{sc.parent_key}.{d}" for d in deps]
                if self._is_sub_component_ready(project_id, full_key, sc.parent_key, stage_def, run_id, full_deps):
                    ready.append(full_key)

        elif fan_out == FanOutStrategy.LEAF:
            leaves = self._get_leaf_keys(project_id)
            for leaf_key in leaves:
                if self._is_leaf_ready(project_id, leaf_key, stage_def, run_id):
                    ready.append(leaf_key)

        return ready

    def _is_component_ready(
        self, project_id: str, comp_key: str, stage_def: StageDefinition,
        run_id: str, dependencies: list[str]
    ) -> bool:
        """Check if a component is ready for a given stage."""
        # 1. Not already processed (non-rejected execution exists)
        existing = (
            self.db.query(StageExecution)
            .filter_by(
                project_id=project_id,
                stage_key=stage_def.stage_key,
                run_id=run_id,
                component_key=comp_key,
            )
            .filter(StageExecution.status.notin_([StageStatus.REJECTED]))
            .first()
        )
        if existing:
            return False

        # 2. All upstream dependency components have approved plans
        for dep_key in dependencies:
            if not self._has_approved_artifact(project_id, ArtifactType.COMPONENT_PLAN, dep_key):
                return False

        # 3. Own prior component stages are approved
        if stage_def.stage_key in COMPONENT_STAGE_ORDER:
            current_idx = COMPONENT_STAGE_ORDER.index(stage_def.stage_key)
            for prior_key in COMPONENT_STAGE_ORDER[:current_idx]:
                if not self._has_approved_execution(project_id, prior_key, comp_key, run_id):
                    return False

        # 4. For extract_sub_components, component_plans must be approved
        if stage_def.stage_key == "extract_sub_components":
            if not self._has_approved_artifact(project_id, ArtifactType.COMPONENT_PLAN, comp_key):
                return False

        return True

    def _is_sub_component_ready(
        self, project_id: str, full_key: str, parent_key: str,
        stage_def: StageDefinition, run_id: str, full_deps: list[str]
    ) -> bool:
        """Check if a sub-component is ready for a given stage."""
        # 1. Not already processed
        existing = (
            self.db.query(StageExecution)
            .filter_by(
                project_id=project_id,
                stage_key=stage_def.stage_key,
                run_id=run_id,
                component_key=full_key,
            )
            .filter(StageExecution.status.notin_([StageStatus.REJECTED]))
            .first()
        )
        if existing:
            return False

        # 2. All dependency sub-components have approved plans
        for dep_key in full_deps:
            if not self._has_approved_artifact(project_id, ArtifactType.SUB_COMPONENT_PLAN, dep_key):
                return False

        # 3. Own prior sub-component stages are approved
        if stage_def.stage_key in SUB_COMPONENT_STAGE_ORDER:
            current_idx = SUB_COMPONENT_STAGE_ORDER.index(stage_def.stage_key)
            for prior_key in SUB_COMPONENT_STAGE_ORDER[:current_idx]:
                if not self._has_approved_execution(project_id, prior_key, full_key, run_id):
                    return False

        # 4. Parent extract_sub_components must be approved
        if not self._has_approved_execution(project_id, "extract_sub_components", parent_key, run_id):
            return False

        return True

    def _is_leaf_ready(
        self, project_id: str, leaf_key: str, stage_def: StageDefinition, run_id: str
    ) -> bool:
        """Check if a leaf entity is ready for code generation/review."""
        # 1. Not already processed
        existing = (
            self.db.query(StageExecution)
            .filter_by(
                project_id=project_id,
                stage_key=stage_def.stage_key,
                run_id=run_id,
                component_key=leaf_key,
            )
            .filter(StageExecution.status.notin_([StageStatus.REJECTED]))
            .first()
        )
        if existing:
            return False

        # 2. Check if leaf's plan is approved
        if "." in leaf_key:
            # Sub-component leaf
            if not self._has_approved_artifact(project_id, ArtifactType.SUB_COMPONENT_PLAN, leaf_key):
                return False
        else:
            # Top-level component leaf
            if not self._has_approved_artifact(project_id, ArtifactType.COMPONENT_PLAN, leaf_key):
                return False

        # 3. For code_review, code_generation must be approved
        if stage_def.stage_key == "code_review":
            if not self._has_approved_execution(project_id, "code_generation", leaf_key, run_id):
                return False

        return True

    def _has_approved_artifact(
        self, project_id: str, artifact_type: ArtifactType, component_key: str
    ) -> bool:
        """Check if an approved artifact exists."""
        return (
            self.db.query(Artifact)
            .filter_by(
                project_id=project_id,
                artifact_type=artifact_type,
                component_key=component_key,
                status=ArtifactStatus.APPROVED,
            )
            .count()
        ) > 0

    def _has_approved_execution(
        self, project_id: str, stage_key: str, component_key: str, run_id: str
    ) -> bool:
        """Check if an approved execution exists for a stage+component."""
        return (
            self.db.query(StageExecution)
            .filter_by(
                project_id=project_id,
                stage_key=stage_key,
                run_id=run_id,
                component_key=component_key,
                status=StageStatus.APPROVED,
            )
            .count()
        ) > 0

    def _get_components(self, project_id: str) -> list[dict]:
        """Get top-level components from ComponentDefinition table."""
        defs = (
            self.db.query(ComponentDefinition)
            .filter_by(project_id=project_id)
            .filter(ComponentDefinition.parent_key.is_(None))
            .all()
        )
        return [
            {
                "key": d.key,
                "name": d.name,
                "description": d.description,
                "dependencies": d.dependencies or [],
            }
            for d in defs
        ]

    def _get_sub_component_defs(self, project_id: str) -> list[ComponentDefinition]:
        """Get all sub-components from ComponentDefinition table."""
        return (
            self.db.query(ComponentDefinition)
            .filter_by(project_id=project_id)
            .filter(ComponentDefinition.parent_key.isnot(None))
            .all()
        )

    def _get_leaf_keys(self, project_id: str) -> list[str]:
        """Get leaf entity keys (components without sub-components + all sub-components)."""
        all_defs = (
            self.db.query(ComponentDefinition)
            .filter_by(project_id=project_id)
            .all()
        )

        top_level = [d for d in all_defs if d.parent_key is None]
        sub_comps = [d for d in all_defs if d.parent_key is not None]
        parent_keys = {d.parent_key for d in sub_comps}

        leaves = []
        # Top-level components that have no sub-components
        for d in top_level:
            if d.key not in parent_keys:
                leaves.append(d.key)
        # All sub-components
        for d in sub_comps:
            leaves.append(f"{d.parent_key}.{d.key}")

        return leaves

    def _store_components(self, project_id: str, content: str):
        """Parse extract_components output and create ComponentDefinition records."""
        components = parse_components_from_content(content)
        if not components:
            logger.warning("No components parsed from extract_components output")
            return

        errors = validate_dependency_dag(components)
        if errors:
            logger.warning("Component dependency validation errors: %s", errors)

        # Inject setup component
        components = inject_setup_component(components)

        # Clear existing top-level components for this project
        (
            self.db.query(ComponentDefinition)
            .filter_by(project_id=project_id)
            .filter(ComponentDefinition.parent_key.is_(None))
            .delete()
        )

        for comp in components:
            cd = ComponentDefinition(
                project_id=project_id,
                key=comp["key"],
                name=comp.get("name", comp["key"]),
                description=comp.get("description"),
                parent_key=None,
                dependencies=comp.get("dependencies", []),
            )
            self.db.add(cd)

        self.db.flush()
        logger.info("Stored %d top-level components for project %s", len(components), project_id)

    def _store_sub_components(self, project_id: str, parent_key: str, content: str):
        """Parse extract_sub_components output and create sub-ComponentDefinition records."""
        result = parse_sub_components_from_content(content)

        if not result.get("needs_decomposition", False):
            logger.info("Component %s does not need sub-component decomposition", parent_key)
            return

        sub_components = result.get("components", [])
        if not sub_components:
            return

        errors = validate_dependency_dag(sub_components)
        if errors:
            logger.warning("Sub-component dependency validation errors for %s: %s", parent_key, errors)

        # Clear existing sub-components for this parent
        (
            self.db.query(ComponentDefinition)
            .filter_by(project_id=project_id, parent_key=parent_key)
            .delete()
        )

        for comp in sub_components:
            cd = ComponentDefinition(
                project_id=project_id,
                key=comp["key"],
                name=comp.get("name", comp["key"]),
                description=comp.get("description"),
                parent_key=parent_key,
                dependencies=comp.get("dependencies", []),
            )
            self.db.add(cd)

        self.db.flush()
        logger.info("Stored %d sub-components for %s in project %s", len(sub_components), parent_key, project_id)

    async def _post_generation_hook(
        self, project_id: str, stage_def: StageDefinition,
        component_key: str | None, execution: StageExecution
    ):
        """Run post-generation hooks for extraction stages."""
        if not execution.artifact_id:
            return

        artifact = self.db.get(Artifact, execution.artifact_id)
        if not artifact or not artifact.content:
            return

        if stage_def.stage_key == "extract_components":
            self._store_components(project_id, artifact.content)
        elif stage_def.stage_key == "extract_sub_components" and component_key:
            self._store_sub_components(project_id, component_key, artifact.content)

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
            # Mark artifact as approved
            if execution.artifact_id:
                artifact = self.db.get(Artifact, execution.artifact_id)
                if artifact:
                    if edited_content:
                        artifact.content = edited_content
                        artifact.version += 1
                    artifact.status = ArtifactStatus.APPROVED

                    # Store feedback as a comment record (not on artifact field)
                    if notes and notes.strip():
                        self.db.add(ArtifactComment(
                            artifact_id=execution.artifact_id,
                            project_id=execution.project_id,
                            author_id=user_id,
                            content=notes.strip(),
                            comment_type="feedback",
                            artifact_version=artifact.version,
                        ))

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

            # Run post-generation hooks (e.g., store components after approval)
            config = (
                self.db.query(PipelineConfig)
                .filter_by(project_id=execution.project_id)
                .first()
            )
            if config:
                stage_def = next(
                    (s for s in config.stages if s.stage_key == execution.stage_key),
                    None,
                )
                if stage_def:
                    await self._post_generation_hook(
                        execution.project_id, stage_def, execution.component_key, execution
                    )

                    # If this stage was regenerated, downstream approved artifacts are
                    # stale because they were built on the old version.  Invalidate
                    # their executions so _find_and_execute_next picks them up.
                    if (execution.retry_count or 0) > 0:
                        stale_ids = self._invalidate_stale_downstream(
                            execution.project_id, execution.run_id,
                            stage_def.order_index, config,
                        )
                        if stale_ids:
                            self.db.commit()
                            await ws_manager.broadcast(execution.project_id, {
                                "type": "staleness_propagated",
                                "stale_artifact_ids": stale_ids,
                            })

            # Find and execute next available work
            await self._check_and_continue(execution)

        elif action == "rejected":
            logger.info("Stage %s rejected (execution=%s), triggering regeneration",
                        execution.stage_key, execution_id)
            execution.status = StageStatus.REJECTED

            if execution.artifact_id:
                artifact = self.db.get(Artifact, execution.artifact_id)
                if artifact:
                    artifact.status = ArtifactStatus.REJECTED

            # Store feedback as a comment record
            if notes and notes.strip() and execution.artifact_id:
                art = self.db.get(Artifact, execution.artifact_id)
                self.db.add(ArtifactComment(
                    artifact_id=execution.artifact_id,
                    project_id=execution.project_id,
                    author_id=user_id,
                    content=notes.strip(),
                    comment_type="feedback",
                    artifact_version=art.version if art else None,
                ))

            # Cascade-reject downstream AWAITING_REVIEW nodes
            config = (
                self.db.query(PipelineConfig)
                .filter_by(project_id=execution.project_id)
                .first()
            )
            stale_artifact_ids = []
            if config:
                stage_def = next(
                    (s for s in config.stages if s.stage_key == execution.stage_key),
                    None,
                )
                if stage_def:
                    stale_artifact_ids = self._cascade_reject_downstream(
                        execution.project_id, execution.run_id,
                        stage_def.order_index, config,
                    )

            self.db.commit()

            await ws_manager.broadcast(execution.project_id, {
                "type": "stage_completed",
                "stage_key": execution.stage_key,
                "component_key": execution.component_key,
                "status": "rejected",
                "execution_id": execution_id,
            })

            if stale_artifact_ids:
                await ws_manager.broadcast(execution.project_id, {
                    "type": "staleness_propagated",
                    "stale_artifact_ids": stale_artifact_ids,
                })

            await self._regenerate_stage(execution)

        elif action == "save_feedback":
            logger.info("Saving feedback for stage %s (execution=%s)",
                        execution.stage_key, execution_id)
            if execution.artifact_id:
                artifact = self.db.get(Artifact, execution.artifact_id)
                if artifact:
                    if edited_content:
                        artifact.content = edited_content
                        artifact.version += 1

                    # Store feedback as a comment record
                    if notes and notes.strip():
                        self.db.add(ArtifactComment(
                            artifact_id=execution.artifact_id,
                            project_id=execution.project_id,
                            author_id=user_id,
                            content=notes.strip(),
                            comment_type="feedback",
                            artifact_version=artifact.version,
                        ))
            self.db.commit()

            await ws_manager.broadcast(execution.project_id, {
                "type": "feedback_saved",
                "stage_key": execution.stage_key,
                "component_key": execution.component_key,
                "execution_id": execution_id,
                "artifact_id": execution.artifact_id,
            })

    async def _check_and_continue(self, execution: StageExecution):
        """After approval, find and execute the next available work."""
        config = (
            self.db.query(PipelineConfig)
            .filter_by(project_id=execution.project_id)
            .first()
        )
        if not config:
            return

        pipeline_run = self._lookup_pipeline_run(execution.run_id) if execution.run_id else None
        await self._find_and_execute_next(
            execution.project_id, execution.run_id, config, pipeline_run
        )

    def _cascade_reject_downstream(
        self, project_id: str, run_id: str,
        rejected_stage_order_index: int, config: PipelineConfig,
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
                    exc.id, exc.stage_key, exc.component_key,
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
        self, project_id: str, run_id: str,
        approved_stage_order_index: int, config: PipelineConfig,
    ) -> list[str]:
        """After approving a regenerated stage, invalidate downstream APPROVED
        executions so they get re-processed with the updated upstream content.

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
                logger.info(
                    "Invalidating stale downstream execution %s (stage=%s, component=%s)",
                    exc.id, exc.stage_key, exc.component_key,
                )
                exc.status = StageStatus.REJECTED

                if exc.artifact_id:
                    artifact = self.db.get(Artifact, exc.artifact_id)
                    if artifact:
                        artifact.status = ArtifactStatus.STALE
                        stale_artifact_ids.append(artifact.id)

        self.db.flush()
        return stale_artifact_ids

    async def _regenerate_stage(self, old_execution: StageExecution):
        """Re-run a rejected stage with human feedback from ArtifactComment records."""
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

        input_artifacts = self._gather_inputs(project_id, stage_def, old_execution.component_key)

        # Set artifact status to GENERATING so the DAG node shows the loading animation
        if old_execution.artifact_id:
            artifact = self.db.get(Artifact, old_execution.artifact_id)
            if artifact:
                artifact.status = ArtifactStatus.GENERATING

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
        # Commit so DAG endpoint sees GENERATING status
        self.db.commit()

        logger.info("Regenerating stage %s (component=%s) with human feedback, new execution=%s",
                     old_execution.stage_key, old_execution.component_key, new_execution.id)

        await ws_manager.broadcast(project_id, {
            "type": "stage_started",
            "stage_key": old_execution.stage_key,
            "component_key": old_execution.component_key,
        })

        try:
            feedback_notes = self._get_feedback_notes(old_execution.artifact_id)
            content, artifact_id = await generate(
                stage_def, input_artifacts, old_execution.component_key, self.db,
                human_notes=feedback_notes,
            )
            new_execution.artifact_id = artifact_id

            # Insert regeneration divider comment
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

    async def revise_artifact(self, artifact_id: str, feedback: str, user_id: str | None = None):
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

        stage_def = next(
            (s for s in config.stages
             if s.output_artifact_type == artifact.artifact_type.value),
            None,
        )
        if not stage_def:
            raise ValueError(
                f"No stage definition for artifact type: {artifact.artifact_type.value}"
            )

        # Store the new feedback as an ArtifactComment
        if feedback and feedback.strip():
            self.db.add(ArtifactComment(
                artifact_id=artifact_id,
                project_id=project_id,
                author_id=user_id,
                content=feedback.strip(),
                comment_type="feedback",
                artifact_version=artifact.version,
            ))
            self.db.flush()

        # Build accumulated feedback from all feedback comments
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
        # Commit so other sessions (DAG endpoint) can see the GENERATING/RUNNING status
        self.db.commit()

        logger.info("Revising artifact %s (stage=%s, component=%s) with feedback",
                     artifact_id, stage_def.stage_key, artifact.component_key)

        await ws_manager.broadcast(project_id, {
            "type": "stage_started",
            "stage_key": stage_def.stage_key,
            "component_key": artifact.component_key,
        })

        try:
            content, new_artifact_id = await generate(
                stage_def, input_artifacts, artifact.component_key, self.db,
                human_notes=accumulated,
            )
            execution.artifact_id = new_artifact_id

            # Insert revision divider comment
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
            artifact.status = ArtifactStatus.APPROVED
            self.db.commit()

            await ws_manager.broadcast(project_id, {
                "type": "stage_failed",
                "stage_key": stage_def.stage_key,
                "component_key": artifact.component_key,
                "error": str(e),
            })

    def _lookup_pipeline_run(self, run_id: str) -> PipelineRun | None:
        """Look up a PipelineRun by its run_id."""
        return (
            self.db.query(PipelineRun)
            .filter_by(run_id=run_id)
            .first()
        )

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

        pipeline_run = self._lookup_pipeline_run(execution.run_id) if execution.run_id else None

        input_artifacts = self._gather_inputs(project_id, stage_def, execution.component_key)
        execution.status = StageStatus.RUNNING
        execution.error_message = None
        execution.retry_count = (execution.retry_count or 0) + 1
        self.db.flush()

        await self._run_stage(
            project_id, stage_def, input_artifacts, execution.component_key, execution,
            execution.run_id or str(uuid.uuid4()), config=config, pipeline_run=pipeline_run,
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
        logger.info("_run_stage: stage=%s component=%s execution_id=%s human_notes=%s",
                     stage_def.stage_key, component_key, execution.id,
                     f"{len(human_notes)} chars" if human_notes else "None")
        logger.info("  input_artifacts keys: %s", list(input_artifacts.keys()))

        # Commit the RUNNING execution so other sessions (DAG endpoint) can see it
        self.db.commit()

        try:
            await ws_manager.broadcast(project_id, {
                "type": "stage_progress",
                "stage_key": stage_def.stage_key,
                "component_key": component_key,
                "step": "generating",
                "message": f"Generating {stage_def.display_name}...",
            })

            content, artifact_id = await generate(
                stage_def, input_artifacts, component_key, self.db,
                human_notes=human_notes,
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

                feedback = await ai_review(
                    stage_def, content, input_artifacts,
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
                        await ws_manager.broadcast(project_id, {
                            "type": "stage_progress",
                            "stage_key": stage_def.stage_key,
                            "component_key": component_key,
                            "step": "self_improvement",
                            "message": f"Self-improvement loop {loop_i + 1}/{ai_loops} for {stage_def.display_name}...",
                        })

                        content, artifact_id = await generate(
                            stage_def, input_artifacts, component_key, self.db,
                            feedback=feedback,
                            human_notes=human_notes,
                        )
                        execution.artifact_id = artifact_id

                        # Re-review
                        feedback = await ai_review(
                            stage_def, content, input_artifacts,
                            review_prompt_overrides=stage_def.pipeline_config.review_prompt_overrides,
                        )
                        artifact = self.db.get(Artifact, artifact_id)
                        if artifact:
                            artifact.ai_review_feedback = feedback

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
        self, project_id: str, stage_def: StageDefinition, component_key: str | None = None,
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
                    .filter(Artifact.status.in_([
                        ArtifactStatus.APPROVED,
                        ArtifactStatus.AWAITING_REVIEW,
                    ]))
                    .first()
                )
                if artifact and artifact.content:
                    inputs[stage_key] = artifact.content
            else:
                # Project-level or aggregated input
                artifacts = (
                    self.db.query(Artifact)
                    .filter_by(project_id=project_id, artifact_type=artifact_type)
                    .filter(Artifact.status.in_([
                        ArtifactStatus.APPROVED,
                        ArtifactStatus.AWAITING_REVIEW,
                    ]))
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


# Helper functions

_COMPONENT_STAGES = {
    "component_requirements", "component_architectures", "component_plans",
    "extract_sub_components",
}
_SUB_COMPONENT_STAGES = {
    "sub_component_requirements", "sub_component_architectures", "sub_component_plans",
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
        "high_level_plan": ArtifactType.HIGH_LEVEL_PLAN,
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
