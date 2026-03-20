"""Tests for PipelineEngine.prune_artifact."""

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
    StageExecution,
    StageStatus,
)
from backend.pipeline.engine import PipelineEngine


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    yield session
    session.close()


def _id():
    return str(uuid.uuid4())


PROJECT_ID = "proj-1"


def _make_artifact(
    db,
    *,
    component_key=None,
    artifact_type=ArtifactType.COMPONENT_PLAN,
    status=ArtifactStatus.APPROVED,
):
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


class TestPruneArtifact:
    def test_deletes_artifact(self, db):
        art = _make_artifact(db)
        engine = PipelineEngine(db)
        engine.prune_artifact(PROJECT_ID, art.id)
        assert db.get(Artifact, art.id) is None

    def test_deletes_dependency_edges(self, db):
        art = _make_artifact(db)
        upstream = _make_artifact(db)
        dep = ArtifactDependency(
            id=_id(),
            upstream_artifact_id=upstream.id,
            downstream_artifact_id=art.id,
            stage_key="component_plans",
        )
        db.add(dep)
        db.flush()

        engine = PipelineEngine(db)
        engine.prune_artifact(PROJECT_ID, art.id)

        assert db.query(ArtifactDependency).filter_by(downstream_artifact_id=art.id).count() == 0

    def test_deletes_comments(self, db):
        art = _make_artifact(db)
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
        engine.prune_artifact(PROJECT_ID, art.id)

        assert db.query(ArtifactComment).filter_by(artifact_id=art.id).count() == 0

    def test_deletes_stage_executions(self, db):
        art = _make_artifact(db)
        exe = StageExecution(
            id=_id(),
            project_id=PROJECT_ID,
            stage_key="component_plans",
            component_key=art.component_key,
            status=StageStatus.APPROVED,
            artifact_id=art.id,
            run_id="run-1",
        )
        db.add(exe)
        db.flush()

        engine = PipelineEngine(db)
        engine.prune_artifact(PROJECT_ID, art.id)

        assert db.query(StageExecution).filter_by(artifact_id=art.id).count() == 0

    def test_preserves_component_definition(self, db):
        """Prune should NOT delete the ComponentDefinition so the fanout
        parent still knows the entity exists and regenerates it."""
        art = _make_artifact(db, component_key="auth")
        comp_def = ComponentDefinition(
            id=_id(),
            project_id=PROJECT_ID,
            key="auth",
            name="Auth",
            parent_key=None,
        )
        db.add(comp_def)
        db.flush()

        engine = PipelineEngine(db)
        engine.prune_artifact(PROJECT_ID, art.id)

        # Artifact is gone but ComponentDefinition survives
        assert db.get(Artifact, art.id) is None
        remaining = (
            db.query(ComponentDefinition).filter_by(project_id=PROJECT_ID, key="auth").count()
        )
        assert remaining == 1

    def test_raises_for_wrong_project(self, db):
        art = _make_artifact(db)
        engine = PipelineEngine(db)
        with pytest.raises(ValueError, match="does not belong"):
            engine.prune_artifact("other-project", art.id)

    def test_raises_for_missing_artifact(self, db):
        engine = PipelineEngine(db)
        with pytest.raises(ValueError, match="not found"):
            engine.prune_artifact(PROJECT_ID, "nonexistent")

    def test_raises_for_generating_artifact(self, db):
        art = _make_artifact(db, status=ArtifactStatus.GENERATING)
        engine = PipelineEngine(db)
        with pytest.raises(ValueError, match="currently being generated"):
            engine.prune_artifact(PROJECT_ID, art.id)

    def test_raises_for_ai_reviewing_artifact(self, db):
        art = _make_artifact(db, status=ArtifactStatus.AI_REVIEWING)
        engine = PipelineEngine(db)
        with pytest.raises(ValueError, match="currently being generated"):
            engine.prune_artifact(PROJECT_ID, art.id)

    def test_prune_without_component_key(self, db):
        """Pruning an artifact with no component_key still works."""
        art = _make_artifact(db, component_key=None)
        engine = PipelineEngine(db)
        engine.prune_artifact(PROJECT_ID, art.id)
        assert db.get(Artifact, art.id) is None
