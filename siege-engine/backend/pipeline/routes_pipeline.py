import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from jose import JWTError
from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.auth.routes import _require_writer, get_current_user
from backend.auth.service import decode_token
from backend.dag.service import get_regeneration_order
from backend.database import get_db
from backend.models import (
    Artifact,
    ArtifactStatus,
    PipelineConfig,
    PipelineRun,
    PipelineRunStatus,
    Project,
    StageExecution,
    StageStatus,
    StopPoint,
    User,
)
from backend.pipeline.engine import PipelineEngine
from backend.pipeline.queue import cancel_jobs_by_type, cancel_running_execution, enqueue
from backend.pipeline.schemas import (
    CancelRequest,
    PipelineStartRequest,
    PromptPreviewRequest,
    RegenerateRequest,
    ResumeRunRequest,
)
from backend.websocket.manager import ws_manager

logger = logging.getLogger(__name__)

pipeline_router = APIRouter()


def _utc_iso(dt: datetime | None) -> str | None:
    """Serialize a naive-UTC datetime with a Z suffix so JS parses it as UTC."""
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc).isoformat()


def _get_project_or_404(db: Session, project_id: str) -> Project:
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    return project


def _check_blocking_pr(project: Project):
    """Raise 409 if this project has an unresolved blocking PR."""
    if project.blocking_pr_url:
        raise HTTPException(
            409,
            detail={
                "message": "A blocking PR must be merged or closed before starting a new run.",
                "blocking_pr_url": project.blocking_pr_url,
                "blocking_pr_number": project.blocking_pr_number,
            },
        )


@pipeline_router.post("/{project_id}/start")
async def start_pipeline(
    project_id: str,
    req: PipelineStartRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(_require_writer),
):
    project = _get_project_or_404(db, project_id)
    _check_blocking_pr(project)

    # Compute next sequential run number for this project
    max_num = (
        db.query(func.max(PipelineRun.run_number)).filter_by(project_id=project_id).scalar()
    ) or 0
    run_number = max_num + 1

    pipeline_run = PipelineRun(
        project_id=project_id,
        run_number=run_number,
        ai_loops=req.ai_loops,
        stop_point=StopPoint(req.stop_point),
        start_stage_key=req.start_stage_key,
        start_component_key=req.start_component_key,
    )
    db.add(pipeline_run)
    db.commit()
    db.refresh(pipeline_run)

    logger.info(
        "POST /start: project_id=%s, run_number=%d, ai_loops=%d, stop_point=%s, start=%s/%s",
        project_id,
        run_number,
        req.ai_loops,
        req.stop_point,
        req.start_stage_key,
        req.start_component_key,
    )

    pipeline_run_id = pipeline_run.id

    enqueue(
        db,
        "start_pipeline",
        {
            "project_id": project_id,
            "pipeline_run_id": pipeline_run_id,
        },
    )

    return {
        "status": "started",
        "run_number": run_number,
        "run_id": pipeline_run.run_id,
    }


@pipeline_router.post("/{project_id}/resume-run")
async def resume_run(
    project_id: str,
    req: ResumeRunRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(_require_writer),
):
    """Start a new run that continues where the last run left off.

    Carries over approved + in-review executions from the most recent run,
    then re-processes any stale or missing nodes.
    """
    project = _get_project_or_404(db, project_id)
    _check_blocking_pr(project)

    # Find the most recent run (completed, paused, cancelled, or failed)
    prev_run = (
        db.query(PipelineRun)
        .filter_by(project_id=project_id)
        .order_by(PipelineRun.run_number.desc())
        .first()
    )
    if not prev_run:
        raise HTTPException(400, "No previous run to resume from")
    if prev_run.status == PipelineRunStatus.RUNNING:
        raise HTTPException(400, "Previous run is still active — cancel it first")

    # Compute next run number
    max_num = (
        db.query(func.max(PipelineRun.run_number)).filter_by(project_id=project_id).scalar()
    ) or 0
    run_number = max_num + 1

    pipeline_run = PipelineRun(
        project_id=project_id,
        run_number=run_number,
        ai_loops=req.ai_loops,
        stop_point=StopPoint(req.stop_point),
        start_stage_key=req.start_stage_key,
        start_component_key=req.start_component_key,
    )
    db.add(pipeline_run)
    db.commit()
    db.refresh(pipeline_run)

    logger.info(
        "POST /resume-run: project_id=%s, run_number=%d, resuming from run #%d (run_id=%s)",
        project_id,
        run_number,
        prev_run.run_number,
        prev_run.run_id,
    )

    pipeline_run_id = pipeline_run.id
    prev_run_id = prev_run.run_id

    enqueue(
        db,
        "resume_run",
        {
            "project_id": project_id,
            "pipeline_run_id": pipeline_run_id,
            "prev_run_id": prev_run_id,
        },
    )

    return {
        "status": "resumed",
        "run_number": run_number,
        "run_id": pipeline_run.run_id,
        "resumed_from": prev_run.run_number,
    }


