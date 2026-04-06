"""Component management mixin for PipelineEngine.

Handles storing, updating, and retrieving component and sub-component
definitions extracted during pipeline execution.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

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
    parse_dual_components_from_content,
    parse_sub_components_from_content,
    validate_dependency_dag,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from backend.pipeline.event_store import EventStore

logger = logging.getLogger(__name__)


class ComponentManagerMixin:
    """Mixin that manages component and sub-component definitions."""

    # Provided by PipelineEngine (host class)
    db: Session
    events: EventStore

    def _get_components(self, project_id: str, dag_type: str = "domain") -> list[dict]:
        """Get top-level components from ComponentDefinition table."""
        defs = (
            self.db.query(ComponentDefinition)
            .filter_by(project_id=project_id, dag_type=dag_type)
            .filter(ComponentDefinition.parent_key.is_(None))
            .all()
        )
        return [
            {
                "key": d.key,
                "name": d.name,
                "description": d.description,
                "dependencies": d.dependencies or [],
                **({"domain_parents": d.domain_parents} if d.domain_parents else {}),
            }
            for d in defs
        ]

    def _get_sub_component_defs(
        self, project_id: str, dag_type: str = "domain"
    ) -> list[ComponentDefinition]:
        """Get all sub-components from ComponentDefinition table."""
        return (
            self.db.query(ComponentDefinition)
            .filter_by(project_id=project_id, dag_type=dag_type)
            .filter(ComponentDefinition.parent_key.isnot(None))
            .all()
        )

    def _get_leaf_keys(self, project_id: str, dag_type: str = "domain") -> list[str]:
        """Get leaf entity keys (components without sub-components + all sub-components)."""
        all_defs = (
            self.db.query(ComponentDefinition)
            .filter_by(project_id=project_id, dag_type=dag_type)
            .all()
        )

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

    # All fan-out stages keyed by top-level component key.
    _COMPONENT_FANOUT_STAGES = [
        "component_architectures",
        "extract_sub_components",
        "component_plans",
    ]
    _FE_COMPONENT_FANOUT_STAGES = [
        "fe_component_architectures",
        "fe_extract_sub_components",
        "fe_component_plans",
    ]

    def _store_components(self, project_id: str, content: str):
        """Parse extract_components output and create ComponentDefinition records.

        Handles both domain and frontend components from dual-format output.
        When component keys are removed (including renames like
        ``identity_and_tenancy`` → ``identity_tenancy``), this method:
        1. Deletes orphaned DB records (artifacts, executions, definitions).
        2. Emits ARTIFACT_PRUNED events so the event-sourced snapshot drops
           stale stage statuses, execution-map entries, errors, and triggers
           for the old keys.
        """
        from backend.pipeline import events as evt

        dual = parse_dual_components_from_content(content)
        components = dual["domain"]
        frontend_components = dual["frontend"]

        if not components and not frontend_components:
            logger.warning("No components parsed from extract_components output")
            return

        # Store frontend components (if any) before domain to keep method tidy
        if frontend_components:
            self._store_frontend_components(project_id, frontend_components)

        if not components:
            return

        errors = validate_dependency_dag(components)
        if errors:
            logger.warning("Component dependency validation errors: %s", errors)

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

            # ── Collect orphan info BEFORE deleting DB rows ──────────
            orphan_pruning: list[dict] = []
            for key in removed_keys:
                orphaned_arts = (
                    self.db.query(Artifact)
                    .filter_by(project_id=project_id, component_key=key)
                    .all()
                )
                # Record pruning info for every fan-out stage that uses
                # this component key, so the snapshot is fully cleaned.
                for art in orphaned_arts:
                    for stage_key in self._COMPONENT_FANOUT_STAGES:
                        orphan_pruning.append(
                            {
                                "artifact_id": art.id,
                                "stage_key": stage_key,
                                "component_key": key,
                            }
                        )
                # Even if no artifact exists, prune the stage entries
                # (e.g., failed executions with no artifact).
                if not orphaned_arts:
                    for stage_key in self._COMPONENT_FANOUT_STAGES:
                        orphan_pruning.append(
                            {
                                "artifact_id": f"__orphan__{key}",
                                "stage_key": stage_key,
                                "component_key": key,
                            }
                        )

                # ── Delete orphaned DB rows ──────────────────────────
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

            # ── Emit pruning events AFTER DB cleanup ─────────────────
            # These events update the event-sourced snapshot so it no
            # longer contains stale entries for removed component keys.
            for info in orphan_pruning:
                self.events.emit(
                    project_id,
                    evt.ARTIFACT_PRUNED,
                    {
                        "artifact_id": info["artifact_id"],
                        "stage_key": info["stage_key"],
                        "component_key": info["component_key"],
                    },
                )
            if orphan_pruning:
                logger.info(
                    "Emitted %d ARTIFACT_PRUNED events for removed components %s",
                    len(orphan_pruning),
                    removed_keys,
                )

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

    def _store_frontend_components(self, project_id: str, components: list[dict]):
        """Store frontend ComponentDefinition records (called from _store_components).

        Uses the same orphan-cleanup pattern as domain components but targets
        frontend-specific fan-out stages.
        """
        from backend.pipeline import events as evt

        errors = validate_dependency_dag(components)
        if errors:
            logger.warning("Frontend component dependency validation errors: %s", errors)

        old_defs = (
            self.db.query(ComponentDefinition)
            .filter_by(project_id=project_id, dag_type="frontend")
            .filter(ComponentDefinition.parent_key.is_(None))
            .all()
        )
        old_keys = {d.key for d in old_defs}
        new_keys = {c["key"] for c in components}
        removed_keys = old_keys - new_keys

        if removed_keys:
            logger.info(
                "Frontend components removed from project %s: %s",
                project_id,
                removed_keys,
            )
            orphan_pruning: list[dict] = []
            for key in removed_keys:
                orphaned_arts = (
                    self.db.query(Artifact)
                    .filter_by(project_id=project_id, component_key=key)
                    .filter(
                        Artifact.artifact_type.in_(
                            [
                                ArtifactType.FRONTEND_COMPONENT_ARCHITECTURE,
                                ArtifactType.FRONTEND_COMPONENT_PLAN,
                                ArtifactType.FRONTEND_SUB_COMPONENT_MAP,
                                ArtifactType.FRONTEND_SUB_COMPONENT_ARCHITECTURE,
                                ArtifactType.FRONTEND_SUB_COMPONENT_PLAN,
                                ArtifactType.FRONTEND_CODE,
                                ArtifactType.FRONTEND_CODE_REVIEW,
                            ]
                        )
                    )
                    .all()
                )
                for art in orphaned_arts:
                    for stage_key in self._FE_COMPONENT_FANOUT_STAGES:
                        orphan_pruning.append(
                            {
                                "artifact_id": art.id,
                                "stage_key": stage_key,
                                "component_key": key,
                            }
                        )
                if not orphaned_arts:
                    for stage_key in self._FE_COMPONENT_FANOUT_STAGES:
                        orphan_pruning.append(
                            {
                                "artifact_id": f"__orphan__{key}",
                                "stage_key": stage_key,
                                "component_key": key,
                            }
                        )

                orphan_art_ids = {a.id for a in orphaned_arts}
                if orphan_art_ids:
                    self.db.query(ArtifactDependency).filter(
                        (ArtifactDependency.upstream_artifact_id.in_(orphan_art_ids))
                        | (ArtifactDependency.downstream_artifact_id.in_(orphan_art_ids))
                    ).delete(synchronize_session="fetch")
                    self.db.query(ArtifactComment).filter(
                        ArtifactComment.artifact_id.in_(orphan_art_ids)
                    ).delete(synchronize_session="fetch")

                self.db.query(StageExecution).filter_by(
                    project_id=project_id, component_key=key
                ).filter(StageExecution.stage_key.like("fe_%")).delete(synchronize_session="fetch")

                for art in orphaned_arts:
                    self.db.delete(art)

                self.db.query(ComponentDefinition).filter_by(
                    project_id=project_id, parent_key=key, dag_type="frontend"
                ).delete()

            for info in orphan_pruning:
                self.events.emit(
                    project_id,
                    evt.ARTIFACT_PRUNED,
                    {
                        "artifact_id": info["artifact_id"],
                        "stage_key": info["stage_key"],
                        "component_key": info["component_key"],
                    },
                )

        old_def_by_key = {d.key: d for d in old_defs}
        added = 0
        updated = 0
        for comp in components:
            existing = old_def_by_key.get(comp["key"])
            if existing:
                existing.name = comp.get("name", comp["key"])
                existing.description = comp.get("description")
                existing.dependencies = comp.get("dependencies", [])
                existing.domain_parents = comp.get("domain_parents", [])
                updated += 1
            else:
                cd = ComponentDefinition(
                    project_id=project_id,
                    key=comp["key"],
                    name=comp.get("name", comp["key"]),
                    description=comp.get("description"),
                    parent_key=None,
                    dependencies=comp.get("dependencies", []),
                    dag_type="frontend",
                    domain_parents=comp.get("domain_parents", []),
                )
                self.db.add(cd)
                added += 1

        if removed_keys:
            self.db.query(ComponentDefinition).filter_by(
                project_id=project_id, dag_type="frontend"
            ).filter(
                ComponentDefinition.parent_key.is_(None),
                ComponentDefinition.key.in_(removed_keys),
            ).delete(synchronize_session="fetch")

        self.db.flush()
        logger.info(
            "Frontend components for project %s: %d added, %d updated, %d removed",
            project_id,
            added,
            updated,
            len(removed_keys),
        )

    def _store_sub_components(
        self, project_id: str, parent_key: str, content: str, dag_type: str = "domain"
    ):
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
            .filter_by(project_id=project_id, parent_key=parent_key, dag_type=dag_type)
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
                dag_type=dag_type,
            )
            self.db.add(cd)

        self.db.flush()
        logger.info(
            "Stored %d sub-components for %s in project %s (dag_type=%s)",
            len(sub_components),
            parent_key,
            project_id,
            dag_type,
        )

    def _heal_missing_entities(self, project_id: str, stage_def: StageDefinition) -> bool:
        """Attempt to re-populate missing ComponentDefinitions from approved artifacts.

        Called when a fan-out stage finds zero entities but an approved branching
        artifact exists.  Returns True if entities were healed.
        """
        fan_out = stage_def.fan_out_strategy
        is_frontend = stage_def.stage_key.startswith("fe_")
        healed = False

        if fan_out in (FanOutStrategy.COMPONENT, FanOutStrategy.LEAF):
            if is_frontend:
                # Frontend components are extracted from the same component_map artifact
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
                        "Healing missing frontend components for project %s from artifact %s",
                        project_id,
                        artifact.id,
                    )
                    self._store_components(project_id, artifact.content)
                    self.db.flush()
                    healed = True
            else:
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
                        project_id,
                        artifact.id,
                    )
                    self._store_components(project_id, artifact.content)
                    self.db.flush()
                    healed = True

        if fan_out in (FanOutStrategy.SUB_COMPONENT, FanOutStrategy.LEAF):
            sub_map_type = (
                ArtifactType.FRONTEND_SUB_COMPONENT_MAP
                if is_frontend
                else ArtifactType.SUB_COMPONENT_MAP
            )
            dag_type = "frontend" if is_frontend else "domain"
            sub_artifacts = (
                self.db.query(Artifact)
                .filter_by(
                    project_id=project_id,
                    artifact_type=sub_map_type,
                    status=ArtifactStatus.APPROVED,
                )
                .filter(Artifact.component_key.isnot(None))
                .all()
            )
            for sub_art in sub_artifacts:
                if sub_art.content and sub_art.component_key:
                    existing = (
                        self.db.query(ComponentDefinition)
                        .filter_by(
                            project_id=project_id,
                            parent_key=sub_art.component_key,
                            dag_type=dag_type,
                        )
                        .count()
                    )
                    if existing == 0:
                        logger.warning(
                            "Healing missing sub-components for parent=%s from artifact %s",
                            sub_art.component_key,
                            sub_art.id,
                        )
                        self._store_sub_components(
                            project_id, sub_art.component_key, sub_art.content, dag_type=dag_type
                        )
                        self.db.flush()
                        healed = True

        return healed

    def reparse_fanout(self, project_id: str, artifact_id: str) -> dict:
        """Re-parse a fanout artifact to restore missing ComponentDefinitions.

        Works on approved extract_components or extract_sub_components artifacts.
        Re-runs the same parsing logic used during post-generation to reconcile
        ComponentDefinition rows with the artifact's current text content.

        Also emits ARTIFACT_PRUNED events for any removed components so the
        event-sourced snapshot stays in sync (clears stale stage statuses,
        execution map entries, etc.).

        Returns a summary of what changed.
        """
        artifact = self.db.get(Artifact, artifact_id)
        if not artifact:
            raise ValueError("Artifact not found")
        if artifact.project_id != project_id:
            raise ValueError("Artifact does not belong to this project")
        if not artifact.content:
            raise ValueError("Artifact has no content to parse")

        before_keys: set[str] = set()
        after_keys: set[str] = set()
        # Snapshot dependency state before re-parse to detect updates
        before_deps: dict[str, list[str]] = {}

        fanout_types = {
            ArtifactType.COMPONENT_MAP,
            ArtifactType.SUB_COMPONENT_MAP,
            ArtifactType.FRONTEND_SUB_COMPONENT_MAP,
        }
        if artifact.artifact_type not in fanout_types:
            raise ValueError(
                f"Artifact type {artifact.artifact_type.value} is not a fanout artifact"
            )

        if artifact.artifact_type == ArtifactType.COMPONENT_MAP:
            old_defs = (
                self.db.query(ComponentDefinition)
                .filter_by(project_id=project_id)
                .filter(ComponentDefinition.parent_key.is_(None))
                .all()
            )
            before_keys = {d.key for d in old_defs}
            before_deps = {d.key: sorted(d.dependencies or []) for d in old_defs}

            # _store_components handles orphan cleanup + pruning events internally.
            self._store_components(project_id, artifact.content)
            self.db.commit()

            new_defs = (
                self.db.query(ComponentDefinition)
                .filter_by(project_id=project_id)
                .filter(ComponentDefinition.parent_key.is_(None))
                .all()
            )
            after_keys = {d.key for d in new_defs}
            after_deps = {d.key: sorted(d.dependencies or []) for d in new_defs}
        elif artifact.artifact_type in (
            ArtifactType.SUB_COMPONENT_MAP,
            ArtifactType.FRONTEND_SUB_COMPONENT_MAP,
        ):
            parent_key = artifact.component_key
            if not parent_key:
                raise ValueError("Sub-component map artifact has no component_key")
            dag_type = (
                "frontend"
                if artifact.artifact_type == ArtifactType.FRONTEND_SUB_COMPONENT_MAP
                else "domain"
            )
            old_defs = (
                self.db.query(ComponentDefinition)
                .filter_by(project_id=project_id, parent_key=parent_key, dag_type=dag_type)
                .all()
            )
            before_keys = {d.key for d in old_defs}
            before_deps = {d.key: sorted(d.dependencies or []) for d in old_defs}

            self._store_sub_components(project_id, parent_key, artifact.content, dag_type=dag_type)
            self.db.commit()

            new_defs = (
                self.db.query(ComponentDefinition)
                .filter_by(project_id=project_id, parent_key=parent_key, dag_type=dag_type)
                .all()
            )
            after_keys = {d.key for d in new_defs}
            after_deps = {d.key: sorted(d.dependencies or []) for d in new_defs}

        added = after_keys - before_keys
        removed = before_keys - after_keys
        # Count components whose dependencies changed
        updated = {
            k for k in (before_keys & after_keys) if before_deps.get(k, []) != after_deps.get(k, [])
        }
        logger.info(
            "Reparsed fanout artifact %s: added=%s removed=%s updated=%s",
            artifact_id,
            added,
            removed,
            updated,
        )
        return {
            "added": sorted(added),
            "removed": sorted(removed),
            "updated": sorted(updated),
            "total": len(after_keys),
        }

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
            self._store_sub_components(
                project_id, component_key, artifact.content, dag_type="domain"
            )
        elif stage_def.stage_key == "fe_extract_sub_components" and component_key:
            self._store_sub_components(
                project_id, component_key, artifact.content, dag_type="frontend"
            )
