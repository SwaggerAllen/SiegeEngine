"""SQLite-backed job queue for pipeline background tasks.

Jobs are stored in the database and picked up by an in-process async worker loop.
This provides crash recovery (jobs survive restarts), visibility (queryable status),
and backpressure (configurable concurrency).
"""

import asyncio
import logging
import uuid
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.database import SessionLocal
from backend.models.job import Job

logger = logging.getLogger(__name__)

# Singleton worker ID for this process
_WORKER_ID = str(uuid.uuid4())[:8]

# Shutdown event
_shutdown_event = asyncio.Event()

# Notify event — set by enqueue() to wake the worker immediately
_job_notify = asyncio.Event()

# Currently running task — allows cancellation from force-restart
_current_task: asyncio.Task | None = None
_current_job_id: str | None = None


def enqueue(
    db: Session,
    job_type: str,
    payload: dict,
    priority: int = 10,
    max_retries: int = 0,
) -> str:
    """Enqueue a job for background processing. Returns job ID.

    Duplicate-safe: if a queued job with the same type and payload already
    exists, the existing job ID is returned instead of creating a new one.
    """
    import json

    # Check for an existing queued job with the same type + payload to
    # avoid duplicate work (e.g. rapid UI clicks on force-restart).
    payload_json = json.dumps(payload, sort_keys=True)
    existing = (
        db.query(Job)
        .filter(
            Job.job_type == job_type,
            Job.status == "queued",
        )
        .all()
    )
    for candidate in existing:
        if json.dumps(candidate.payload, sort_keys=True) == payload_json:
            logger.info(
                "Dedup: reusing existing queued job %s type=%s",
                candidate.id,
                job_type,
            )
            return candidate.id

    job = Job(
        job_type=job_type,
        payload=payload,
        priority=priority,
        max_retries=max_retries,
    )
    db.add(job)
    db.commit()
    logger.info(f"Enqueued job {job.id} type={job_type}")
    # Wake the worker loop — safe to call from sync code on the event loop
    _job_notify.set()
    return job.id


def cancel_job(db: Session, job_id: str) -> bool:
    """Cancel a queued job. Returns True if cancelled, False if already running/done."""
    job = db.get(Job, job_id)
    if not job or job.status != "queued":
        return False
    job.status = "cancelled"
    db.commit()
    return True


def cancel_jobs_by_type(db: Session, job_type: str, **payload_filters) -> int:
    """Cancel all queued jobs of a given type matching payload filters."""
    jobs = db.query(Job).filter_by(job_type=job_type, status="queued").all()
    cancelled = 0
    for job in jobs:
        if all(job.payload.get(k) == v for k, v in payload_filters.items()):
            job.status = "cancelled"
            cancelled += 1
    if cancelled:
        db.commit()
    return cancelled


def cancel_running_execution(execution_id: str) -> bool:
    """Cancel the currently running job if it's working on *execution_id*.

    This cancels the asyncio Task (which propagates CancelledError through
    the handler and into the CLI subprocess), and also directly kills the
    CLI process for immediate teardown.

    Returns True if a running task was cancelled.
    """
    global _current_task, _current_job_id

    from backend.cli.manager import cli_manager

    # Kill the CLI subprocess first (instant)
    cli_manager.kill_process_for_execution(execution_id)

    # Cancel the asyncio task if it matches
    if _current_task and not _current_task.done():
        # We check the job payload via a tag stored on the task
        task_exec_id = getattr(_current_task, "_execution_id", None)
        if task_exec_id == execution_id:
            logger.info(
                "Cancelling running task for execution %s (job %s)",
                execution_id,
                _current_job_id,
            )
            _current_task.cancel()
            return True

    return False


