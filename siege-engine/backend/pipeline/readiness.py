"""Readiness-check mixin for PipelineEngine.

Determines which stages/entities are ready to execute based on what has
already been approved in the current run.

Status reads for approval checks use the PipelineSnapshot (event-sourced
source of truth).  Execution-existence checks still use the StageExecution
table since the snapshot is project-level and doesn't distinguish by run_id.
"""

import logging

from backend.models import (
    ArtifactType,
    FanOutStrategy,
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


class ReadinessMixin:
    """Mixin that provides stage/entity readiness checks."""

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

    def _get_ready_entities(
        self, project_id: str, stage_def: StageDefinition, run_id: str
    ) -> list[str]:
        """Get entity keys that are ready to be processed for a fan-out stage."""
        fan_out = stage_def.fan_out_strategy
        ready = []

        if fan_out == FanOutStrategy.COMPONENT:
            comps = self._get_components(project_id)

            if stage_def.stage_key == "component_plans":
                parent_keys = {d.parent_key for d in self._get_sub_component_defs(project_id)}
                comps = [c for c in comps if c["key"] not in parent_keys]

            for comp in comps:
                key = comp["key"]
                if self._is_component_ready(
                    project_id, key, stage_def, run_id, comp.get("dependencies", [])
                ):
                    ready.append(key)

        elif fan_out == FanOutStrategy.SUB_COMPONENT:
            sub_comps = self._get_sub_component_defs(project_id)
            for sc in sub_comps:
                full_key = f"{sc.parent_key}.{sc.key}"
                deps = sc.dependencies or []
                full_deps = [f"{sc.parent_key}.{d}" for d in deps]
                if self._is_sub_component_ready(
                    project_id, full_key, sc.parent_key, stage_def, run_id, full_deps
                ):
                    ready.append(full_key)

        elif fan_out == FanOutStrategy.LEAF:
            leaves = self._get_leaf_keys(project_id)
            for leaf_key in leaves:
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
            return False

        for dep_key in dependencies:
            if not self._has_approved_artifact(
                project_id, ArtifactType.COMPONENT_ARCHITECTURE, dep_key
            ):
                return False

        if stage_def.stage_key in COMPONENT_STAGE_ORDER:
            current_idx = COMPONENT_STAGE_ORDER.index(stage_def.stage_key)
            for prior_key in COMPONENT_STAGE_ORDER[:current_idx]:
                if not self._has_approved_execution(project_id, prior_key, comp_key, run_id):
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

        for dep_key in full_deps:
            if not self._has_approved_artifact(
                project_id, ArtifactType.SUB_COMPONENT_PLAN, dep_key
            ):
                return False

        if stage_def.stage_key in SUB_COMPONENT_STAGE_ORDER:
            current_idx = SUB_COMPONENT_STAGE_ORDER.index(stage_def.stage_key)
            for prior_key in SUB_COMPONENT_STAGE_ORDER[:current_idx]:
                if not self._has_approved_execution(project_id, prior_key, full_key, run_id):
                    return False

        if not self._has_approved_execution(
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
            if not self._has_approved_artifact(
                project_id, ArtifactType.SUB_COMPONENT_PLAN, leaf_key
            ):
                return False
        else:
            if not self._has_approved_artifact(project_id, ArtifactType.COMPONENT_PLAN, leaf_key):
                return False

        if stage_def.stage_key == "code_review":
            if not self._has_approved_execution(project_id, "code_generation", leaf_key, run_id):
                return False

        return True

    def _has_approved_artifact(
        self, project_id: str, artifact_type: ArtifactType, component_key: str
    ) -> bool:
        """Check if an approved artifact exists using the snapshot.

        Maps artifact_type → stage_key, then checks the snapshot's
        stage_statuses for approval.
        """
        stage_key = _ARTIFACT_TYPE_TO_STAGE_KEY.get(artifact_type)
        if not stage_key:
            return False
        snapshot = self.events.get_snapshot(project_id)
        key = f"{stage_key}/{component_key}" if component_key else stage_key
        return (snapshot.stage_statuses or {}).get(key) == "approved"

    def _has_approved_execution(
        self, project_id: str, stage_key: str, component_key: str, run_id: str
    ) -> bool:
        """Check if an approved execution exists using the snapshot.

        The snapshot's stage_statuses track the current status for each
        stage+component.  Carried-over executions set their status to
        'approved' in the snapshot.
        """
        snapshot = self.events.get_snapshot(project_id)
        key = f"{stage_key}/{component_key}" if component_key else stage_key
        return (snapshot.stage_statuses or {}).get(key) == "approved"
