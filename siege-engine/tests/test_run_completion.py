"""Tests for _try_complete_run and run completion logic."""

import pytest

from backend.models import (
    PipelineRunStatus,
    StageStatus,
)
from backend.pipeline.engine import PipelineEngine

from tests.conftest import make_execution


class TestTryCompleteRun:
    @pytest.mark.asyncio
    async def test_completes_run_when_all_executions_terminal(
        self, db, project, pipeline_config, stage_def, pipeline_run,
    ):
        ex = make_execution(
            db, project.id, run_id=pipeline_run.run_id, status=StageStatus.FAILED,
        )
        engine = PipelineEngine(db)

        await engine._try_complete_run(ex)

        db.refresh(pipeline_run)
        assert pipeline_run.status == PipelineRunStatus.FAILED
        assert pipeline_run.completed_at is not None

    @pytest.mark.asyncio
    async def test_sets_failed_when_any_execution_failed(
        self, db, project, pipeline_config, stage_def, pipeline_run,
    ):
        make_execution(
            db, project.id, run_id=pipeline_run.run_id, status=StageStatus.APPROVED,
        )
        failed_ex = make_execution(
            db, project.id, run_id=pipeline_run.run_id, status=StageStatus.FAILED,
        )
        engine = PipelineEngine(db)

        await engine._try_complete_run(failed_ex)

        db.refresh(pipeline_run)
        assert pipeline_run.status == PipelineRunStatus.FAILED

    @pytest.mark.asyncio
    async def test_sets_completed_when_all_approved(
        self, db, project, pipeline_config, stage_def, pipeline_run,
    ):
        ex = make_execution(
            db, project.id, run_id=pipeline_run.run_id, status=StageStatus.APPROVED,
        )
        engine = PipelineEngine(db)

        await engine._try_complete_run(ex)

        db.refresh(pipeline_run)
        assert pipeline_run.status == PipelineRunStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_does_not_complete_if_inflight_work(
        self, db, project, pipeline_config, stage_def, pipeline_run,
    ):
        make_execution(
            db, project.id, run_id=pipeline_run.run_id, status=StageStatus.RUNNING,
        )
        done_ex = make_execution(
            db, project.id, run_id=pipeline_run.run_id, status=StageStatus.APPROVED,
        )
        engine = PipelineEngine(db)

        await engine._try_complete_run(done_ex)

        db.refresh(pipeline_run)
        assert pipeline_run.status == PipelineRunStatus.RUNNING  # unchanged

    @pytest.mark.asyncio
    async def test_does_not_complete_if_awaiting_review(
        self, db, project, pipeline_config, stage_def, pipeline_run,
    ):
        ex = make_execution(
            db, project.id, run_id=pipeline_run.run_id, status=StageStatus.AWAITING_REVIEW,
        )
        engine = PipelineEngine(db)

        await engine._try_complete_run(ex)

        db.refresh(pipeline_run)
        assert pipeline_run.status == PipelineRunStatus.RUNNING  # unchanged

    @pytest.mark.asyncio
    async def test_noop_if_run_already_completed(
        self, db, project, pipeline_config, stage_def, pipeline_run,
    ):
        pipeline_run.status = PipelineRunStatus.COMPLETED
        db.flush()

        ex = make_execution(
            db, project.id, run_id=pipeline_run.run_id, status=StageStatus.FAILED,
        )
        engine = PipelineEngine(db)

        await engine._try_complete_run(ex)

        db.refresh(pipeline_run)
        assert pipeline_run.status == PipelineRunStatus.COMPLETED  # unchanged

    @pytest.mark.asyncio
    async def test_noop_if_no_pipeline_run(self, db, project, pipeline_config, stage_def):
        ex = make_execution(
            db, project.id, run_id="nonexistent-run-id", status=StageStatus.FAILED,
        )
        engine = PipelineEngine(db)

        # Should not raise
        await engine._try_complete_run(ex)