@pipeline_router.post("/{project_id}/propagate")
async def propagate_changes(
    project_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(_require_writer),
):
    """Regenerate stale artifacts after input document changes.

    Creates a propagation run where all regenerated artifacts land in
    AWAITING_REVIEW regardless of the human_review setting, so the user
    can review all changes that resulted from the input change.
    """
    project = _get_project_or_404(db, project_id)
    _check_blocking_pr(project)

    # Count stale artifacts
    stale_count = db.query(Artifact).filter_by(project_id=project_id, is_stale=True).count()
    if stale_count == 0:
        raise HTTPException(400, "No stale artifacts to propagate")

    max_num = (
        db.query(func.max(PipelineRun.run_number)).filter_by(project_id=project_id).scalar()
    ) or 0
    run_number = max_num + 1

    pipeline_run = PipelineRun(
        project_id=project_id,
        run_number=run_number,
        propagation_run=True,
        stop_point=StopPoint.BEFORE_CODE,
    )
    db.add(pipeline_run)
    db.commit()
    db.refresh(pipeline_run)

    enqueue(
        db,
        "resume_run",
        {
            "project_id": project_id,
            "pipeline_run_id": pipeline_run.id,
            "prev_run_id": pipeline_run.run_id,
        },
    )

    return {
        "status": "propagating",
        "run_number": run_number,
        "run_id": pipeline_run.run_id,
        "stale_count": stale_count,
    }


@pipeline_router.post("/{project_id}/cancel")
async def cancel_pipeline(
    project_id: str,
    req: CancelRequest = CancelRequest(),
    db: Session = Depends(get_db),
    user: User = Depends(_require_writer),
):
    project = _get_project_or_404(db, project_id)

    from backend.pipeline import events as _evt
    from backend.pipeline.event_store import EventStore

    es = EventStore(db)

    # Find all active executions
    active_executions = (
        db.query(StageExecution)
        .filter_by(project_id=project_id)
        .filter(
            StageExecution.status.in_(
                [
                    StageStatus.RUNNING,
                    StageStatus.PENDING,
                    StageStatus.AI_REVIEW,
                    StageStatus.AWAITING_REVIEW,
                ]
            )
        )
        .all()
    )

    # Kill CLI processes and cancel worker tasks (operational)
    for e in active_executions:
        cancel_running_execution(e.id)

    # Cancel all queued jobs for this project (operational)
    from backend.models.job import Job

    all_exec_ids = {e.id for e in active_executions}
    queued_jobs = db.query(Job).filter(Job.status.in_(["queued", "running"])).all()
    for job in queued_jobs:
        payload = job.payload or {}
        if payload.get("project_id") == project_id or payload.get("execution_id") in all_exec_ids:
            job.status = "cancelled"

    # Preserve awaiting_review executions that have valid artifacts —
    # auto-approve them so the next run carries them over instead of
    # regenerating from scratch.
    for e in active_executions:
        if e.status == StageStatus.AWAITING_REVIEW and e.artifact_id:
            es.emit(
                project_id,
                _evt.HUMAN_APPROVED,
                {
                    "execution_id": e.id,
                    "stage_key": e.stage_key,
                    "component_key": e.component_key,
                    "artifact_id": e.artifact_id,
                },
                run_id=e.run_id,
            )
            e.status = StageStatus.APPROVED
            e.completed_at = e.completed_at or datetime.utcnow()
        else:
            es.emit(
                project_id,
                _evt.STAGE_FAILED,
                {
                    "execution_id": e.id,
                    "stage_key": e.stage_key,
                    "component_key": e.component_key,
                    "artifact_id": e.artifact_id,
                    "error": "Cancelled by user",
                },
                run_id=e.run_id,
            )
            e.status = StageStatus.FAILED
            e.error_message = "Cancelled by user"

    # Reset in-progress artifacts as DB projections
    in_progress_artifacts = (
        db.query(Artifact)
        .filter_by(project_id=project_id)
        .filter(Artifact.status.in_([ArtifactStatus.GENERATING, ArtifactStatus.AI_REVIEWING]))
        .all()
    )
    for a in in_progress_artifacts:
        a.status = ArtifactStatus.PENDING

    # Emit RUN_COMPLETED events for active runs (snapshot updates via reducer)
    active_runs = (
        db.query(PipelineRun)
        .filter_by(project_id=project_id)
        .filter(PipelineRun.status.in_([PipelineRunStatus.RUNNING, PipelineRunStatus.PAUSED]))
        .all()
    )
    for r in active_runs:
        es.emit(
            project_id,
            _evt.RUN_COMPLETED,
            {
                "run_id": r.run_id,
                "status": "cancelled",
            },
            run_id=r.run_id,
        )
        # DB projections
        r.status = PipelineRunStatus.CANCELLED
        r.completed_at = r.completed_at or datetime.utcnow()

    db.commit()

    # Broadcast cancellation so the UI updates immediately
    await ws_manager.broadcast(
        project_id,
        {
            "type": "pipeline_cancelled",
            "cancelled_count": len(active_executions),
        },
    )

    result = {"status": "cancelled", "cancelled_count": len(active_executions)}

    # Optionally open a blocking PR
    if req.open_pr:
        if not project.github_repo_slug:
            raise HTTPException(400, "Project has no GitHub repo configured")

        from backend.git_manager.service import git_manager
        from backend.github.service import GitHubService
        from backend.models import GitHubCredential

        cred = db.query(GitHubCredential).filter_by(user_id=user.id).first()
        if not cred:
            raise HTTPException(400, "GitHub not connected. Connect via Settings.")

        if not project.remote_url or not project.remote_url.startswith("https://"):
            raise HTTPException(400, "Project needs an HTTPS remote URL for PR creation")

        run_label = active_runs[0].run_number if active_runs else "cancelled"
        branch = f"siege-engine/{project.name.lower().replace(' ', '-')}"
        pr_title = req.pr_title or f"Cancelled run #{run_label} — review before continuing"
        pr_body = (
            req.pr_body
            or "This PR was created when a pipeline run was cancelled."
            " Merge or close it to unblock new runs."
        )

        auth_url = project.remote_url.replace(
            "https://", f"https://x-access-token:{cred.access_token}@"
        )

        try:
            git_manager.push_branch(project_id, branch, auth_url=auth_url)
        except Exception as e:
            logger.error("Failed to push branch for PR: %s", e)
            result["pr_error"] = f"Failed to push branch: {e}"
            return result

        gh = GitHubService(cred.access_token)
        try:
            pr = await gh.create_pr(
                project.github_repo_slug,
                pr_title,
                pr_body,
                branch,
                req.base_branch,
            )
        except Exception as e:
            error_detail = str(e)
            if hasattr(e, "response") and e.response is not None:
                try:
                    error_detail = e.response.json().get("message", error_detail)
                except Exception:
                    pass
            logger.error("Failed to create PR: %s", error_detail)
            result["pr_error"] = f"GitHub API error: {error_detail}"
            return result

        project.blocking_pr_url = pr.get("html_url")
        project.blocking_pr_number = pr.get("number")
        db.commit()

        result["pr_url"] = project.blocking_pr_url
        result["pr_number"] = project.blocking_pr_number

    return result


