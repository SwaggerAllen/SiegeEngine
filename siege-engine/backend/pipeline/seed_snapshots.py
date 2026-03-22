"""One-time script to seed PipelineSnapshot for existing projects.

Reads current Artifact.status, StageExecution.status, and PipelineRun.status
from the DB and builds an initial snapshot for each project.

Usage:
    python -m backend.pipeline.seed_snapshots
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from backend.database import SessionLocal
from backend.models.artifact import Artifact
from backend.models.enums import PipelineRunStatus
from backend.models.pipeline import PipelineRun, StageExecution
from backend.models.pipeline_events import PipelineSnapshot
from backend.models.project import Project

logger = logging.getLogger(__name__)


def seed_snapshot_for_project(db: Session, project_id: str) -> PipelineSnapshot:
    """Build an initial PipelineSnapshot from current DB state."""
    existing = db.query(PipelineSnapshot).filter_by(project_id=project_id).first()
    if existing:
        logger.info("Snapshot already exists for project %s, skipping", project_id)
        return existing

    # Gather artifact statuses
    artifact_statuses: dict[str, str] = {}
    artifacts = db.query(Artifact).filter_by(project_id=project_id).all()
    for art in artifacts:
        artifact_statuses[art.id] = art.status.value

    # Gather stage statuses from the latest execution per stage/component
    stage_statuses: dict[str, str] = {}
    executions = db.query(StageExecution).filter_by(project_id=project_id).all()
    # Group by (stage_key, component_key) and take latest by started_at
    latest: dict[str, StageExecution] = {}
    for ex in executions:
        key = f"{ex.stage_key}/{ex.component_key}" if ex.component_key else ex.stage_key
        prev = latest.get(key)
        if prev is None or (
            ex.started_at
            and (not prev.started_at or ex.started_at > prev.started_at)
        ):
            latest[key] = ex
    for key, ex in latest.items():
        stage_statuses[key] = ex.status.value

    # Gather run statuses
    run_status: dict[str, str] = {}
    runs = db.query(PipelineRun).filter_by(project_id=project_id).all()
    active_run = None
    for run in runs:
        run_status[run.run_id] = run.status.value
        if run.status in (PipelineRunStatus.RUNNING, PipelineRunStatus.PAUSED):
            active_run = run

    snapshot = PipelineSnapshot(
        project_id=project_id,
        last_sequence=0,
        run_status=run_status,
        stage_statuses=stage_statuses,
        artifact_statuses=artifact_statuses,
        is_running=active_run is not None and active_run.status == PipelineRunStatus.RUNNING,
        is_paused=active_run is not None and active_run.status == PipelineRunStatus.PAUSED,
        paused_stage=None,
        current_run_id=active_run.run_id if active_run else None,
        # Extended snapshot fields — must be initialized to empty dicts
        artifact_versions={},
        stage_errors={},
        comment_counts={},
        stage_triggers={},
        artifact_meta={},
        artifact_git_shas={},
        cascade_parents={},
        execution_map={},
    )
    db.add(snapshot)
    db.flush()
    logger.info(
        "Seeded snapshot for project %s: %d artifacts, %d stages, %d runs",
        project_id, len(artifact_statuses), len(stage_statuses), len(run_status),
    )
    return snapshot


def seed_all() -> None:
    """Seed snapshots for all projects."""
    db = SessionLocal()
    try:
        projects = db.query(Project).all()
        for project in projects:
            seed_snapshot_for_project(db, project.id)
        db.commit()
        logger.info("Seeded snapshots for %d projects", len(projects))
    finally:
        db.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    seed_all()