def _claim_next_sync() -> tuple[str, str, dict] | None:
    """Synchronous: claim the next queued job. Returns (job_id, job_type, payload) or None.

    Runs in a thread pool to avoid blocking the event loop.
    """
    db = SessionLocal()
    try:
        has_queued = db.execute(text("SELECT 1 FROM jobs WHERE status = 'queued' LIMIT 1")).first()
        if not has_queued:
            return None

        now = datetime.utcnow()
        result = db.execute(
            text(
                "UPDATE jobs SET status = 'running', locked_by = :worker, locked_at = :now "
                "WHERE id = ("
                "  SELECT id FROM jobs WHERE status = 'queued' "
                "  ORDER BY priority ASC, created_at ASC LIMIT 1"
                ") RETURNING id"
            ),
            {"worker": _WORKER_ID, "now": now},
        )
        row = result.first()
        db.commit()
        if not row:
            return None
        job = db.get(Job, row[0])
        if not job:
            return None
        return job.id, job.job_type, dict(job.payload)
    finally:
        db.close()


def _complete_job_sync(job_id: str, error: str | None = None) -> None:
    """Synchronous: mark a job as completed or failed. Runs in a thread pool."""
    db = SessionLocal()
    try:
        job = db.get(Job, job_id)
        if not job or job.status != "running":
            return
        if error:
            job.retry_count += 1
            if job.retry_count <= job.max_retries:
                job.status = "queued"
                job.locked_by = None
                job.locked_at = None
                job.error_message = error
                logger.warning(
                    f"Job {job.id} failed (retry {job.retry_count}/{job.max_retries}): {error}"
                )
            else:
                job.status = "failed"
                job.error_message = error
                job.completed_at = datetime.utcnow()
                logger.error(f"Job {job.id} permanently failed: {error}")
        else:
            job.status = "completed"
            job.completed_at = datetime.utcnow()
            logger.info(f"Job {job.id} completed")
        db.commit()
    finally:
        db.close()


# ── Job Handlers ──────────────────────────────────────────────────────────────


async def _handle_start_pipeline(payload: dict) -> None:
    """Handle a start_pipeline job."""
    from backend.pipeline.engine import PipelineEngine

    db = SessionLocal()
    try:
        engine = PipelineEngine(db)
        await engine.start_pipeline(
            payload["project_id"],
            pipeline_run_id=payload.get("pipeline_run_id"),
        )
    finally:
        db.close()


async def _handle_resume_run(payload: dict) -> None:
    """Handle a resume_run job."""
    from backend.pipeline.engine import PipelineEngine

    db = SessionLocal()
    try:
        engine = PipelineEngine(db)
        await engine.resume_run(
            payload["project_id"],
            payload["pipeline_run_id"],
            payload["prev_run_id"],
        )
    finally:
        db.close()


async def _handle_resume_stage(payload: dict) -> None:
    """Handle a resume_stage job."""
    from backend.pipeline.engine import PipelineEngine

    db = SessionLocal()
    try:
        engine = PipelineEngine(db)
        await engine.resume_stage(
            payload["execution_id"],
            payload["action"],
            notes=payload.get("notes"),
            edited_content=payload.get("edited_content"),
            user_id=payload.get("user_id"),
        )
    finally:
        db.close()


async def _handle_revise_artifact(payload: dict) -> None:
    """Handle a revise_artifact job."""
    from backend.pipeline.engine import PipelineEngine

    db = SessionLocal()
    try:
        engine = PipelineEngine(db)
        await engine.revise_artifact(
            payload["artifact_id"],
            payload["feedback"],
            user_id=payload.get("user_id"),
        )
    finally:
        db.close()


async def _handle_resolve_stale(payload: dict) -> None:
    """Handle a resolve_stale job."""
    from backend.pipeline.engine import PipelineEngine

    db = SessionLocal()
    try:
        engine = PipelineEngine(db)
        await engine.resolve_stale(
            payload["artifact_id"],
            payload["action"],
            notes=payload.get("notes"),
            edited_content=payload.get("edited_content"),
            user_id=payload.get("user_id"),
        )
    finally:
        db.close()