@pipeline_router.post("/{project_id}/reset-all")
async def reset_all(
    project_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(_require_writer),
):
    """Reset pipeline to a clean slate via events.

    Emits STAGE_FAILED for in-flight executions, RUN_COMPLETED for active runs,
    and PIPELINE_RESET to put all artifacts into awaiting_review. The snapshot
    (source of truth) is updated by the reducer; DB models are updated as projections.
    """
    _get_project_or_404(db, project_id)

    from backend.pipeline import events as _evt
    from backend.pipeline.event_store import EventStore

    es = EventStore(db)

    # 1. Kill ALL running processes for this project's executions
    all_project_execs = db.query(StageExecution).filter_by(project_id=project_id).all()
    all_exec_ids = {e.id for e in all_project_execs}
    for e in all_project_execs:
        cancel_running_execution(e.id)

    # Cancel ALL queued/running jobs for this project (comprehensive)
    from backend.models.job import Job

    active_jobs = db.query(Job).filter(Job.status.in_(["queued", "running"])).all()
    for job in active_jobs:
        payload = job.payload or {}
        if payload.get("project_id") == project_id or payload.get("execution_id") in all_exec_ids:
            job.status = "cancelled"

    # Narrow to in-flight executions for event emission
    in_flight = [
        e
        for e in all_project_execs
        if e.status
        in (
            StageStatus.RUNNING,
            StageStatus.PENDING,
            StageStatus.AI_REVIEW,
            StageStatus.AWAITING_REVIEW,
        )
    ]

    # 2. Emit STAGE_FAILED for each in-flight execution
    for e in in_flight:
        es.emit(
            project_id,
            _evt.STAGE_FAILED,
            {
                "execution_id": e.id,
                "stage_key": e.stage_key,
                "component_key": e.component_key,
                "artifact_id": e.artifact_id,
                "error": "Reset by user",
            },
            run_id=e.run_id,
        )
        # DB projection
        e.status = StageStatus.FAILED
        e.error_message = "Reset by user"
        e.completed_at = e.completed_at or datetime.utcnow()

    # 3. Emit RUN_COMPLETED for active runs
    active_runs = (
        db.query(PipelineRun)
        .filter_by(project_id=project_id)
        .filter(PipelineRun.status.in_([PipelineRunStatus.RUNNING, PipelineRunStatus.PAUSED]))
        .all()
    )
    for r in active_runs:
        es.emit(
            project_id,
            _evt.RUN_COMPLETED,
            {
                "run_id": r.run_id,
                "status": "cancelled",
            },
            run_id=r.run_id,
        )
        # DB projection
        r.status = PipelineRunStatus.CANCELLED
        r.completed_at = r.completed_at or datetime.utcnow()

    db.flush()

    # 4. Determine run_id for the reset event
    latest_run = (
        db.query(PipelineRun)
        .filter_by(project_id=project_id)
        .order_by(PipelineRun.run_number.desc())
        .first()
    )
    if not latest_run:
        latest_run = PipelineRun(
            project_id=project_id,
            run_number=1,
            stop_point=StopPoint.END_OF_PHASE,
            status=PipelineRunStatus.CANCELLED,
            completed_at=datetime.utcnow(),
        )
        db.add(latest_run)
        db.flush()
    run_id = latest_run.run_id

    # 5. Emit PIPELINE_RESET (reducer puts all snapshot artifacts into awaiting_review)
    es.emit(project_id, _evt.PIPELINE_RESET, {}, run_id=run_id)

    # 6. Sync DB artifact statuses as projections to match snapshot
    all_artifacts = db.query(Artifact).filter_by(project_id=project_id).all()
    snapshot = es.get_snapshot(project_id)
    reset_count = 0
    for artifact in all_artifacts:
        snap_status = (snapshot.artifact_statuses or {}).get(artifact.id)
        if snap_status:
            try:
                artifact.status = ArtifactStatus(snap_status)
            except ValueError:
                pass
            reset_count += 1
        elif not artifact.content or not artifact.content.strip():
            artifact.status = ArtifactStatus.PENDING

    # Ensure awaiting_review executions exist for resume
    for artifact in all_artifacts:
        if artifact.status == ArtifactStatus.AWAITING_REVIEW:
            existing_exec = (
                db.query(StageExecution)
                .filter_by(project_id=project_id, artifact_id=artifact.id)
                .order_by(StageExecution.started_at.desc())
                .first()
            )
            if existing_exec:
                existing_exec.status = StageStatus.AWAITING_REVIEW
                existing_exec.run_id = run_id
                existing_exec.error_message = None

    db.commit()

    await ws_manager.broadcast(
        project_id,
        {
            "type": "pipeline_cancelled",
            "run_id": run_id,
            "message": "Pipeline reset to clean slate",
        },
    )

    return {
        "status": "reset",
        "artifacts_reset": reset_count,
        "executions_cancelled": len(in_flight),
        "runs_cancelled": len(active_runs),
    }


