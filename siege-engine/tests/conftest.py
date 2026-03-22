"""Shared test fixtures for pipeline tests."""

import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.database import Base
from backend.models import (
    Artifact,
    ArtifactStatus,
    ArtifactType,
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


def _id():
    return str(uuid.uuid4())


PROJECT_ID = _id()


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    yield session
    session.close()


@pytest.fixture()
def project(db):
    p = Project(
        id=PROJECT_ID,
        name="Test Project",
        git_repo_path="/tmp/test-repo",
    )
    db.add(p)
    db.flush()
    return p


@pytest.fixture()
def pipeline_config(db, project):
    config = PipelineConfig(
        id=_id(),
        project_id=project.id,
    )
    db.add(config)
    db.flush()
    return config


@pytest.fixture()
def stage_def(db, pipeline_config):
    sd = StageDefinition(
        id=_id(),
        pipeline_config_id=pipeline_config.id,
        stage_key="system_architecture",
        display_name="System Architecture",
        order_index=1,
        output_artifact_type="system_architecture",
        input_stage_keys=[],
        fan_out_strategy=FanOutStrategy.NONE,
        prompt_template_key="architecture",
    )
    db.add(sd)
    db.flush()
    return sd


@pytest.fixture()
def pipeline_run(db, project):
    run = PipelineRun(
        id=_id(),
        project_id=project.id,
        run_number=1,
        status=PipelineRunStatus.RUNNING,
        stop_point=StopPoint.EVERY_ARTIFACT,
    )
    db.add(run)
    db.flush()
    return run


def make_execution(
    db,
    project_id,
    stage_key="system_architecture",
    *,
    run_id=None,
    status=StageStatus.FAILED,
    component_key=None,
    artifact_id=None,
    retry_count=0,
):
    ex = StageExecution(
        id=_id(),
        project_id=project_id,
        stage_key=stage_key,
        component_key=component_key,
        status=status,
        run_id=run_id,
        artifact_id=artifact_id,
        retry_count=retry_count,
    )
    db.add(ex)
    db.flush()
    return ex


def make_artifact(
    db,
    project_id,
    *,
    artifact_type=ArtifactType.SYSTEM_ARCHITECTURE,
    status=ArtifactStatus.PENDING,
    content="test content",
    component_key=None,
):
    art = Artifact(
        id=_id(),
        project_id=project_id,
        artifact_type=artifact_type,
        name="Test Artifact",
        component_key=component_key,
        content=content,
        status=status,
        version=1,
    )
    db.add(art)
    db.flush()
    return art
