"""Tests for pipeline reconciliation logic."""

import pytest

from backend.models import (
    ArtifactStatus,
    PipelineRunStatus,
    StageStatus,
)
from backend.pipeline import events as evt
from backend.pipeline.event_store import EventStore
from backend.pipeline.reconcile import reconcile_project

from tests.conftest import make_artifact, make_execution


class TestReconcileProject:
    def test_no_corrections_when_clean(self, db, project, pipeline_config, stage_def):
        corrections = reconcile_project(db, project.id)
        assert corrections == []

    def test_fixes_orphaned_running_execution(self, db, project, pipeline_config, stage_def, pipeline_run):
        """An execution RUNNING in DB but not tracked by snapshot → FAILED."""
        ex = make_execution(
            db, project.id, run_id=pipeline_run.run_id, status=StageStatus.RUNNING,
        )
        db.commit()

        corrections = reconcile_project(db, project.id)

        db.refresh(ex)
        assert ex.status == StageStatus.FAILED
        orphan_corrections = [c for c in corrections if c["type"] == "orphan_execution"]
        assert len(orphan_corrections) == 1
        assert orphan_corrections[0]["id"] == ex.id

    def test_fixes_zombie_run(self, db, project, pipeline_config, stage_def, pipeline_run):
        """A RUNNING run with no active executions → FAILED."""
        # Create a failed execution (no active work left)
        make_execution(
            db, project.id, run_id=pipeline_run.run_id, status=StageStatus.FAILED,
        )

        # Emit run_created event so snapshot thinks run is running
        es = EventStore(db)
        es.emit(project.id, evt.RUN_CREATED, {
            "run_id": pipeline_run.run_id,
            "run_number": pipeline_run.run_number,
            "ai_loops": 1,
            "stop_point": "every_artifact",
        }, run_id=pipeline_run.run_id)
        db.commit()

        corrections = reconcile_project(db, project.id)

        db.refresh(pipeline_run)
        assert pipeline_run.status == PipelineRunStatus.FAILED
        zombie_corrections = [c for c in corrections if c["type"] == "zombie_run"]
        assert len(zombie_corrections) == 1

    def test_does_not_kill_run_with_active_work(self, db, project, pipeline_config, stage_def, pipeline_run):
        """A RUNNING run with an AWAITING_REVIEW execution should stay RUNNING."""
        make_execution(
            db, project.id, run_id=pipeline_run.run_id,
            status=StageStatus.AWAITING_REVIEW,
        )

        # Emit run_created event
        es = EventStore(db)
        es.emit(project.id, evt.RUN_CREATED, {
            "run_id": pipeline_run.run_id,
            "run_number": pipeline_run.run_number,
            "ai_loops": 1,
            "stop_point": "every_artifact",
        }, run_id=pipeline_run.run_id)
        db.commit()

        corrections = reconcile_project(db, project.id)

        db.refresh(pipeline_run)
        assert pipeline_run.status == PipelineRunStatus.RUNNING
        zombie_corrections = [c for c in corrections if c["type"] == "zombie_run"]
        assert len(zombie_corrections) == 0

    def test_syncs_artifact_status_from_snapshot(self, db, project, pipeline_config, stage_def, pipeline_run):
        """Artifact status in DB should be synced to match snapshot."""
        art = make_artifact(db, project.id, status=ArtifactStatus.PENDING)

        # Emit events that set the artifact to approved in the snapshot
        es = EventStore(db)
        es.emit(project.id, evt.RUN_CREATED, {
            "run_id": pipeline_run.run_id,
            "run_number": 1,
            "ai_loops": 1,
            "stop_point": "every_artifact",
        }, run_id=pipeline_run.run_id)

        ex = make_execution(
            db, project.id, run_id=pipeline_run.run_id,
            status=StageStatus.APPROVED, artifact_id=art.id,
        )
        es.emit(project.id, evt.STAGE_STARTED, {
            "execution_id": ex.id,
            "stage_key": stage_def.stage_key,
            "component_key": None,
            "artifact_id": art.id,
            "trigger": "pipeline_run",
            "retry_count": 0,
        }, run_id=pipeline_run.run_id)
        es.emit(project.id, evt.HUMAN_APPROVED, {
            "execution_id": ex.id,
            "stage_key": stage_def.stage_key,
            "component_key": None,
            "artifact_id": art.id,
        }, run_id=pipeline_run.run_id)
        db.commit()

        corrections = reconcile_project(db, project.id)

        db.refresh(art)
        assert art.status == ArtifactStatus.APPROVED
        art_corrections = [c for c in corrections if c["type"] == "artifact_status"]
        assert len(art_corrections) == 1