@pipeline_router.get("/{project_id}/status")
def get_status(
    project_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    executions = (
        db.query(StageExecution)
        .filter_by(project_id=project_id)
        .order_by(StageExecution.started_at.desc())
        .all()
    )

    # Include snapshot data for Phase 2 reads
    from backend.pipeline.event_store import EventStore

    es = EventStore(db)
    snapshot = es.get_snapshot(project_id)

    stage_statuses = snapshot.stage_statuses or {}
    exec_map = snapshot.execution_map or {}

    def _snap_status(e):
        """Get status from snapshot for the CURRENT execution only.

        Only the execution tracked in execution_map gets the live snapshot
        status.  Historical executions use their own DB status — otherwise
        every execution for a stage shows the same blinking "running" badge.
        """
        key = f"{e.stage_key}/{e.component_key}" if e.component_key else e.stage_key
        tracked = exec_map.get(key, {})
        if tracked.get("execution_id") == e.id:
            return stage_statuses.get(key, e.status.value)
        return e.status.value

    return {
        "stages": [
            {
                "id": e.id,
                "stage_key": e.stage_key,
                "component_key": e.component_key,
                "status": _snap_status(e),
                "artifact_id": e.artifact_id,
                "started_at": _utc_iso(e.started_at),
                "completed_at": _utc_iso(e.completed_at),
                "error_message": e.error_message,
                "run_id": e.run_id,
            }
            for e in executions
        ],
        "snapshot": {
            "is_running": snapshot.is_running,
            "is_paused": snapshot.is_paused,
            "paused_stage": snapshot.paused_stage,
            "current_run_id": snapshot.current_run_id,
            "stage_statuses": snapshot.stage_statuses or {},
            "artifact_statuses": snapshot.artifact_statuses or {},
            "run_status": snapshot.run_status or {},
            "last_sequence": snapshot.last_sequence,
        },
    }


@pipeline_router.get("/{project_id}/debug-state")
def get_debug_state(
    project_id: str,
    max_events: int = 30,
    max_runs: int = 20,
    max_executions: int = 40,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """Return complete pipeline state for debugging."""
    from backend.models.job import Job
    from backend.models.pipeline_events import PipelineEvent
    from backend.pipeline.event_store import EventStore

    _get_project_or_404(db, project_id)

    # Snapshot (full)
    es = EventStore(db)
    snapshot = es.get_snapshot(project_id)
    snapshot_data = {
        "is_running": snapshot.is_running,
        "is_paused": snapshot.is_paused,
        "paused_stage": snapshot.paused_stage,
        "current_run_id": snapshot.current_run_id,
        "last_sequence": snapshot.last_sequence,
        "run_status": snapshot.run_status or {},
        "stage_statuses": snapshot.stage_statuses or {},
        "artifact_statuses": snapshot.artifact_statuses or {},
        "artifact_versions": snapshot.artifact_versions or {},
        "stage_errors": snapshot.stage_errors or {},
        "stage_triggers": snapshot.stage_triggers or {},
        "artifact_meta": snapshot.artifact_meta or {},
        "artifact_git_shas": snapshot.artifact_git_shas or {},
        "comment_counts": snapshot.comment_counts or {},
        "cascade_parents": snapshot.cascade_parents or {},
        "execution_map": snapshot.execution_map or {},
    }

    # Runs (most recent first, capped)
    run_limit = min(max(max_runs, 5), 100)
    runs = (
        db.query(PipelineRun)
        .filter_by(project_id=project_id)
        .order_by(PipelineRun.run_number.desc())
        .limit(run_limit)
        .all()
    )
    runs_data = [
        {
            "run_number": r.run_number,
            "run_id": r.run_id,
            "status": r.status.value,
            "ai_loops": r.ai_loops,
            "human_review": r.human_review,
            "stop_point": r.stop_point.value,
            "propagation_run": r.propagation_run,
            "start_stage_key": r.start_stage_key,
            "start_component_key": r.start_component_key,
            "started_at": _utc_iso(r.started_at),
            "completed_at": _utc_iso(r.completed_at),
        }
        for r in runs
    ]

    # Executions (most recent first, capped)
    exec_limit = min(max(max_executions, 10), 200)
    executions = (
        db.query(StageExecution)
        .filter_by(project_id=project_id)
        .order_by(StageExecution.started_at.desc().nullslast())
        .limit(exec_limit)
        .all()
    )
    exec_data = [
        {
            "id": e.id,
            "stage_key": e.stage_key,
            "component_key": e.component_key,
            "status": e.status.value,
            "artifact_id": e.artifact_id,
            "run_id": e.run_id,
            "error_message": e.error_message,
            "retry_count": e.retry_count,
            "started_at": _utc_iso(e.started_at),
            "completed_at": _utc_iso(e.completed_at),
        }
        for e in executions
    ]

    # Artifacts
    artifacts = db.query(Artifact).filter_by(project_id=project_id).all()
    artifact_data = [
        {
            "id": a.id,
            "name": a.name,
            "artifact_type": a.artifact_type.value,
            "component_key": a.component_key,
            "status": a.status.value,
            "version": a.version,
            "content_length": len(a.content) if a.content else 0,
            "file_path": a.file_path,
            "git_commit_sha": a.git_commit_sha,
        }
        for a in artifacts
    ]

    # Recent events (capped)
    event_limit = min(max(max_events, 10), 200)
    events = (
        db.query(PipelineEvent)
        .filter_by(project_id=project_id)
        .order_by(PipelineEvent.sequence.desc())
        .limit(event_limit)
        .all()
    )
    event_data = [
        {
            "sequence": ev.sequence,
            "event_type": ev.event_type,
            "run_id": ev.run_id,
            "payload": ev.payload,
            "created_at": _utc_iso(ev.created_at),
        }
        for ev in reversed(events)  # chronological order
    ]

    # Active jobs
    jobs = db.query(Job).filter(Job.status.in_(["queued", "running"])).all()
    # Filter to this project's jobs
    job_data = []
    for j in jobs:
        payload = j.payload or {}
        if payload.get("project_id") == project_id:
            job_data.append(
                {
                    "id": j.id,
                    "job_type": j.job_type,
                    "status": j.status,
                    "payload": payload,
                    "created_at": _utc_iso(j.created_at),
                }
            )

    # Snapshot vs DB mismatches
    mismatches = []
    snap_artifact_statuses = snapshot_data["artifact_statuses"]
    for a in artifact_data:
        snap_status = snap_artifact_statuses.get(a["id"])
        db_status = a["status"]
        if snap_status and snap_status != db_status:
            mismatches.append(
                {
                    "type": "artifact_status",
                    "id": a["id"],
                    "name": a["name"],
                    "snapshot": snap_status,
                    "db": db_status,
                }
            )

    snap_stage_statuses = snapshot_data["stage_statuses"]
    # Build a map of current execution status per stage key
    exec_by_stage: dict[str, str] = {}
    for e in exec_data:
        key = e["stage_key"]
        if e["component_key"]:
            key += f":{e['component_key']}"
        # Keep the most recent (first in list since sorted desc)
        if key not in exec_by_stage:
            exec_by_stage[key] = e["status"]
    for key, snap_status in snap_stage_statuses.items():
        db_status = exec_by_stage.get(key)
        if db_status and snap_status != db_status:
            mismatches.append(
                {
                    "type": "stage_status",
                    "key": key,
                    "snapshot": snap_status,
                    "db": db_status,
                }
            )

    return {
        "snapshot": snapshot_data,
        "runs": runs_data,
        "executions": exec_data,
        "artifacts": artifact_data,
        "events": event_data,
        "jobs": job_data,
        "mismatches": mismatches,
    }


@pipeline_router.get("/{project_id}/events")
def list_events(
    project_id: str,
    run_id: str | None = Query(None),
    event_type: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """Return paginated event history for a project."""
    from backend.models.pipeline_events import PipelineEvent

    _get_project_or_404(db, project_id)

    query = db.query(PipelineEvent).filter_by(project_id=project_id)
    if run_id:
        query = query.filter(PipelineEvent.run_id == run_id)
    if event_type:
        query = query.filter(PipelineEvent.event_type == event_type)

    total = query.count()
    events = query.order_by(PipelineEvent.sequence.desc()).offset(offset).limit(limit).all()

    # Collect artifact IDs and run IDs from event payloads for name resolution
    artifact_ids: set[str] = set()
    run_ids: set[str] = set()
    for e in events:
        if e.payload:
            aid = e.payload.get("artifact_id")
            if aid:
                artifact_ids.add(str(aid))
        if e.run_id:
            run_ids.add(e.run_id)

    # Resolve artifact names
    artifact_names: dict[str, str] = {}
    if artifact_ids:
        from backend.models.artifact import Artifact

        arts = db.query(Artifact.id, Artifact.name).filter(Artifact.id.in_(artifact_ids)).all()
        artifact_names = {a.id: a.name for a in arts}

    # Resolve run numbers
    run_numbers: dict[str, int] = {}
    if run_ids:
        from backend.models.pipeline import PipelineRun

        runs_q = (
            db.query(PipelineRun.run_id, PipelineRun.run_number)
            .filter(PipelineRun.run_id.in_(run_ids))
            .all()
        )
        run_numbers = {r.run_id: r.run_number for r in runs_q}

    return {
        "events": [
            {
                "id": e.id,
                "sequence": e.sequence,
                "event_type": e.event_type,
                "payload": e.payload,
                "run_id": e.run_id,
                "created_at": _utc_iso(e.created_at),
            }
            for e in events
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
        "artifact_names": artifact_names,
        "run_numbers": run_numbers,
    }


@pipeline_router.get("/{project_id}/events/snapshot-at/{sequence}")
def snapshot_at_sequence(
    project_id: str,
    sequence: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """Replay events up to a given sequence number and return the snapshot state at that point."""
    from backend.models.pipeline_events import PipelineEvent
    from backend.pipeline.reducer import apply_event, empty_snapshot

    _get_project_or_404(db, project_id)

    events = (
        db.query(PipelineEvent)
        .filter_by(project_id=project_id)
        .filter(PipelineEvent.sequence <= sequence)
        .order_by(PipelineEvent.sequence)
        .all()
    )

    if not events:
        raise HTTPException(404, f"No events found up to sequence {sequence}")

    state = empty_snapshot()
    for event in events:
        state = apply_event(state, event.event_type, event.payload, event.sequence)

    return state


@pipeline_router.post("/{project_id}/events/revert-to/{sequence}")
def revert_to_sequence(
    project_id: str,
    sequence: int,
    db: Session = Depends(get_db),
    _user: User = Depends(_require_writer),
):
    """Revert pipeline state to a historical point.

    This is destructive: all events after the target sequence are deleted, the
    snapshot is rebuilt, artifact content is restored from git history, and any
    artifacts/executions/runs created after the target point are removed.
    """
    from datetime import datetime as dt

    from backend.git_manager.service import git_manager
    from backend.models.artifact import Artifact, ArtifactDependency
    from backend.models.enums import ArtifactStatus
    from backend.models.pipeline import PipelineRun, StageExecution
    from backend.models.pipeline_events import PipelineEvent
    from backend.pipeline.event_store import EventStore

    _get_project_or_404(db, project_id)

    # Validate that the target sequence exists
    target_event = (
        db.query(PipelineEvent).filter_by(project_id=project_id, sequence=sequence).first()
    )
    if not target_event:
        raise HTTPException(404, f"No event found at sequence {sequence}")

    target_time = target_event.created_at

    # Delete all events after the target sequence
    deleted_count = (
        db.query(PipelineEvent)
        .filter_by(project_id=project_id)
        .filter(PipelineEvent.sequence > sequence)
        .delete(synchronize_session="fetch")
    )

    # Rebuild snapshot from remaining events
    es = EventStore(db)
    rebuilt = es.rebuild_snapshot(project_id)

    # --- Restore artifact state ---
    valid_artifact_ids = set((rebuilt.artifact_statuses or {}).keys())
    snapshot_git_shas = dict(rebuilt.artifact_git_shas or {})
    snapshot_versions = dict(rebuilt.artifact_versions or {})
    all_artifacts = db.query(Artifact).filter_by(project_id=project_id).all()
    artifacts_restored = 0
    artifacts_deleted = 0

    for art in all_artifacts:
        if art.id not in valid_artifact_ids:
            # Artifact was created after the revert point — clean up references first
            db.query(StageExecution).filter(StageExecution.artifact_id == art.id).update(
                {"artifact_id": None}, synchronize_session="fetch"
            )
            db.query(ArtifactDependency).filter(
                (ArtifactDependency.upstream_artifact_id == art.id)
                | (ArtifactDependency.downstream_artifact_id == art.id)
            ).delete(synchronize_session="fetch")
            db.delete(art)
            artifacts_deleted += 1
        else:
            # Restore status from snapshot
            target_status_str = rebuilt.artifact_statuses[art.id]
            try:
                art.status = ArtifactStatus(target_status_str)
            except ValueError:
                art.status = ArtifactStatus.PENDING

            # Restore version from snapshot if tracked
            if art.id in snapshot_versions:
                art.version = snapshot_versions[art.id]

            # Restore content from git history — prefer exact SHA from snapshot
            if art.file_path:
                try:
                    restore_sha = snapshot_git_shas.get(art.id)
                    if not restore_sha:
                        # Fall back to timestamp-based lookup
                        history = git_manager.get_file_history(project_id, art.file_path)
                        for commit in history:
                            commit_time = dt.fromisoformat(
                                commit["timestamp"].replace("Z", "+00:00")
                            )
                            if commit_time.replace(tzinfo=None) <= target_time.replace(tzinfo=None):
                                restore_sha = commit["sha"]
                                break
                    if restore_sha and restore_sha != art.git_commit_sha:
                        content = git_manager.get_file_at_version(
                            project_id, art.file_path, restore_sha
                        )
                        art.content = content
                        art.git_commit_sha = restore_sha
                        artifacts_restored += 1
                except Exception:
                    logger.warning(
                        "Could not restore git content for artifact %s (%s)",
                        art.id,
                        art.file_path,
                        exc_info=True,
                    )

    # --- Clean up executions and runs created after the revert point ---
    # Delete executions whose run was created after target time
    runs_after = (
        db.query(PipelineRun.run_id)
        .filter_by(project_id=project_id)
        .filter(PipelineRun.started_at > target_time)
        .all()
    )
    run_ids_after = {r[0] for r in runs_after}
    if run_ids_after:
        db.query(StageExecution).filter(
            StageExecution.project_id == project_id,
            StageExecution.run_id.in_(run_ids_after),
        ).delete(synchronize_session="fetch")

    db.query(PipelineRun).filter(
        PipelineRun.project_id == project_id,
        PipelineRun.started_at > target_time,
    ).delete(synchronize_session="fetch")

    db.commit()

    return {
        "status": "reverted",
        "reverted_to_sequence": sequence,
        "events_deleted": deleted_count,
        "artifacts_restored": artifacts_restored,
        "artifacts_deleted": artifacts_deleted,
    }


@pipeline_router.get("/{project_id}/blocking-pr")
def get_blocking_pr(
    project_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    project = _get_project_or_404(db, project_id)
    return {
        "blocking_pr_url": project.blocking_pr_url,
        "blocking_pr_number": project.blocking_pr_number,
    }


@pipeline_router.post("/{project_id}/blocking-pr/check")
async def check_blocking_pr(
    project_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(_require_writer),
):
    """Check the blocking PR on GitHub; clear it if merged or closed."""
    project = _get_project_or_404(db, project_id)
    if not project.blocking_pr_url:
        return {"blocking": False}

    if not project.github_repo_slug or not project.blocking_pr_number:
        # No way to check — clear it
        project.blocking_pr_url = None
        project.blocking_pr_number = None
        db.commit()
        return {"blocking": False}

    from backend.github.service import GitHubService
    from backend.models import GitHubCredential

    cred = db.query(GitHubCredential).filter_by(user_id=user.id).first()
    if not cred:
        raise HTTPException(400, "GitHub not connected. Connect via Settings.")

    gh = GitHubService(cred.access_token)
    pr = await gh.get_pr_status(project.github_repo_slug, project.blocking_pr_number)
    state = pr.get("state")

    if state != "open":
        project.blocking_pr_url = None
        project.blocking_pr_number = None
        db.commit()
        return {"blocking": False, "pr_state": state}

    return {
        "blocking": True,
        "pr_state": state,
        "blocking_pr_url": project.blocking_pr_url,
        "blocking_pr_number": project.blocking_pr_number,
    }


@pipeline_router.post("/{project_id}/blocking-pr/dismiss")
def dismiss_blocking_pr(
    project_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(_require_writer),
):
    """Manually dismiss the blocking PR requirement without checking GitHub."""
    project = _get_project_or_404(db, project_id)
    project.blocking_pr_url = None
    project.blocking_pr_number = None
    db.commit()
    return {"status": "dismissed"}


# ──── Pipeline Runs ────


@pipeline_router.get("/{project_id}/runs")
def list_runs(
    project_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    runs = (
        db.query(PipelineRun)
        .filter_by(project_id=project_id)
        .order_by(PipelineRun.run_number.desc())
        .all()
    )
    return [
        {
            "id": r.id,
            "run_number": r.run_number,
            "run_id": r.run_id,
            "status": r.status.value,
            "ai_loops": r.ai_loops,
            "stop_point": r.stop_point.value,
            "start_stage_key": r.start_stage_key,
            "start_component_key": r.start_component_key,
            "git_commit_sha": r.git_commit_sha,
            "started_at": _utc_iso(r.started_at),
            "completed_at": _utc_iso(r.completed_at),
        }
        for r in runs
    ]


@pipeline_router.get("/{project_id}/runs/{run_number}/state")
def get_run_state(
    project_id: str,
    run_number: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """Return the siege-state.json manifest for a specific completed run."""
    pipeline_run = (
        db.query(PipelineRun).filter_by(project_id=project_id, run_number=run_number).first()
    )
    if not pipeline_run:
        raise HTTPException(404, f"Run #{run_number} not found")
    if not pipeline_run.git_commit_sha:
        raise HTTPException(404, f"Run #{run_number} has no checkpoint commit")

    try:
        import json

        from backend.git_manager.service import git_manager

        content = git_manager.get_file_at_commit(
            project_id, "siege-state.json", pipeline_run.git_commit_sha
        )
        return json.loads(content)
    except Exception as e:
        raise HTTPException(500, f"Failed to load run state: {e}")


@pipeline_router.post("/{project_id}/reconcile")
def reconcile_statuses(
    project_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(_require_writer),
):
    """Rebuild the pipeline snapshot from the event log and sync DB projections.

    The snapshot is the single source of truth. This endpoint rebuilds it
    from events, then syncs DB model status fields to match (repair projections).
    """
    _get_project_or_404(db, project_id)

    from backend.pipeline.reconcile import reconcile_project

    corrections = reconcile_project(db, project_id)

    latest_run = (
        db.query(PipelineRun)
        .filter_by(project_id=project_id)
        .order_by(PipelineRun.run_number.desc())
        .first()
    )

    return {
        "corrections": corrections,
        "orphans_removed": [],
        "run_id": latest_run.run_id if latest_run else None,
        "run_number": latest_run.run_number if latest_run else None,
    }


@pipeline_router.post("/{project_id}/reconstruct")
def reconstruct_from_git(
    project_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(_require_writer),
):
    """Reconstruct pipeline state from the git repository.

    Disaster recovery: rebuilds all artifacts and component definitions
    from siege-state.json + git file content. All artifacts are set to
    AWAITING_REVIEW so the user can inspect them.
    """
    _get_project_or_404(db, project_id)

    from backend.cli.reconstruct import reconstruct_from_git as _reconstruct

    result = _reconstruct(db, project_id)
    return result


@pipeline_router.post("/{project_id}/regenerate")
async def regenerate(
    project_id: str,
    req: RegenerateRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(_require_writer),
):
    order = get_regeneration_order(db, req.artifact_ids)
    return {
        "status": "regeneration_started",
        "order": order,
        "levels": len(order),
    }


@pipeline_router.post("/{project_id}/prompt-preview")
def prompt_preview(
    project_id: str,
    req: PromptPreviewRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """Return the full interpolated prompt that would be sent to the LLM."""
    from backend.models import Artifact
    from backend.pipeline.nodes.generate import build_prompt_messages

    artifact = db.get(Artifact, req.artifact_id)
    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found")
    if artifact.project_id != project_id:
        raise HTTPException(status_code=403, detail="Artifact does not belong to this project")

    config = db.query(PipelineConfig).filter_by(project_id=project_id).first()
    if not config:
        raise HTTPException(404, "Pipeline config not found")

    stage_def = next(
        (s for s in config.stages if s.output_artifact_type == artifact.artifact_type.value),
        None,
    )
    if not stage_def:
        raise HTTPException(status_code=404, detail="No stage definition for this artifact type")

    # Gather input artifacts the same way the engine does
    engine = PipelineEngine(db)
    input_artifacts = engine._gather_inputs(project_id, stage_def, artifact.component_key)

    # Build feedback from comments table (feedback-only)
    feedback_notes = engine._get_feedback_notes(req.artifact_id)
    # Allow draft feedback override for "what-if" preview
    if req.human_notes is not None:
        if feedback_notes:
            effective_notes = f"{feedback_notes}\n\n---\n\n{req.human_notes}"
        else:
            effective_notes = req.human_notes
    else:
        effective_notes = feedback_notes

    result = build_prompt_messages(
        stage_def,
        input_artifacts,
        artifact.component_key,
        feedback=artifact.ai_review_feedback if hasattr(artifact, "ai_review_feedback") else None,
        human_notes=effective_notes,
    )

    return result


@pipeline_router.post("/{project_id}/retry/{execution_id}")
async def retry_stage(
    project_id: str,
    execution_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(_require_writer),
):
    from backend.models import StageExecution

    execution = db.get(StageExecution, execution_id)
    if not execution or execution.project_id != project_id:
        raise HTTPException(404, "Execution not found")
    if execution.status.value != "failed":
        raise HTTPException(400, "Can only retry failed executions")

    cancel_jobs_by_type(db, "retry_stage", execution_id=execution_id)
    enqueue(db, "retry_stage", {"execution_id": execution_id})
    return {"status": "retrying", "execution_id": execution_id}


@pipeline_router.delete("/{project_id}/prune/{artifact_id}")
async def prune_artifact(
    project_id: str,
    artifact_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(_require_writer),
):
    """Prune (delete) an artifact and its associated records from the project."""
    artifact = db.get(Artifact, artifact_id)
    if not artifact:
        raise HTTPException(404, "Artifact not found")
    if artifact.project_id != project_id:
        raise HTTPException(404, "Artifact not found in this project")
    if artifact.status in (ArtifactStatus.GENERATING, ArtifactStatus.AI_REVIEWING):
        raise HTTPException(400, "Cannot prune an artifact that is currently being generated")

    engine = PipelineEngine(db)
    try:
        engine.prune_artifact(project_id, artifact_id)
    except ValueError as e:
        raise HTTPException(400, str(e))

    await ws_manager.broadcast(
        project_id,
        {
            "type": "artifact_pruned",
            "artifact_id": artifact_id,
        },
    )
    return {"status": "pruned", "artifact_id": artifact_id}


@pipeline_router.post("/{project_id}/artifacts/{artifact_id}/reparse")
async def reparse_fanout(
    project_id: str,
    artifact_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(_require_writer),
):
    """Re-parse a fanout artifact to restore missing ComponentDefinitions."""
    engine = PipelineEngine(db)
    try:
        result = engine.reparse_fanout(project_id, artifact_id)
    except ValueError as e:
        raise HTTPException(400, str(e))

    await ws_manager.broadcast(
        project_id,
        {
            "type": "fanout_reparsed",
            "artifact_id": artifact_id,
            "added": result["added"],
            "removed": result["removed"],
        },
    )
    return result


@pipeline_router.get("/{project_id}/artifacts/{artifact_id}/diff")
async def get_artifact_diff(
    project_id: str,
    artifact_id: str,
    version_sha: str | None = None,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """Get a unified diff showing what changed in a specific version.

    If version_sha is provided, diffs that version against its immediate
    predecessor (showing what changed *into* that version).
    Otherwise, diffs the current version against the previous one (using
    prev_git_commit_sha when available to skip self-improvement intermediates).
    """
    import re

    from backend.git_manager.service import git_manager

    artifact = db.get(Artifact, artifact_id)
    if not artifact or artifact.project_id != project_id:
        raise HTTPException(404, "Artifact not found")

    if not artifact.file_path or not artifact.git_commit_sha:
        raise HTTPException(400, "Artifact has no version history")

    history = git_manager.get_file_history(project_id, artifact.file_path)
    if len(history) < 2:
        raise HTTPException(400, "No previous version to diff against")

    # When a specific version is selected, diff it against its predecessor
    # (showing what changed into that version).
    if version_sha:
        current_sha = None
        previous_sha = None
        for i, entry in enumerate(history):
            if entry["sha"] == version_sha:
                current_sha = version_sha
                if i + 1 < len(history):
                    previous_sha = history[i + 1]["sha"]
                break
        if not current_sha:
            raise HTTPException(400, "Specified version not found in history")
        if not previous_sha:
            raise HTTPException(400, "No previous version to diff against for this version")
    else:
        # Default: diff the current artifact version
        current_sha = artifact.git_commit_sha
        previous_sha = None

        # Prefer prev_git_commit_sha — it points to the version before the
        # current generation cycle, skipping intermediate self-improvement
        # commits that would otherwise pollute the diff.
        if artifact.prev_git_commit_sha:
            if any(e["sha"] == artifact.prev_git_commit_sha for e in history):
                previous_sha = artifact.prev_git_commit_sha

        # Fall back to walking git history for the immediate predecessor
        if not previous_sha:
            for i, entry in enumerate(history):
                if entry["sha"] == current_sha and i + 1 < len(history):
                    previous_sha = history[i + 1]["sha"]
                    break

        # Last resort: use the two most recent commits
        if not previous_sha:
            current_sha = history[0]["sha"]
            previous_sha = history[1]["sha"]

    diff_text = git_manager.get_diff(project_id, previous_sha, current_sha, artifact.file_path)

    # Parse version numbers from commit messages for accurate labels
    to_version = artifact.version
    from_version = artifact.version - 1
    for entry in history:
        if entry["sha"] == current_sha:
            m = re.search(r"v(\d+)", entry["message"])
            if m:
                to_version = int(m.group(1))
        if entry["sha"] == previous_sha:
            m = re.search(r"v(\d+)", entry["message"])
            if m:
                from_version = int(m.group(1))

    return {
        "diff": diff_text,
        "from_version": from_version,
        "to_version": to_version,
        "from_sha": previous_sha,
        "to_sha": current_sha,
    }


@pipeline_router.websocket("/{project_id}/ws")
async def pipeline_websocket(
    websocket: WebSocket,
    project_id: str,
    token: str = Query(...),
):
    try:
        decode_token(token)
    except (JWTError, Exception):
        await websocket.close(code=4001, reason="Invalid token")
        return

    await ws_manager.connect(project_id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(project_id, websocket)
