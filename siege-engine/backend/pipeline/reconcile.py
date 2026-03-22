"""Pipeline state reconciliation.

Rebuilds the pipeline snapshot from the event log and syncs DB model
status fields (projections) to match.  Used both on startup (automatic
recovery) and via the repair button (manual reconcile endpoint).
"""

from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy.orm import Session

from backend.models import (
    Artifact,
    ArtifactStatus,
    PipelineRun,
    PipelineRunStatus,
    Project,
    StageExecution,
    StageStatus,
)
from backend.models.job import Job
from backend.pipeline import events as evt
from backend.pipeline.event_store import EventStore

logger = logging.getLogger(__name__)


def reconcile_project(db: Session, project_id: str) -> list[dict]:
    """Rebuild snapshot from events and sync DB projections for one project.

    Returns a list of corrections made.  The caller is responsible for
    committing the transaction afterward (or it may already be committed
    by event emissions).
    """
    es = EventStore(db)
    snapshot = es.rebuild_snapshot(project_id)
    corrections: list[dict] = []

    # ── Sync artifact statuses ──────────────────────────────────────────
    artifacts = db.query(Artifact).filter_by(project_id=project_id).all()
    for art in artifacts:
        snap_status = (snapshot.artifact_statuses or {}).get(art.id)
        if snap_status:
            try:
                new_status = ArtifactStatus(snap_status)
                if art.status != new_status:
                    corrections.append({
                        "type": "artifact_status",
                        "id": art.id,
                        "from": art.status.value if art.status else None,
                        "to": new_status.value,
                    })
                    art.status = new_status
            except ValueError:
                pass
        snap_version = (snapshot.artifact_versions or {}).get(art.id)
        if snap_version is not None:
            art.version = snap_version

    # ── Sync execution statuses from snapshot ───────────────────────────
    snap_stage_statuses = snapshot.stage_statuses or {}
    snap_exec_map = snapshot.execution_map or {}
    _status_map = {
        "running": StageStatus.RUNNING,
        "pending": StageStatus.PENDING,
        "generating": StageStatus.RUNNING,
        "awaiting_review": StageStatus.AWAITING_REVIEW,
        "approved": StageStatus.APPROVED,
        "rejected": StageStatus.REJECTED,
        "failed": StageStatus.FAILED,
        "ai_reviewing": StageStatus.AI_REVIEW,
    }
    for stage_key, snap_stage_status in snap_stage_statuses.items():
        exec_entry = snap_exec_map.get(stage_key)
        if not exec_entry:
            continue
        exec_id = exec_entry.get("execution_id")
        if not exec_id:
            continue
        execution = db.get(StageExecution, exec_id)
        if not execution:
            continue
        target_status = _status_map.get(snap_stage_status)
        if target_status and execution.status != target_status:
            corrections.append({
                "type": "execution_status",
                "id": exec_id,
                "stage_key": stage_key,
                "from": execution.status.value if execution.status else None,
                "to": target_status.value,
            })
            execution.status = target_status
            if target_status in (
                StageStatus.APPROVED, StageStatus.REJECTED, StageStatus.FAILED,
            ) and not execution.completed_at:
                execution.completed_at = datetime.utcnow()

    # ── Fix orphaned RUNNING executions ─────────────────────────────────
    tracked_exec_ids = {
        entry.get("execution_id")
        for entry in snap_exec_map.values()
        if entry.get("execution_id")
    }
    orphan_executions = (
        db.query(StageExecution)
        .filter(
            StageExecution.project_id == project_id,
            StageExecution.status.in_([
                StageStatus.RUNNING, StageStatus.AI_REVIEW,
            ]),
            StageExecution.id.notin_(tracked_exec_ids) if tracked_exec_ids else True,
        )
        .all()
    )
    for orphan in orphan_executions:
        corrections.append({
            "type": "orphan_execution",
            "id": orphan.id,
            "stage_key": orphan.stage_key,
            "from": orphan.status.value,
            "to": "failed",
        })
        orphan.status = StageStatus.FAILED
        orphan.completed_at = orphan.completed_at or datetime.utcnow()

    # ── Fix zombie executions (RUNNING but no active job) ─────────────
    # An execution can be marked RUNNING in both the snapshot and DB, but
    # if there's no queued/running job backing it, the process is dead.
    active_job_exec_ids = _active_job_execution_ids(db, project_id)
    running_executions = (
        db.query(StageExecution)
        .filter(
            StageExecution.project_id == project_id,
            StageExecution.status.in_([
                StageStatus.RUNNING, StageStatus.AI_REVIEW,
            ]),
        )
        .all()
    )
    for ex in running_executions:
        if ex.id not in active_job_exec_ids:
            corrections.append({
                "type": "zombie_execution",
                "id": ex.id,
                "stage_key": ex.stage_key,
                "from": ex.status.value,
                "to": "failed",
            })
            ex.status = StageStatus.FAILED
            ex.error_message = ex.error_message or "Process died"
            ex.completed_at = ex.completed_at or datetime.utcnow()
            # Emit event so the snapshot reflects this
            es.emit(project_id, evt.STAGE_FAILED, {
                "execution_id": ex.id,
                "stage_key": ex.stage_key,
                "component_key": ex.component_key,
                "artifact_id": ex.artifact_id,
                "error": "Process died (no active job)",
            }, run_id=ex.run_id)

    # ── Enforce one active execution per stage ────────────────────────
    # If multiple executions are RUNNING/AI_REVIEW for the same
    # (stage_key, component_key), keep only the newest and fail the rest.
    active_execs = (
        db.query(StageExecution)
        .filter(
            StageExecution.project_id == project_id,
            StageExecution.status.in_([
                StageStatus.RUNNING, StageStatus.AI_REVIEW,
            ]),
        )
        .order_by(StageExecution.started_at.desc())
        .all()
    )
    seen_stages: dict[tuple, str] = {}
    for ex in active_execs:
        stage_tuple = (ex.stage_key, ex.component_key)
        if stage_tuple in seen_stages:
            corrections.append({
                "type": "duplicate_execution",
                "id": ex.id,
                "stage_key": ex.stage_key,
                "kept": seen_stages[stage_tuple],
                "from": ex.status.value,
                "to": "failed",
            })
            ex.status = StageStatus.FAILED
            ex.error_message = "Duplicate execution"
            ex.completed_at = ex.completed_at or datetime.utcnow()
            es.emit(project_id, evt.STAGE_FAILED, {
                "execution_id": ex.id,
                "stage_key": ex.stage_key,
                "component_key": ex.component_key,
                "artifact_id": ex.artifact_id,
                "error": "Duplicate execution",
            }, run_id=ex.run_id)
        else:
            seen_stages[stage_tuple] = ex.id

    # ── Fix stuck runs (snapshot says not running) ──────────────────────
    snap_is_running = snapshot.is_running
    snap_run_statuses = snapshot.run_status or {}
    running_runs = (
        db.query(PipelineRun)
        .filter_by(project_id=project_id, status=PipelineRunStatus.RUNNING)
        .all()
    )
    for run in running_runs:
        snap_run_status = snap_run_statuses.get(run.run_id)
        if snap_run_status != "running" or not snap_is_running:
            corrections.append({
                "type": "run_status",
                "id": run.run_id,
                "from": "running",
                "to": "completed",
            })
            run.status = PipelineRunStatus.COMPLETED
            run.completed_at = run.completed_at or datetime.utcnow()

    # ── Fix phantom "running" entries in snapshot run_status ─────────────
    # After rebuilding the snapshot from events, some run_status entries may
    # still show "running" even though the DB PipelineRun is already terminal
    # (e.g. a previous reconciliation fixed the DB but never emitted the
    # RUN_COMPLETED event, or a PIPELINE_RESET before the fix didn't cancel
    # running entries).  Emit RUN_COMPLETED events to permanently fix these.
    snap_run_statuses = snapshot.run_status or {}
    for run_id, snap_status in list(snap_run_statuses.items()):
        if snap_status != "running":
            continue
        db_run = (
            db.query(PipelineRun)
            .filter_by(run_id=run_id, project_id=project_id)
            .first()
        )
        if db_run is None or db_run.status == PipelineRunStatus.RUNNING:
            continue  # still legitimately running (or unknown)
        terminal = db_run.status.value  # "completed", "failed", "cancelled"
        corrections.append({
            "type": "phantom_run_status",
            "id": run_id,
            "from": "running",
            "to": terminal,
        })
        es.emit(
            project_id, evt.RUN_COMPLETED,
            {"run_id": run_id, "status": terminal},
            run_id=run_id,
        )

    # ── Fix zombie runs (running but no active executions) ──────────────
    still_running = (
        db.query(PipelineRun)
        .filter_by(project_id=project_id, status=PipelineRunStatus.RUNNING)
        .all()
    )
    for run in still_running:
        active_count = (
            db.query(StageExecution)
            .filter(
                StageExecution.run_id == run.run_id,
                StageExecution.status.in_([
                    StageStatus.RUNNING, StageStatus.AI_REVIEW,
                    StageStatus.AWAITING_REVIEW,
                ]),
            )
            .count()
        )
        if active_count == 0:
            corrections.append({
                "type": "zombie_run",
                "id": run.run_id,
                "from": "running",
                "to": "failed",
            })
            run.status = PipelineRunStatus.FAILED
            run.completed_at = run.completed_at or datetime.utcnow()
            es.emit(
                project_id, evt.RUN_COMPLETED,
                {"run_id": run.run_id, "status": "failed"},
                run_id=run.run_id,
            )

    db.commit()
    return corrections


def _active_job_execution_ids(
    db: Session, project_id: str,
) -> set[str]:
    """Return execution IDs that have an active (queued/running) job."""
    active_jobs = (
        db.query(Job)
        .filter(Job.status.in_(["queued", "running"]))
        .all()
    )
    exec_ids: set[str] = set()
    for job in active_jobs:
        payload = job.payload or {}
        job_project = payload.get("project_id")
        job_exec = payload.get("execution_id")
        if job_project == project_id and job_exec:
            exec_ids.add(job_exec)
    return exec_ids


def reconcile_all_projects(db: Session) -> dict[str, list[dict]]:
    """Run reconcile for every project.  Used on startup."""
    projects = db.query(Project).all()
    all_corrections: dict[str, list[dict]] = {}
    for project in projects:
        corrections = reconcile_project(db, project.id)
        if corrections:
            all_corrections[project.id] = corrections
            logger.warning(
                "Startup reconcile for project %s (%s): %d corrections",
                project.name, project.id, len(corrections),
            )
    return all_corrections
