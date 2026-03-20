"""Component management mixin for PipelineEngine.

Handles storing, updating, and retrieving component and sub-component
definitions extracted during pipeline execution.
"""

import logging

from backend.models import (
    Artifact,
    ArtifactComment,
    ArtifactDependency,
    ArtifactStatus,
    ArtifactType,
    ComponentDefinition,
    FanOutStrategy,
    StageDefinition,
    StageExecution,
)
from backend.pipeline.nodes.extract_components import (
    inject_setup_component,
    parse_components_from_content,
    parse_sub_components_from_content,
    validate_dependency_dag,
)

logger = logging.getLogger(__name__)


class ComponentManagerMixin:
    """Mixin that manages component and sub-component definitions."""

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
        all_defs = self.db.query(ComponentDefinition).filter_by(project_id=project_id).all()

        top_level = [d for d in all_defs if d.parent_key is None]
        sub_comps = [d for d in all_defs if d.parent_key is not None]
        parent_keys = {d.parent_key for d in sub_comps}

        leaves = []
        for d in top_level:
            if d.key not in parent_keys:
                leaves.append(d.key)
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

        components = inject_setup_component(components)

        old_defs = (
            self.db.query(ComponentDefinition)
            .filter_by(project_id=project_id)
            .filter(ComponentDefinition.parent_key.is_(None))
            .all()
        )
        old_keys = {d.key for d in old_defs}
        new_keys = {c["key"] for c in components}
        removed_keys = old_keys - new_keys

        if removed_keys:
            logger.info(
                "Components removed from project %s: %s",
                project_id,
                removed_keys,
            )
            for key in removed_keys:
                orphaned_arts = (
                    self.db.query(Artifact)
                    .filter_by(project_id=project_id, component_key=key)
                    .all()
                )
                orphan_art_ids = {a.id for a in orphaned_arts}

                if orphan_art_ids:
                    (
                        self.db.query(ArtifactDependency)
                        .filter(
                            (ArtifactDependency.upstream_artifact_id.in_(orphan_art_ids))
                            | (ArtifactDependency.downstream_artifact_id.in_(orphan_art_ids))
                        )
                        .delete(synchronize_session="fetch")
                    )

                if orphan_art_ids:
                    (
                        self.db.query(ArtifactComment)
                        .filter(ArtifactComment.artifact_id.in_(orphan_art_ids))
                        .delete(synchronize_session="fetch")
                    )

                (
                    self.db.query(StageExecution)
                    .filter_by(project_id=project_id, component_key=key)
                    .delete()
                )

                for art in orphaned_arts:
                    self.db.delete(art)

                (
                    self.db.query(ComponentDefinition)
                    .filter_by(project_id=project_id, parent_key=key)
                    .delete()
                )

                sub_arts = (
                    self.db.query(Artifact)
                    .filter_by(project_id=project_id)
                    .filter(Artifact.component_key.like(f"{key}.%"))
                    .all()
                )
                sub_art_ids = {a.id for a in sub_arts}
                if sub_art_ids:
                    (
                        self.db.query(ArtifactDependency)
                        .filter(
                            (ArtifactDependency.upstream_artifact_id.in_(sub_art_ids))
                            | (ArtifactDependency.downstream_artifact_id.in_(sub_art_ids))
                        )
                        .delete(synchronize_session="fetch")
                    )
                    (
                        self.db.query(ArtifactComment)
                        .filter(ArtifactComment.artifact_id.in_(sub_art_ids))
                        .delete(synchronize_session="fetch")
                    )
                (
                    self.db.query(StageExecution)
                    .filter_by(project_id=project_id)
                    .filter(StageExecution.component_key.like(f"{key}.%"))
                    .delete(synchronize_session="fetch")
                )
                for art in sub_arts:
                    self.db.delete(art)

        old_def_by_key = {d.key: d for d in old_defs}
        added = 0
        updated = 0
        for comp in components:
            existing = old_def_by_key.get(comp["key"])
            if existing:
                existing.name = comp.get("name", comp["key"])
                existing.description = comp.get("description")
                existing.dependencies = comp.get("dependencies", [])
                updated += 1
            else:
                cd = ComponentDefinition(
                    project_id=project_id,
                    key=comp["key"],
                    name=comp.get("name", comp["key"]),
                    description=comp.get("description"),
                    parent_key=None,
                    dependencies=comp.get("dependencies", []),
                )
                self.db.add(cd)
                added += 1

        if removed_keys:
            (
                self.db.query(ComponentDefinition)
                .filter_by(project_id=project_id)
                .filter(ComponentDefinition.parent_key.is_(None))
                .filter(ComponentDefinition.key.in_(removed_keys))
                .delete(synchronize_session="fetch")
            )

        self.db.flush()
        logger.info(
            "Components for project %s: %d added, %d updated, %d removed",
            project_id,
            added,
            updated,
            len(removed_keys),
        )

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
            logger.warning(
                "Sub-component dependency validation errors for %s: %s", parent_key, errors
            )

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
        logger.info(
            "Stored %d sub-components for %s in project %s",
            len(sub_components),
            parent_key,
            project_id,
        )

    def _heal_missing_entities(self, project_id: str, stage_def: StageDefinition) -> bool:
        """Attempt to re-populate missing ComponentDefinitions from approved artifacts.

        Called when a fan-out stage finds zero entities but an approved branching
        artifact exists.  Returns True if entities were healed.
        """
        fan_out = stage_def.fan_out_strategy
        healed = False

        if fan_out in (FanOutStrategy.COMPONENT, FanOutStrategy.LEAF):
            # Check for approved extract_components artifact
            artifact = (
                self.db.query(Artifact)
                .filter_by(
                    project_id=project_id,
                    artifact_type=ArtifactType.COMPONENT_MAP,
                    status=ArtifactStatus.APPROVED,
                )
                .first()
            )
            if artifact and artifact.content:
                logger.warning(
                    "Healing missing components for project %s from artifact %s",
                    project_id, artifact.id,
                )
                self._store_components(project_id, artifact.content)
                self.db.flush()
                healed = True

        if fan_out in (FanOutStrategy.SUB_COMPONENT, FanOutStrategy.LEAF):
            # Check for approved extract_sub_components artifacts per parent
            sub_artifacts = (
                self.db.query(Artifact)
                .filter_by(
                    project_id=project_id,
                    artifact_type=ArtifactType.SUB_COMPONENT_MAP,
                    status=ArtifactStatus.APPROVED,
                )
                .filter(Artifact.component_key.isnot(None))
                .all()
            )
            for sub_art in sub_artifacts:
                if sub_art.content and sub_art.component_key:
                    existing = (
                        self.db.query(ComponentDefinition)
                        .filter_by(project_id=project_id, parent_key=sub_art.component_key)
                        .count()
                    )
                    if existing == 0:
                        logger.warning(
                            "Healing missing sub-components for parent=%s from artifact %s",
                            sub_art.component_key, sub_art.id,
                        )
                        self._store_sub_components(
                            project_id, sub_art.component_key, sub_art.content
                        )
                        self.db.flush()
                        healed = True

        return healed

    async def _post_generation_hook(
        self,
        project_id: str,
        stage_def: StageDefinition,
        component_key: str | None,
        execution,
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
