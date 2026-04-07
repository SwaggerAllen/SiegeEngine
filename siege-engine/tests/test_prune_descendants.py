"""Tests for PipelineEngine.prune_descendants."""

import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.models import (
    Artifact,
    ArtifactComment,
    ArtifactDependency,
    ArtifactStatus,
    ArtifactType,
    Base,
    ComponentDefinition,
    FanOutStrategy,
    PipelineConfig,
    Project,
    StageDefinition,
    StageExecution,
    StageStatus,
)
from backend.pipeline.engine import PipelineEngine


def _id():
    return str(uuid.uuid4())


PROJECT_ID = "proj-prune-desc"


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    yield session
    session.close()


@pytest.fixture()
def setup_pipeline(db):
    """Create a project with a pipeline config containing 3 stages."""
    project = Project(id=PROJECT_ID, name="Test", git_repo_path="/tmp/test")
    db.add(project)
    db.flush()

    config = PipelineConfig(id=_id(), project_id=PROJECT_ID)
    db.add(config)
    db.flush()

    # Stage order: extract_components(3), component_architectures(4), component_plans(5)
    stages = [
        StageDefinition(
            id=_id(),
            pipeline_config_id=config.id,
            stage_key="extract_components",
            display_name="Extract Components",
            order_index=3,
            output_artifact_type="component_map",
            input_stage_keys=[],
            fan_out_strategy=FanOutStrategy.NONE,
            prompt_template_key="extract_components",
        ),
        StageDefinition(
            id=_id(),
            pipeline_config_id=config.id,
            stage_key="component_architectures",
            display_name="Component Architectures",
            order_index=4,
            output_artifact_type="component_architecture",
            input_stage_keys=["extract_components"],
            fan_out_strategy=FanOutStrategy.COMPONENT,
            prompt_template_key="component_architecture",
        ),
        StageDefinition(
            id=_id(),
            pipeline_config_id=config.id,
            stage_key="component_plans",
            display_name="Component Plans",
            order_index=5,
            output_artifact_type="component_plan",
            input_stage_keys=["component_architectures"],
            fan_out_strategy=FanOutStrategy.COMPONENT,
            prompt_template_key="component_plan",
        ),
    ]
    for s in stages:
        db.add(s)
    db.flush()
    return config


def _make_artifact(db, *, artifact_type, component_key=None, status=ArtifactStatus.APPROVED):
    art = Artifact(
        id=_id(),
        project_id=PROJECT_ID,
        artifact_type=artifact_type,
        name="Test",
        component_key=component_key,
        content="content",
        status=status,
        version=1,
    )
    db.add(art)
    db.flush()
    return art


class TestPruneDescendants:
    def test_deletes_downstream_artifacts(self, db, setup_pipeline):
        """Artifacts in stages with higher order_index are deleted."""
        anchor_art = _make_artifact(db, artifact_type=ArtifactType.COMPONENT_MAP)
        arch_art = _make_artifact(
            db, artifact_type=ArtifactType.COMPONENT_ARCHITECTURE, component_key="auth"
        )
        plan_art = _make_artifact(
            db, artifact_type=ArtifactType.COMPONENT_PLAN, component_key="auth"
        )

        engine = PipelineEngine(db)
        result = engine.prune_descendants(PROJECT_ID, "extract_components")

        assert db.get(Artifact, anchor_art.id) is not None  # anchor preserved
        assert db.get(Artifact, arch_art.id) is None
        assert db.get(Artifact, plan_art.id) is None
        assert result["pruned_artifacts"] == 2
        assert "component_architectures" in result["stages"]
        assert "component_plans" in result["stages"]

    def test_deletes_downstream_executions(self, db, setup_pipeline):
        """Executions for downstream stages are deleted."""
        ex = StageExecution(
            id=_id(),
            project_id=PROJECT_ID,
            stage_key="component_architectures",
            component_key="auth",
            status=StageStatus.APPROVED,
            run_id="run-1",
        )
        db.add(ex)
        db.flush()

        engine = PipelineEngine(db)
        result = engine.prune_descendants(PROJECT_ID, "extract_components")

        assert result["pruned_executions"] == 1
        assert db.get(StageExecution, ex.id) is None

    def test_deletes_dependency_edges(self, db, setup_pipeline):
        """Dependency edges involving downstream artifacts are cleaned up."""
        anchor_art = _make_artifact(db, artifact_type=ArtifactType.COMPONENT_MAP)
        downstream_art = _make_artifact(
            db, artifact_type=ArtifactType.COMPONENT_ARCHITECTURE, component_key="auth"
        )
        dep = ArtifactDependency(
            id=_id(),
            upstream_artifact_id=anchor_art.id,
            downstream_artifact_id=downstream_art.id,
            stage_key="component_architectures",
        )
        db.add(dep)
        db.flush()

        engine = PipelineEngine(db)
        engine.prune_descendants(PROJECT_ID, "extract_components")

        assert db.query(ArtifactDependency).count() == 0

    def test_deletes_comments(self, db, setup_pipeline):
        """Comments on downstream artifacts are deleted."""
        art = _make_artifact(
            db, artifact_type=ArtifactType.COMPONENT_ARCHITECTURE, component_key="auth"
        )
        comment = ArtifactComment(
            id=_id(),
            artifact_id=art.id,
            project_id=PROJECT_ID,
            content="test comment",
            comment_type="comment",
        )
        db.add(comment)
        db.flush()

        engine = PipelineEngine(db)
        engine.prune_descendants(PROJECT_ID, "extract_components")

        assert db.query(ArtifactComment).count() == 0

    def test_preserves_component_definitions(self, db, setup_pipeline):
        """ComponentDefinitions are preserved so pipeline knows what to regenerate."""
        _make_artifact(
            db, artifact_type=ArtifactType.COMPONENT_ARCHITECTURE, component_key="auth"
        )
        comp = ComponentDefinition(
            id=_id(),
            project_id=PROJECT_ID,
            key="auth",
            name="Auth",
        )
        db.add(comp)
        db.flush()

        engine = PipelineEngine(db)
        engine.prune_descendants(PROJECT_ID, "extract_components")

        assert db.query(ComponentDefinition).filter_by(key="auth").count() == 1

    def test_no_downstream_returns_empty(self, db, setup_pipeline):
        """Pruning from the last stage returns empty result."""
        engine = PipelineEngine(db)
        result = engine.prune_descendants(PROJECT_ID, "component_plans")

        assert result["pruned_artifacts"] == 0
        assert result["pruned_executions"] == 0
        assert result["stages"] == []

    def test_raises_for_missing_config(self, db):
        """Raises if project has no pipeline config."""
        engine = PipelineEngine(db)
        with pytest.raises(ValueError, match="No pipeline config"):
            engine.prune_descendants("no-such-project", "extract_components")

    def test_raises_for_unknown_stage(self, db, setup_pipeline):
        """Raises if stage_key doesn't exist."""
        engine = PipelineEngine(db)
        with pytest.raises(ValueError, match="not found"):
            engine.prune_descendants(PROJECT_ID, "nonexistent_stage")

    def test_preserves_anchor_stage_artifacts(self, db, setup_pipeline):
        """Artifacts AT the anchor stage are not touched."""
        anchor_art = _make_artifact(db, artifact_type=ArtifactType.COMPONENT_MAP)

        engine = PipelineEngine(db)
        engine.prune_descendants(PROJECT_ID, "extract_components")

        assert db.get(Artifact, anchor_art.id) is not None
