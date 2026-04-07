"""Tests for project cloning."""

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
    InputDocument,
    PipelineConfig,
    PipelineSnapshot,
    Project,
    StageDefinition,
    StageExecution,
    StageStatus,
)
from backend.projects.service import clone_project


def _id():
    return str(uuid.uuid4())


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    yield session
    session.close()


@pytest.fixture()
def source_project(db):
    """Create a source project with config, artifacts, components, etc."""
    project = Project(id=_id(), name="Original", description="desc", git_repo_path="/tmp/orig")
    db.add(project)
    db.flush()

    # Pipeline config + one stage
    config = PipelineConfig(id=_id(), project_id=project.id, default_model="test-model")
    db.add(config)
    db.flush()

    stage = StageDefinition(
        id=_id(),
        pipeline_config_id=config.id,
        stage_key="feature_expansion",
        display_name="Feature Expansion",
        order_index=1,
        output_artifact_type="feature_expansion",
        input_stage_keys=[],
        fan_out_strategy=FanOutStrategy.NONE,
        prompt_template_key="feature_expansion",
    )
    db.add(stage)
    db.flush()

    # Artifacts
    art1 = Artifact(
        id=_id(),
        project_id=project.id,
        artifact_type=ArtifactType.PROJECT_DOC,
        name="Project Doc",
        content="project doc content",
        status=ArtifactStatus.APPROVED,
        version=1,
        file_path="project_doc.md",
        git_commit_sha="abc123",
    )
    art2 = Artifact(
        id=_id(),
        project_id=project.id,
        artifact_type=ArtifactType.FEATURE_EXPANSION,
        name="Feature Expansion",
        content="features",
        status=ArtifactStatus.APPROVED,
        version=2,
        file_path="feature_expansion.md",
    )
    db.add_all([art1, art2])
    db.flush()

    # Dependency
    dep = ArtifactDependency(
        id=_id(),
        upstream_artifact_id=art1.id,
        downstream_artifact_id=art2.id,
        stage_key="feature_expansion",
    )
    db.add(dep)

    # Component definition
    comp = ComponentDefinition(
        id=_id(),
        project_id=project.id,
        key="auth",
        name="Auth Service",
        description="Authentication",
        dag_type="domain",
    )
    db.add(comp)

    # Input document
    doc = InputDocument(
        id=_id(),
        project_id=project.id,
        name="API Spec",
        content="spec content",
        doc_type="reference",
    )
    db.add(doc)

    # Comment
    comment = ArtifactComment(
        id=_id(),
        artifact_id=art1.id,
        project_id=project.id,
        content="looks good",
        comment_type="comment",
    )
    db.add(comment)

    # Execution (should NOT be cloned)
    ex = StageExecution(
        id=_id(),
        project_id=project.id,
        stage_key="feature_expansion",
        status=StageStatus.APPROVED,
        run_id="run-1",
        artifact_id=art2.id,
    )
    db.add(ex)

    db.commit()
    return project


class TestCloneProject:
    def test_creates_new_project(self, db, source_project):
        clone = clone_project(db, source_project.id)
        assert clone.id != source_project.id
        assert clone.name == "Original (copy)"
        assert clone.description == "desc"

    def test_custom_name(self, db, source_project):
        clone = clone_project(db, source_project.id, new_name="My Checkpoint")
        assert clone.name == "My Checkpoint"

    def test_clones_pipeline_config(self, db, source_project):
        clone = clone_project(db, source_project.id)
        config = db.query(PipelineConfig).filter_by(project_id=clone.id).first()
        assert config is not None
        assert config.default_model == "test-model"

    def test_clones_stage_definitions(self, db, source_project):
        clone = clone_project(db, source_project.id)
        config = db.query(PipelineConfig).filter_by(project_id=clone.id).first()
        stages = config.stages
        assert len(stages) == 1
        assert stages[0].stage_key == "feature_expansion"

    def test_clones_artifacts_with_new_ids(self, db, source_project):
        clone = clone_project(db, source_project.id)
        src_arts = db.query(Artifact).filter_by(project_id=source_project.id).all()
        clone_arts = db.query(Artifact).filter_by(project_id=clone.id).all()
        assert len(clone_arts) == len(src_arts)
        src_ids = {a.id for a in src_arts}
        clone_ids = {a.id for a in clone_arts}
        assert src_ids.isdisjoint(clone_ids)

    def test_clones_artifact_content(self, db, source_project):
        clone = clone_project(db, source_project.id)
        arts = db.query(Artifact).filter_by(project_id=clone.id).all()
        contents = {a.artifact_type: a.content for a in arts}
        assert contents[ArtifactType.PROJECT_DOC] == "project doc content"
        assert contents[ArtifactType.FEATURE_EXPANSION] == "features"

    def test_clones_artifact_dependencies(self, db, source_project):
        clone = clone_project(db, source_project.id)
        clone_arts = db.query(Artifact).filter_by(project_id=clone.id).all()
        clone_art_ids = {a.id for a in clone_arts}
        deps = (
            db.query(ArtifactDependency)
            .filter(ArtifactDependency.upstream_artifact_id.in_(clone_art_ids))
            .all()
        )
        assert len(deps) == 1
        assert deps[0].downstream_artifact_id in clone_art_ids

    def test_clones_component_definitions(self, db, source_project):
        clone = clone_project(db, source_project.id)
        comps = db.query(ComponentDefinition).filter_by(project_id=clone.id).all()
        assert len(comps) == 1
        assert comps[0].key == "auth"
        assert comps[0].dag_type == "domain"

    def test_clones_input_documents(self, db, source_project):
        clone = clone_project(db, source_project.id)
        docs = db.query(InputDocument).filter_by(project_id=clone.id).all()
        assert len(docs) == 1
        assert docs[0].name == "API Spec"

    def test_clones_comments(self, db, source_project):
        clone = clone_project(db, source_project.id)
        comments = db.query(ArtifactComment).filter_by(project_id=clone.id).all()
        assert len(comments) == 1
        assert comments[0].content == "looks good"

    def test_does_not_clone_executions(self, db, source_project):
        clone = clone_project(db, source_project.id)
        execs = db.query(StageExecution).filter_by(project_id=clone.id).all()
        assert len(execs) == 0

    def test_builds_snapshot(self, db, source_project):
        clone = clone_project(db, source_project.id)
        snap = db.query(PipelineSnapshot).filter_by(project_id=clone.id).first()
        assert snap is not None
        assert snap.is_running is False
        # Both artifacts should be in snapshot
        assert len(snap.artifact_statuses) == 2
        for status in snap.artifact_statuses.values():
            assert status == "approved"

    def test_snapshot_has_stage_statuses(self, db, source_project):
        clone = clone_project(db, source_project.id)
        snap = db.query(PipelineSnapshot).filter_by(project_id=clone.id).first()
        # feature_expansion stage should be approved
        assert "feature_expansion" in snap.stage_statuses

    def test_raises_for_missing_source(self, db):
        with pytest.raises(ValueError, match="not found"):
            clone_project(db, "nonexistent")

    def test_source_project_unchanged(self, db, source_project):
        """Cloning doesn't modify the source project."""
        src_art_count_before = db.query(Artifact).filter_by(project_id=source_project.id).count()
        clone_project(db, source_project.id)
        src_art_count_after = db.query(Artifact).filter_by(project_id=source_project.id).count()
        assert src_art_count_before == src_art_count_after
