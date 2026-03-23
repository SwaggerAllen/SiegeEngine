"""Readiness-check mixin for PipelineEngine.

Determines which stages/entities are ready to execute based on what has
already been generated in the current run.

Dependencies are satisfied when parent artifacts have been *generated*
(status in: approved, awaiting_review, stale) — approval is not required
for downstream generation to proceed.

Status reads use the PipelineSnapshot (event-sourced source of truth).
Execution-existence checks still use the StageExecution table since
the snapshot is project-level and doesn't distinguish by run_id.
"""

import logging

from backend.models import (
    ArtifactType,
    FanOutStrategy,
    PipelineRun,
    StageDefinition,
    StageExecution,
    StageStatus,
)

logger = logging.getLogger(__name__)

# Reverse mapping: artifact type → stage key that produces it.
_ARTIFACT_TYPE_TO_STAGE_KEY: dict[ArtifactType, str] = {
    ArtifactType.SYSTEM_REQUIREMENTS: "system_requirements",
    ArtifactType.SYSTEM_ARCHITECTURE: "system_architecture",
    ArtifactType.COMPONENT_ARCHITECTURE: "component_architectures",
    ArtifactType.COMPONENT_PLAN: "component_plans",
    ArtifactType.COMPONENT_MAP: "extract_components",
    ArtifactType.SUB_COMPONENT_MAP: "extract_sub_components",
    ArtifactType.SUB_COMPONENT_ARCHITECTURE: "sub_component_architectures",
    ArtifactType.SUB_COMPONENT_PLAN: "sub_component_plans",
    ArtifactType.CODE: "code_generation",
    ArtifactType.CODE_REVIEW: "code_review",
}

# Statuses that indicate an artifact has been generated (has content).
_GENERATED_STATUSES = {"approved", "awaiting_review", "stale"}

# Stage keys grouped by level for readiness checks.
COMPONENT_STAGE_ORDER = [
    "component_architectures",
    "extract_sub_components",
    "component_plans",
]
SUB_COMPONENT_STAGE_ORDER = [
    "sub_component_architectures",
    "sub_component_plans",
]

# Stage order mapping for scope filtering.
_STAGE_KEY_TO_ORDER: dict[str, int] = {
    "system_requirements": 0,
    "system_architecture": 1,
    "extract_components": 2,
    "component_architectures": 3,
    "extract_sub_components": 4,
    "component_plans": 5,
    "sub_component_architectures": 6,
    "sub_component_plans": 7,
    "code_generation": 8,
    "code_review": 9,
}


