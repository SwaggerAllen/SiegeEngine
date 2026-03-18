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
        human_review=req.human_review,
        ai_loops=req.ai_loops,
        stop_point=StopPoint(req.stop_point),
    )
    db.add(pipeline_run)
    db.commit()
    db.refresh(pipeline_run)

    logger.info(
        "POST /start: project_id=%s, run_number=%d, human_review=%s, ai_loops=%d, stop_point=%s",
        project_id,
        run_number,
        req.human_review,
        req.ai_loops,
        req.stop_point,
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
        human_review=req.human_review,
        ai_loops=req.ai_loops,
        stop_point=StopPoint(req.stop_point),
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

        run_label = active_runs[0].run_number if active_runs else "cancelled"
        branch = f"siege-engine/{project.name.lower().replace(' ', '-')}"
        pr_title = req.pr_title or f"Cancelled run #{run_label} — review before continuing"
        pr_body = (
            req.pr_body
            or "This PR was created when a pipeline run was cancelled."
            " Merge or close it to unblock new runs."
        )

        auth_url = None
        if project.remote_url and project.remote_url.startswith("https://"):
            auth_url = project.remote_url.replace(
                "https://", f"https://x-access-token:{cred.access_token}@"
            )
        git_manager.push_branch(project_id, branch, auth_url=auth_url)

        gh = GitHubService(cred.access_token)
        pr = await gh.create_pr(
            project.github_repo_slug,
            pr_title,
            pr_body,
            branch,
            req.base_branch,
        )

        project.blocking_pr_url = pr.get("html_url")
        project.blocking_pr_number = pr.get("number")
        db.commit()

        result["pr_url"] = project.blocking_pr_url
        result["pr_number"] = project.blocking_pr_number

    return result


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
        ]
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
            "human_review": r.human_review,
            "ai_loops": r.ai_loops,
            "stop_point": r.stop_point.value,
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

    # Current version is history[0], previous is history[1]
    current_sha = history[0]["sha"]
    previous_sha = history[1]["sha"]

    diff_text = git_manager.get_diff(project_id, previous_sha, current_sha, artifact.file_path)

    return {
        "diff": diff_text,
        "from_version": artifact.version - 1,
        "to_version": artifact.version,
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
