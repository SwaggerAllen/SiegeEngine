"""Build a siege-state.json manifest at the end of a pipeline run."""

import logging
from datetime import datetime

from sqlalchemy.orm import Session

from backend.models import (
    Artifact,
    ComponentDefinition,
    PipelineRun,
    StageExecution,
)

logger = logging.getLogger(__name__)


def build_siege_state(db: Session, project_id: str, pipeline_run: PipelineRun) -> dict:
    """Build a JSON-serialisable manifest capturing the full project state at the end of a run."""

    # Artifacts
    artifacts = db.query(Artifact).filter_by(project_id=project_id).all()
    artifact_list = [
        {
            "id": a.id,
            "artifact_type": a.artifact_type.value
            if hasattr(a.artifact_type, "value")
            else str(a.artifact_type),
            "name": a.name,
            "component_key": a.component_key,
            "status": a.status.value if hasattr(a.status, "value") else str(a.status),
            "version": a.version,
            "file_path": a.file_path,
            "git_commit_sha": a.git_commit_sha,
        }
        for a in artifacts
    ]

    # Stage executions for this run
    executions = (
        db.query(StageExecution).filter_by(project_id=project_id, run_id=pipeline_run.run_id).all()
    )
    execution_list = [
        {
            "id": e.id,
            "stage_key": e.stage_key,
            "component_key": e.component_key,
            "status": e.status.value if hasattr(e.status, "value") else str(e.status),
            "artifact_id": e.artifact_id,
            "started_at": e.started_at.isoformat() if e.started_at else None,
            "completed_at": e.completed_at.isoformat() if e.completed_at else None,
            "generation_completed_at": (
                e.generation_completed_at.isoformat()
                if e.generation_completed_at else None
            ),
        }
        for e in executions
    ]

    # Component definitions
    components = db.query(ComponentDefinition).filter_by(project_id=project_id).all()
    component_list = [
        {
            "key": c.key,
            "name": c.name,
            "parent_key": c.parent_key,
            "dependencies": c.dependencies or [],
        }
        for c in components
    ]

    return {
        "run_number": pipeline_run.run_number,
        "run_id": pipeline_run.run_id,
        "timestamp": datetime.utcnow().isoformat(),
        "config": {
            "ai_loops": pipeline_run.ai_loops,
            "stop_point": pipeline_run.stop_point.value
            if hasattr(pipeline_run.stop_point, "value")
            else str(pipeline_run.stop_point),
            "start_stage_key": pipeline_run.start_stage_key,
            "start_component_key": pipeline_run.start_component_key,
        },
        "artifacts": artifact_list,
        "stage_executions": execution_list,
        "component_definitions": component_list,
    }