class ReadinessMixin:
    """Mixin that provides stage/entity readiness checks."""

    def _stage_fully_generated(
        self, project_id: str, stage_def: StageDefinition, run_id: str
    ) -> bool:
        """Check if a stage is fully generated (all expected entities have content).

        Uses the PipelineSnapshot as the source of truth for stage statuses.
        A stage is "fully generated" when all entities are in a generated state
        (approved, awaiting_review, or stale).
        """
        snapshot = self.events.get_snapshot(project_id)
        statuses = snapshot.stage_statuses or {}
        fan_out = stage_def.fan_out_strategy

        if fan_out == FanOutStrategy.NONE:
            return statuses.get(stage_def.stage_key) in _GENERATED_STATUSES

        # Fan-out stages: check if ALL entities have been generated
        all_entities = self._get_all_entities_for_stage(project_id, stage_def)
        if not all_entities:
            return False

        missing = []
        for entity_key in all_entities:
            key = f"{stage_def.stage_key}/{entity_key}"
            entity_status = statuses.get(key)
            if entity_status not in _GENERATED_STATUSES:
                missing.append(f"{entity_key}={entity_status}")

        if missing:
            logger.debug(
                "[readiness] %s not fully generated: missing/non-generated: %s",
                stage_def.stage_key, missing[:10],
            )
            return False

        return True

    def _stage_fully_complete(
        self, project_id: str, stage_def: StageDefinition, run_id: str
    ) -> bool:
        """Check if a stage is fully complete (all expected entities approved).

        Uses the PipelineSnapshot as the source of truth for stage statuses.
        """
        snapshot = self.events.get_snapshot(project_id)
        statuses = snapshot.stage_statuses or {}
        fan_out = stage_def.fan_out_strategy

        if fan_out == FanOutStrategy.NONE:
            return statuses.get(stage_def.stage_key) == "approved"

        # Fan-out stages: check if ALL entities have approved status
        all_entities = self._get_all_entities_for_stage(project_id, stage_def)
        if not all_entities:
            return False

        for entity_key in all_entities:
            key = f"{stage_def.stage_key}/{entity_key}"
            if statuses.get(key) != "approved":
                return False

        return True

    def _is_in_run_scope(
        self,
        stage_def: StageDefinition,
        component_key: str | None,
        pipeline_run: PipelineRun | None,
    ) -> bool:
        """Check if a stage/entity is within the scope of the current run.

        A run scoped to a starting node only generates descendants of that node.
        If no start node is set, everything is in scope.
        """
        if not pipeline_run:
            return True
        if not pipeline_run.start_stage_key:
            return True

        start_order = _STAGE_KEY_TO_ORDER.get(pipeline_run.start_stage_key, 0)
        stage_order = stage_def.order_index

        # Stages before the start are out of scope
        if stage_order < start_order:
            return False

        # If run is scoped to a specific component, filter by that component
        if pipeline_run.start_component_key:
            start_comp = pipeline_run.start_component_key
            if component_key:
                # component_key matches or is a sub-component of start_comp
                if not (component_key == start_comp
                        or component_key.startswith(f"{start_comp}.")):
                    return False
            elif stage_def.fan_out_strategy != FanOutStrategy.NONE:
                # Fan-out stage but no component_key yet — will be filtered
                # at entity level by _get_scoped_ready_entities
                pass

        return True

    def _get_all_entities_for_stage(self, project_id: str, stage_def: StageDefinition) -> list[str]:
        """Get all entity keys that should be processed for a fan-out stage.

        Self-healing: if no entities are found but an approved branching artifact
        exists, attempt to re-populate ComponentDefinitions before returning.
        """
        entities = self._collect_entities(project_id, stage_def)

        if not entities and stage_def.fan_out_strategy != FanOutStrategy.NONE:
            if self._heal_missing_entities(project_id, stage_def):
                entities = self._collect_entities(project_id, stage_def)

        return entities

    def _collect_entities(self, project_id: str, stage_def: StageDefinition) -> list[str]:
        """Raw entity collection without self-healing."""
        fan_out = stage_def.fan_out_strategy

        if fan_out == FanOutStrategy.COMPONENT:
            comps = self._get_components(project_id)
            if stage_def.stage_key == "component_plans":
                parent_keys = {d.parent_key for d in self._get_sub_component_defs(project_id)}
                comps = [c for c in comps if c["key"] not in parent_keys]
            return [c["key"] for c in comps]

        elif fan_out == FanOutStrategy.SUB_COMPONENT:
            return [sc.key for sc in self._get_sub_component_defs(project_id)]

        elif fan_out == FanOutStrategy.LEAF:
            return self._get_leaf_keys(project_id)

        return []

    def _entity_already_generated(
        self, project_id: str, stage_key: str, component_key: str | None,
    ) -> bool:
        """Check if an entity already has generated content in the snapshot.

        Used by regen_generated_only runs to skip entities that haven't been
        generated yet (only regenerate what already exists).
        """
        snapshot = self.events.get_snapshot(project_id)
        key = f"{stage_key}/{component_key}" if component_key else stage_key
        return (snapshot.stage_statuses or {}).get(key) in _GENERATED_STATUSES

    def _get_ready_entities(
        self, project_id: str, stage_def: StageDefinition, run_id: str,
        pipeline_run: PipelineRun | None = None,
    ) -> list[str]:
        """Get entity keys that are ready to be processed for a fan-out stage."""
        fan_out = stage_def.fan_out_strategy
        regen_only = pipeline_run.regen_generated_only if pipeline_run else False
        ready = []

        if fan_out == FanOutStrategy.COMPONENT:
            comps = self._get_components(project_id)

            if stage_def.stage_key == "component_plans":
                parent_keys = {d.parent_key for d in self._get_sub_component_defs(project_id)}
                comps = [c for c in comps if c["key"] not in parent_keys]

            for comp in comps:
                key = comp["key"]
                if not self._is_in_run_scope(stage_def, key, pipeline_run):
                    logger.debug(
                        "[readiness] %s/%s: out of run scope (start_component=%s)",
                        stage_def.stage_key, key,
                        pipeline_run.start_component_key if pipeline_run else None,
                    )
                    continue
                if regen_only and not self._entity_already_generated(
                    project_id, stage_def.stage_key, key
                ):
                    logger.debug(
                        "[readiness] %s/%s: skipped (regen_only, not previously generated)",
                        stage_def.stage_key, key,
                    )
                    continue
                if self._is_component_ready(
                    project_id, key, stage_def, run_id, comp.get("dependencies", [])
                ):
                    ready.append(key)
                else:
                    logger.debug(
                        "[readiness] %s/%s: not ready (deps=%s)",
                        stage_def.stage_key, key, comp.get("dependencies", []),
                    )

        elif fan_out == FanOutStrategy.SUB_COMPONENT:
            sub_comps = self._get_sub_component_defs(project_id)
            for sc in sub_comps:
                full_key = f"{sc.parent_key}.{sc.key}"
                if not self._is_in_run_scope(stage_def, full_key, pipeline_run):
                    continue
                if regen_only and not self._entity_already_generated(
                    project_id, stage_def.stage_key, full_key
                ):
                    continue
                deps = sc.dependencies or []
                full_deps = [f"{sc.parent_key}.{d}" for d in deps]
                if self._is_sub_component_ready(
                    project_id, full_key, sc.parent_key, stage_def, run_id, full_deps
                ):
                    ready.append(full_key)

        elif fan_out == FanOutStrategy.LEAF:
            leaves = self._get_leaf_keys(project_id)
            for leaf_key in leaves:
                if not self._is_in_run_scope(stage_def, leaf_key, pipeline_run):
                    continue
                if regen_only and not self._entity_already_generated(
                    project_id, stage_def.stage_key, leaf_key
                ):
                    continue
                if self._is_leaf_ready(project_id, leaf_key, stage_def, run_id):
                    ready.append(leaf_key)

        return ready

    def _is_component_ready(
        self,
        project_id: str,
        comp_key: str,
        stage_def: StageDefinition,
        run_id: str,
        dependencies: list[str],
    ) -> bool:
        """Check if a component is ready for a given stage."""
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
            logger.debug(
                "[readiness] %s/%s not ready: existing exec %s (status=%s) in run %s",
                stage_def.stage_key, comp_key, existing.id, existing.status.value, run_id,
            )
            return False

        # Dependencies satisfied when parent has been *generated* (not just approved)
        for dep_key in dependencies:
            if not self._has_generated_artifact(
                project_id, ArtifactType.COMPONENT_ARCHITECTURE, dep_key
            ):
                logger.debug(
                    "[readiness] %s/%s not ready: dependency %s not generated",
                    stage_def.stage_key, comp_key, dep_key,
                )
                return False

        if stage_def.stage_key in COMPONENT_STAGE_ORDER:
            current_idx = COMPONENT_STAGE_ORDER.index(stage_def.stage_key)
            for prior_key in COMPONENT_STAGE_ORDER[:current_idx]:
                if not self._has_generated_execution(project_id, prior_key, comp_key, run_id):
                    logger.debug(
                        "[readiness] %s/%s not ready: prior stage %s not generated",
                        stage_def.stage_key, comp_key, prior_key,
                    )
                    return False

        return True

    def _is_sub_component_ready(
        self,
        project_id: str,
        full_key: str,
        parent_key: str,
        stage_def: StageDefinition,
        run_id: str,
        full_deps: list[str],
    ) -> bool:
        """Check if a sub-component is ready for a given stage."""
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

        # Dependencies satisfied when parent has been *generated*
        for dep_key in full_deps:
            if not self._has_generated_artifact(
                project_id, ArtifactType.SUB_COMPONENT_ARCHITECTURE, dep_key
            ):
                return False

        if stage_def.stage_key in SUB_COMPONENT_STAGE_ORDER:
            current_idx = SUB_COMPONENT_STAGE_ORDER.index(stage_def.stage_key)
            for prior_key in SUB_COMPONENT_STAGE_ORDER[:current_idx]:
                if not self._has_generated_execution(project_id, prior_key, full_key, run_id):
                    return False

        if not self._has_generated_execution(
            project_id, "extract_sub_components", parent_key, run_id
        ):
            return False

        return True

    def _is_leaf_ready(
        self, project_id: str, leaf_key: str, stage_def: StageDefinition, run_id: str
    ) -> bool:
        """Check if a leaf entity is ready for code generation/review."""
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

        if "." in leaf_key:
            if not self._has_generated_artifact(
                project_id, ArtifactType.SUB_COMPONENT_PLAN, leaf_key
            ):
                return False
        else:
            if not self._has_generated_artifact(project_id, ArtifactType.COMPONENT_PLAN, leaf_key):
                return False

        if stage_def.stage_key == "code_review":
            if not self._has_generated_execution(project_id, "code_generation", leaf_key, run_id):
                return False

        return True

    def _has_generated_artifact(
        self, project_id: str, artifact_type: ArtifactType, component_key: str
    ) -> bool:
        """Check if a generated artifact exists using the snapshot.

        An artifact is considered "generated" if its status indicates it has
        content: approved, awaiting_review, or stale.
        """
        stage_key = _ARTIFACT_TYPE_TO_STAGE_KEY.get(artifact_type)
        if not stage_key:
            return False
        snapshot = self.events.get_snapshot(project_id)
        key = f"{stage_key}/{component_key}" if component_key else stage_key
        return (snapshot.stage_statuses or {}).get(key) in _GENERATED_STATUSES

    def _has_generated_execution(
        self, project_id: str, stage_key: str, component_key: str, run_id: str
    ) -> bool:
        """Check if a generated execution exists using the snapshot.

        An execution is considered "generated" if its status indicates the
        artifact has content: approved, awaiting_review, or stale.
        """
        snapshot = self.events.get_snapshot(project_id)
        key = f"{stage_key}/{component_key}" if component_key else stage_key
        return (snapshot.stage_statuses or {}).get(key) in _GENERATED_STATUSES

    # Keep legacy names as aliases for any external callers
    _has_approved_artifact = _has_generated_artifact
    _has_approved_execution = _has_generated_execution
