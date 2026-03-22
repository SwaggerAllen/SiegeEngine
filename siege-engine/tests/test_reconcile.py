"""Tests for pipeline reconciliation logic."""


from backend.models import (
    ArtifactStatus,
    PipelineRunStatus,
    StageStatus,
)
from backend.pipeline import events as evt
from backend.pipeline.event_store import EventStore
from backend.pipeline.reconcile import reconcile_project
from backend.pipeline.reducer import apply_event, empty_snapshot
from tests.conftest import make_artifact, make_execution


class TestPipelineResetCancelsRunningRuns:
    """pipeline_reset should mark all 'running' run_status entries as cancelled."""

    def test_running_runs_cancelled_on_reset(self):
        snap = empty_snapshot()
        snap = apply_event(snap, evt.RUN_CREATED, {
            "run_id": "run-1", "run_number": 1, "ai_loops": 1,
            "stop_point": "every_artifact",
        }, sequence=1)
        snap = apply_event(snap, evt.RUN_COMPLETED, {
            "run_id": "run-1", "status": "completed",
        }, sequence=2)
        snap = apply_event(snap, evt.RUN_CREATED, {
            "run_id": "run-2", "run_number": 2, "ai_loops": 1,
            "stop_point": "every_artifact",
        }, sequence=3)

        assert snap["run_status"]["run-1"] == "completed"
        assert snap["run_status"]["run-2"] == "running"

        snap = apply_event(snap, evt.PIPELINE_RESET, {}, sequence=4)

        assert snap["run_status"]["run-1"] == "completed"  # stays completed
        assert snap["run_status"]["run-2"] == "cancelled"   # was running → cancelled
        assert snap["is_running"] is False

    def test_no_running_runs_unaffected(self):
        snap = empty_snapshot()
        snap = apply_event(snap, evt.RUN_CREATED, {
            "run_id": "run-1", "run_number": 1, "ai_loops": 1,
            "stop_point": "every_artifact",
        }, sequence=1)
        snap = apply_event(snap, evt.RUN_COMPLETED, {
            "run_id": "run-1", "status": "failed",
        }, sequence=2)

        snap = apply_event(snap, evt.PIPELINE_RESET, {}, sequence=3)

        assert snap["run_status"]["run-1"] == "failed"  # unchanged


class TestReconcileProject:
    def test_no_corrections_when_clean(self, db, project, pipeline_config, stage_def):
        corrections = reconcile_project(db, project.id)
        assert corrections == []

    def test_fixes_orphaned_running_execution(
        self, db, project, pipeline_config, stage_def, pipeline_run,
    ):
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

    def test_does_not_kill_run_with_active_work(
        self, db, project, pipeline_config, stage_def, pipeline_run,
    ):
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

    def test_syncs_artifact_status_from_snapshot(
        self, db, project, pipeline_config, stage_def, pipeline_run,
    ):
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

    def test_fixes_phantom_running_run_status(
        self, db, project, pipeline_config, stage_def, pipeline_run,
    ):
        """A run that is "running" in snapshot but already FAILED in DB gets a
        RUN_COMPLETED event emitted so the snapshot catches up."""
        es = EventStore(db)
        # Emit RUN_CREATED so the snapshot has this run as "running"
        es.emit(project.id, evt.RUN_CREATED, {
            "run_id": pipeline_run.run_id,
            "run_number": pipeline_run.run_number,
            "ai_loops": 1,
            "stop_point": "every_artifact",
        }, run_id=pipeline_run.run_id)

        # Manually fix the DB run to FAILED (simulating a prior partial fix)
        pipeline_run.status = PipelineRunStatus.FAILED
        db.commit()

        corrections = reconcile_project(db, project.id)

        # The snapshot should now show this run as "failed"
        snapshot = es.get_snapshot(project.id)
        assert snapshot.run_status[pipeline_run.run_id] == "failed"
        phantom_corrections = [c for c in corrections if c["type"] == "phantom_run_status"]
        assert len(phantom_corrections) == 1
        assert phantom_corrections[0]["id"] == pipeline_run.run_id

    def test_phantom_fix_does_not_touch_legitimately_running(
        self, db, project, pipeline_config, stage_def, pipeline_run,
    ):
        """A run that is "running" in both snapshot and DB should not be touched."""
        es = EventStore(db)
        es.emit(project.id, evt.RUN_CREATED, {
            "run_id": pipeline_run.run_id,
            "run_number": pipeline_run.run_number,
            "ai_loops": 1,
            "stop_point": "every_artifact",
        }, run_id=pipeline_run.run_id)

        # Keep an active execution so zombie check doesn't fire either
        make_execution(
            db, project.id, run_id=pipeline_run.run_id,
            status=StageStatus.AWAITING_REVIEW,
        )
        db.commit()

        corrections = reconcile_project(db, project.id)

        phantom_corrections = [c for c in corrections if c["type"] == "phantom_run_status"]
        assert len(phantom_corrections) == 0
        db.refresh(pipeline_run)
        assert pipeline_run.status == PipelineRunStatus.RUNNING