async def _handle_retry_stage(payload: dict) -> None:
    """Handle a retry_stage job."""
    from backend.pipeline.engine import PipelineEngine

    db = SessionLocal()
    try:
        engine = PipelineEngine(db)
        from backend.models import StageExecution

        execution = db.get(StageExecution, payload["execution_id"])
        if execution:
            await engine.retry_stage(execution)
    finally:
        db.close()


async def _handle_regen_downstream(payload: dict) -> None:
    """Handle a regen_downstream job."""
    from backend.pipeline.engine import PipelineEngine

    db = SessionLocal()
    try:
        engine = PipelineEngine(db)
        await engine.regen_downstream(
            payload["artifact_id"],
        )
    finally:
        db.close()


async def _handle_trigger_stage(payload: dict) -> None:
    """Handle a trigger_stage job (manual kickoff)."""
    from backend.pipeline.engine import PipelineEngine

    db = SessionLocal()
    try:
        engine = PipelineEngine(db)
        await engine.trigger_stage(
            payload["project_id"],
            payload["stage_key"],
            component_key=payload.get("component_key"),
        )
    finally:
        db.close()


_JOB_HANDLERS = {
    "start_pipeline": _handle_start_pipeline,
    "resume_run": _handle_resume_run,
    "resume_stage": _handle_resume_stage,
    "revise_artifact": _handle_revise_artifact,
    "resolve_stale": _handle_resolve_stale,
    "regen_downstream": _handle_regen_downstream,
    "retry_stage": _handle_retry_stage,
    "trigger_stage": _handle_trigger_stage,
}


# ── Worker Loop ───────────────────────────────────────────────────────────────


async def worker_loop(poll_interval: float = 5.0) -> None:
    """Main worker loop. Waits for job notifications, polls in a thread.

    DB operations run in asyncio.to_thread() so they never block the event loop.
    """
    global _current_task, _current_job_id

    logger.info(f"Job queue worker started (id={_WORKER_ID})")

    while not _shutdown_event.is_set():
        # Wait for either a job notification, shutdown, or the poll timeout
        _job_notify.clear()
        shutdown_task = asyncio.create_task(_shutdown_event.wait())
        notify_task = asyncio.create_task(_job_notify.wait())
        try:
            done, pending = await asyncio.wait(
                [shutdown_task, notify_task],
                timeout=poll_interval,
                return_when=asyncio.FIRST_COMPLETED,
            )
        finally:
            for t in (shutdown_task, notify_task):
                if not t.done():
                    t.cancel()
                    try:
                        await t
                    except asyncio.CancelledError:
                        pass
        if _shutdown_event.is_set():
            break

        # Poll for jobs in a thread to avoid blocking the event loop
        claimed = await asyncio.to_thread(_claim_next_sync)
        if claimed is None:
            continue

        job_id, job_type, payload = claimed

        handler = _JOB_HANDLERS.get(job_type)
        if not handler:
            await asyncio.to_thread(_complete_job_sync, job_id, f"Unknown job type: {job_type}")
            continue

        # Run handler as a tracked task so it can be cancelled by force-restart
        error = None
        asyncio.current_task()
        handler_task = asyncio.create_task(handler(payload))

        # Tag the task with execution_id so cancel_running_execution can match it
        exec_id = payload.get("execution_id")
        handler_task._execution_id = exec_id

        _current_task = handler_task
        _current_job_id = job_id

        try:
            await handler_task
        except asyncio.CancelledError:
            logger.info("Job %s (%s) was cancelled", job_id, job_type)
            error = "Cancelled by force-restart"
        except Exception as e:
            logger.exception(f"Job {job_id} ({job_type}) failed")
            error = str(e)[:1000]
        finally:
            _current_task = None
            _current_job_id = None

        await asyncio.to_thread(_complete_job_sync, job_id, error)

    logger.info("Job queue worker stopped")


def shutdown_worker() -> None:
    """Signal the worker to stop."""
    _shutdown_event.set()
