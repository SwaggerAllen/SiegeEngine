"""Tests for stage execution strategies and lifecycle guarantees."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.models import (
    Artifact,
    ArtifactStatus,
    ArtifactType,
    PipelineRunStatus,
    StageExecution,
    StageStatus,
)
from backend.pipeline.engine import PipelineEngine
from backend.pipeline.stage_execution import (
    ArtifactRevisionStrategy,
    ForceRestartStrategy,
    ManualTriggerStrategy,
    RejectionRegenerateStrategy,
    SkipExecution,
    StageExecutionContext,
)

from tests.conftest import PROJECT_ID, make_artifact, make_execution


# ---------------------------------------------------------------------------
# ForceRestartStrategy
# ---------------------------------------------------------------------------


class TestForceRestartStrategy:
    @pytest.mark.asyncio
    async def test_creates_new_execution(self, db, project, pipeline_config, stage_def, pipeline_run):
        old_exec = make_execution(
            db, project.id, run_id=pipeline_run.run_id, status=StageStatus.FAILED,
        )
        engine = PipelineEngine(db)
        strategy = ForceRestartStrategy(old_exec)

        ctx = await strategy.prepare(engine)

        assert ctx.execution.id != old_exec.id
        assert ctx.execution.status == StageStatus.RUNNING
        assert ctx.execution.retry_count == (old_exec.retry_count or 0) + 1
        assert ctx.trigger == "force_restart"

    @pytest.mark.asyncio
    async def test_guard_skips_if_already_running(self, db, project, pipeline_config, stage_def, pipeline_run):
        old_exec = make_execution(
            db, project.id, run_id=pipeline_run.run_id, status=StageStatus.FAILED,
        )
        # Create a running execution for the same stage
        make_execution(
            db, project.id, run_id=pipeline_run.run_id, status=StageStatus.RUNNING,
        )
        engine = PipelineEngine(db)
        strategy = ForceRestartStrategy(old_exec)

        with pytest.raises(SkipExecution):
            await strategy.prepare(engine)

    @pytest.mark.asyncio
    async def test_resets_artifact_to_pending(self, db, project, pipeline_config, stage_def, pipeline_run):
        art = make_artifact(db, project.id, status=ArtifactStatus.REJECTED)
        old_exec = make_execution(
            db, project.id, run_id=pipeline_run.run_id,
            status=StageStatus.FAILED, artifact_id=art.id,
        )
        engine = PipelineEngine(db)
        strategy = ForceRestartStrategy(old_exec)

        await strategy.prepare(engine)

        db.refresh(art)
        assert art.status == ArtifactStatus.PENDING

    @pytest.mark.asyncio
    async def test_carries_artifact_id_to_new_execution(self, db, project, pipeline_config, stage_def, pipeline_run):
        art = make_artifact(db, project.id, status=ArtifactStatus.REJECTED)
        old_exec = make_execution(
            db, project.id, run_id=pipeline_run.run_id,
            status=StageStatus.FAILED, artifact_id=art.id,
        )
        engine = PipelineEngine(db)
        strategy = ForceRestartStrategy(old_exec)

        ctx = await strategy.prepare(engine)

        assert ctx.execution.artifact_id == art.id


# ---------------------------------------------------------------------------
# ManualTriggerStrategy
# ---------------------------------------------------------------------------


class TestManualTriggerStrategy:
    @pytest.mark.asyncio
    async def test_creates_execution(self, db, project, pipeline_config, stage_def, pipeline_run):
        engine = PipelineEngine(db)
        strategy = ManualTriggerStrategy(
            project_id=project.id,
            stage_def=stage_def,
            run_id=pipeline_run.run_id,
            config=pipeline_config,
            pipeline_run=pipeline_run,
        )

        ctx = await strategy.prepare(engine)

        assert ctx.execution.status == StageStatus.RUNNING
        assert ctx.execution.stage_key == "system_architecture"
        assert ctx.trigger == "manual_trigger"

    @pytest.mark.asyncio
    async def test_guard_skips_if_already_running(self, db, project, pipeline_config, stage_def, pipeline_run):
        make_execution(
            db, project.id, run_id=pipeline_run.run_id, status=StageStatus.RUNNING,
        )
        engine = PipelineEngine(db)
        strategy = ManualTriggerStrategy(
            project_id=project.id,
            stage_def=stage_def,
            run_id=pipeline_run.run_id,
            config=pipeline_config,
            pipeline_run=pipeline_run,
        )

        with pytest.raises(SkipExecution):
            await strategy.prepare(engine)


# ---------------------------------------------------------------------------
# RejectionRegenerateStrategy
# ---------------------------------------------------------------------------


class TestRejectionRegenerateStrategy:
    @pytest.mark.asyncio
    async def test_creates_new_execution(self, db, project, pipeline_config, stage_def, pipeline_run):
        art = make_artifact(db, project.id, status=ArtifactStatus.REJECTED)
        old_exec = make_execution(
            db, project.id, run_id=pipeline_run.run_id,
            status=StageStatus.REJECTED, artifact_id=art.id,
        )
        engine = PipelineEngine(db)
        strategy = RejectionRegenerateStrategy(old_exec)

        ctx = await strategy.prepare(engine)

        assert ctx.execution.id != old_exec.id
        assert ctx.execution.status == StageStatus.RUNNING
        assert ctx.trigger == "rejection_regenerate"
        assert ctx.error_artifact_status == ArtifactStatus.REJECTED
        assert ctx.original_artifact_id == art.id
        assert ctx.version_comment == "Artifact regenerated"

    @pytest.mark.asyncio
    async def test_sets_artifact_to_generating(self, db, project, pipeline_config, stage_def, pipeline_run):
        art = make_artifact(db, project.id, status=ArtifactStatus.REJECTED)
        old_exec = make_execution(
            db, project.id, run_id=pipeline_run.run_id,
            status=StageStatus.REJECTED, artifact_id=art.id,
        )
        engine = PipelineEngine(db)
        strategy = RejectionRegenerateStrategy(old_exec)

        await strategy.prepare(engine)

        db.refresh(art)
        assert art.status == ArtifactStatus.GENERATING

    @pytest.mark.asyncio
    async def test_guard_skips_if_already_running(self, db, project, pipeline_config, stage_def, pipeline_run):
        old_exec = make_execution(
            db, project.id, run_id=pipeline_run.run_id, status=StageStatus.REJECTED,
        )
        make_execution(
            db, project.id, run_id=pipeline_run.run_id, status=StageStatus.RUNNING,
        )
        engine = PipelineEngine(db)
        strategy = RejectionRegenerateStrategy(old_exec)

        with pytest.raises(SkipExecution):
            await strategy.prepare(engine)


# ---------------------------------------------------------------------------
# ArtifactRevisionStrategy
# ---------------------------------------------------------------------------


class TestArtifactRevisionStrategy:
    @pytest.mark.asyncio
    async def test_creates_execution_with_standalone_run(self, db, project, pipeline_config, stage_def):
        art = make_artifact(db, project.id, status=ArtifactStatus.APPROVED)
        engine = PipelineEngine(db)
        strategy = ArtifactRevisionStrategy(art.id, "please improve")

        ctx = await strategy.prepare(engine)

        assert ctx.execution.status == StageStatus.RUNNING
        assert ctx.pipeline_run is None  # standalone, no PipelineRun
        assert ctx.trigger == "revision"
        assert ctx.error_artifact_status == ArtifactStatus.APPROVED
        assert ctx.original_artifact_id == art.id
        assert ctx.version_comment == "Artifact revised"

    @pytest.mark.asyncio
    async def test_sets_artifact_to_generating(self, db, project, pipeline_config, stage_def):
        art = make_artifact(db, project.id, status=ArtifactStatus.APPROVED)
        engine = PipelineEngine(db)
        strategy = ArtifactRevisionStrategy(art.id, "improve this")

        await strategy.prepare(engine)

        db.refresh(art)
        assert art.status == ArtifactStatus.GENERATING

    @pytest.mark.asyncio
    async def test_guard_skips_if_already_running(self, db, project, pipeline_config, stage_def):
        art = make_artifact(db, project.id, status=ArtifactStatus.APPROVED)
        make_execution(
            db, project.id, status=StageStatus.RUNNING, artifact_id=art.id,
            run_id="some-run-id",
        )
        engine = PipelineEngine(db)
        strategy = ArtifactRevisionStrategy(art.id, "improve")

        with pytest.raises(SkipExecution):
            await strategy.prepare(engine)

    @pytest.mark.asyncio
    async def test_saves_feedback_as_comment(self, db, project, pipeline_config, stage_def):
        from backend.models import ArtifactComment

        art = make_artifact(db, project.id, status=ArtifactStatus.APPROVED)
        engine = PipelineEngine(db)
        strategy = ArtifactRevisionStrategy(art.id, "fix the intro section", user_id="user-1")

        await strategy.prepare(engine)

        comments = db.query(ArtifactComment).filter_by(artifact_id=art.id).all()
        assert len(comments) == 1
        assert comments[0].content == "fix the intro section"
        assert comments[0].comment_type == "feedback"
        assert comments[0].author_id == "user-1"
