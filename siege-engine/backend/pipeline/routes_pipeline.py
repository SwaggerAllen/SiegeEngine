import logging
from datetime import datetime

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
from backend.pipeline.queue import enqueue
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

    enqueue(db, "start_pipeline", {
        "project_id": project_id,
        "pipeline_run_id": pipeline_run_id,
    })

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

    enqueue(db, "resume_run", {
        "project_id": project_id,
        "pipeline_run_id": pipeline_run_id,
        "prev_run_id": prev_run_id,
    })

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
    stale_count = (
        db.query(Artifact)
        .filter_by(project_id=project_id, status=ArtifactStatus.STALE)
        .count()
    )
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

    enqueue(db, "resume_run", {
        "project_id": project_id,
        "pipeline_run_id": pipeline_run.id,
        "prev_run_id": pipeline_run.run_id,
    })

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

    # Mark all running/pending executions as failed
    running = (
        db.query(StageExecution)
        .filter_by(project_id=project_id)
        .filter(
            StageExecution.status.in_(
                [StageStatus.RUNNING, StageStatus.PENDING, StageStatus.AI_REVIEW]
            )
        )
        .all()
    )
    for e in running:
        e.status = StageStatus.FAILED
        e.error_message = "Cancelled by user"

    # Reset in-progress artifacts back to pending so they don't stay stuck
    in_progress_artifacts = (
        db.query(Artifact)
        .filter_by(project_id=project_id)
        .filter(Artifact.status.in_([ArtifactStatus.GENERATING, ArtifactStatus.AI_REVIEWING]))
        .all()
    )
    for a in in_progress_artifacts:
        a.status = ArtifactStatus.PENDING

    # Also mark any active PipelineRun as cancelled
    active_runs = (
        db.query(PipelineRun)
        .filter_by(project_id=project_id, status=PipelineRunStatus.RUNNING)
        .all()
    )
    for r in active_runs:
        r.status = PipelineRunStatus.CANCELLED
        r.completed_at = datetime.utcnow()

    db.commit()

    result = {"status": "cancelled", "cancelled_count": len(running)}

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
            if hasattr(e, 'response') and e.response is not None:
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
    """Reset pipeline to a clean slate.

    Cancels all active runs, puts every artifact with content into
    AWAITING_REVIEW, and ensures each has an execution the next Resume
    can carry over.  Artifacts without content become PENDING.
    """
    project = _get_project_or_404(db, project_id)

    # 1. Cancel all active pipeline runs
    active_runs = (
        db.query(PipelineRun)
        .filter_by(project_id=project_id, status=PipelineRunStatus.RUNNING)
        .all()
    )
    for r in active_runs:
        r.status = PipelineRunStatus.CANCELLED
        r.completed_at = datetime.utcnow()

    # 2. Fail all in-flight executions
    in_flight = (
        db.query(StageExecution)
        .filter_by(project_id=project_id)
        .filter(
            StageExecution.status.in_(
                [StageStatus.RUNNING, StageStatus.PENDING, StageStatus.AI_REVIEW]
            )
        )
        .all()
    )
    for e in in_flight:
        e.status = StageStatus.FAILED
        e.error_message = "Reset by user"
        e.completed_at = e.completed_at or datetime.utcnow()

    db.flush()

    # 3. Determine which run to attach reset executions to.
    #    Use the most recent cancelled/completed run so Resume can find them.
    latest_run = (
        db.query(PipelineRun)
        .filter_by(project_id=project_id)
        .order_by(PipelineRun.run_number.desc())
        .first()
    )
    if not latest_run:
        # No runs at all — create a synthetic one
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

    # 4. Reset artifacts and their executions
    all_artifacts = (
        db.query(Artifact)
        .filter_by(project_id=project_id)
        .all()
    )

    reset_count = 0
    for artifact in all_artifacts:
        if artifact.content and artifact.content.strip():
            artifact.status = ArtifactStatus.AWAITING_REVIEW

            # Find or create an AWAITING_REVIEW execution in the target run
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
            reset_count += 1
        else:
            artifact.status = ArtifactStatus.PENDING

    db.commit()

    # Emit pipeline_reset event
    from backend.pipeline.event_store import EventStore
    from backend.pipeline import events as _evt
    EventStore(db).emit(project_id, _evt.PIPELINE_RESET, {}, run_id=run_id)
    db.commit()

    await ws_manager.broadcast(
        project_id,
        {
            "type": "pipeline_completed",
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

    return {
        "stages": [
            {
                "id": e.id,
                "stage_key": e.stage_key,
                "component_key": e.component_key,
                "status": e.status.value,
                "artifact_id": e.artifact_id,
                "started_at": e.started_at.isoformat() if e.started_at else None,
                "completed_at": e.completed_at.isoformat() if e.completed_at else None,
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


@pipeline_router.get("/{project_id}/snapshot")
def get_snapshot(
    project_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """Return the materialized pipeline snapshot."""
    from backend.pipeline.event_store import EventStore
    es = EventStore(db)
    snapshot = es.get_snapshot(project_id)
    return {
        "is_running": snapshot.is_running,
        "is_paused": snapshot.is_paused,
        "paused_stage": snapshot.paused_stage,
        "current_run_id": snapshot.current_run_id,
        "stage_statuses": snapshot.stage_statuses or {},
        "artifact_statuses": snapshot.artifact_statuses or {},
        "run_status": snapshot.run_status or {},
        "last_sequence": snapshot.last_sequence,
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

    query = (
        db.query(PipelineEvent)
        .filter_by(project_id=project_id)
    )
    if run_id:
        query = query.filter(PipelineEvent.run_id == run_id)
    if event_type:
        query = query.filter(PipelineEvent.event_type == event_type)

    total = query.count()
    events = (
        query
        .order_by(PipelineEvent.sequence.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

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
        arts = (
            db.query(Artifact.id, Artifact.name)
            .filter(Artifact.id.in_(artifact_ids))
            .all()
        )
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
                "created_at": e.created_at.isoformat() if e.created_at else None,
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
        db.query(PipelineEvent)
        .filter_by(project_id=project_id, sequence=sequence)
        .first()
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
            db.query(StageExecution).filter(
                StageExecution.artifact_id == art.id
            ).update({"artifact_id": None}, synchronize_session="fetch")
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
                            commit_time = dt.fromisoformat(commit["timestamp"].replace("Z", "+00:00"))
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
                        art.id, art.file_path, exc_info=True,
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
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "completed_at": r.completed_at.isoformat() if r.completed_at else None,
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
    """Rebuild the pipeline snapshot from the event log.

    Reconciliation is no longer needed since the event-sourced snapshot
    is the single source of truth. This endpoint now rebuilds the
    materialized snapshot in case it drifts.
    """
    _get_project_or_404(db, project_id)

    from backend.pipeline.event_store import EventStore
    es = EventStore(db)
    es.rebuild_snapshot(project_id)
    db.commit()

    latest_run = (
        db.query(PipelineRun)
        .filter_by(project_id=project_id)
        .order_by(PipelineRun.run_number.desc())
        .first()
    )

    return {
        "corrections": [],
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
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """Get a unified diff between the current and previous version of an artifact."""
    from backend.git_manager.service import git_manager

    artifact = db.get(Artifact, artifact_id)
    if not artifact or artifact.project_id != project_id:
        raise HTTPException(404, "Artifact not found")

    if not artifact.file_path or not artifact.git_commit_sha:
        raise HTTPException(400, "Artifact has no version history")

    # Get the file history to find the previous version
    history = git_manager.get_file_history(project_id, artifact.file_path)
    if len(history) < 2:
        raise HTTPException(400, "No previous version to diff against")

    # Use the artifact's known commit SHA as current, find its predecessor
    current_sha = artifact.git_commit_sha
    previous_sha = None
    for i, entry in enumerate(history):
        if entry["sha"] == current_sha and i + 1 < len(history):
            previous_sha = history[i + 1]["sha"]
            break

    # Fallback: if artifact SHA not found in history, use latest two
    if not previous_sha:
        current_sha = history[0]["sha"]
        previous_sha = history[1]["sha"]

    diff_text = git_manager.get_diff(project_id, previous_sha, current_sha, artifact.file_path)

    # Parse version numbers from commit messages for accurate labels
    import re
    to_version = artifact.version
    from_version = artifact.version - 1
    for entry in history:
        if entry["sha"] == previous_sha:
            m = re.search(r"v(\d+)", entry["message"])
            if m:
                from_version = int(m.group(1))
            break

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
