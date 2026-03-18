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


def enqueue(
    db: Session,
    job_type: str,
    payload: dict,
    priority: int = 10,
    max_retries: int = 0,
) -> str:
    """Enqueue a job for background processing. Returns job ID."""
    job = Job(
        job_type=job_type,
        payload=payload,
        priority=priority,
        max_retries=max_retries,
    )
    db.add(job)
    db.commit()
    logger.info(f"Enqueued job {job.id} type={job_type}")
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


def recover_stale_jobs(db: Session) -> int:
    """Mark any 'running' jobs as 'queued' on startup (crash recovery)."""
    count = (
        db.query(Job)
        .filter_by(status="running")
        .update({"status": "queued", "locked_by": None, "locked_at": None})
    )
    db.commit()
    if count:
        logger.info(f"Recovered {count} stale running jobs")
    return count


def _claim_next(db: Session) -> Job | None:
    """Atomically claim the next queued job. Returns None if queue is empty."""
    # Read-only check first to avoid unnecessary write locks
    has_queued = db.execute(
        text("SELECT 1 FROM jobs WHERE status = 'queued' LIMIT 1")
    ).first()
    if not has_queued:
        return None

    # Atomic claim with write lock
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
    return db.get(Job, row[0])


def _complete_job(db: Session, job: Job, error: str | None = None) -> None:
    """Mark a job as completed or failed."""
    if error:
        job.retry_count += 1
        if job.retry_count <= job.max_retries:
            job.status = "queued"
            job.locked_by = None
            job.locked_at = None
            job.error_message = error
            logger.warning(f"Job {job.id} failed (retry {job.retry_count}/{job.max_retries}): {error}")
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


_JOB_HANDLERS = {
    "start_pipeline": _handle_start_pipeline,
    "resume_run": _handle_resume_run,
    "resume_stage": _handle_resume_stage,
    "revise_artifact": _handle_revise_artifact,
    "resolve_stale": _handle_resolve_stale,
    "retry_stage": _handle_retry_stage,
}


# ── Worker Loop ───────────────────────────────────────────────────────────────

async def worker_loop(poll_interval: float = 2.0) -> None:
    """Main worker loop. Polls the job queue and executes jobs.

    Runs as an asyncio task within the server process.
    """
    logger.info(f"Job queue worker started (id={_WORKER_ID})")

    while not _shutdown_event.is_set():
        db = SessionLocal()
        try:
            job = _claim_next(db)
        finally:
            db.close()

        if job is None:
            try:
                await asyncio.wait_for(_shutdown_event.wait(), timeout=poll_interval)
                break  # Shutdown signaled
            except asyncio.TimeoutError:
                continue

        handler = _JOB_HANDLERS.get(job.job_type)
        if not handler:
            db = SessionLocal()
            try:
                job = db.get(Job, job.id)
                _complete_job(db, job, error=f"Unknown job type: {job.job_type}")
            finally:
                db.close()
            continue

        error = None
        try:
            await handler(job.payload)
        except Exception as e:
            logger.exception(f"Job {job.id} ({job.job_type}) failed")
            error = str(e)[:1000]

        db = SessionLocal()
        try:
            job = db.get(Job, job.id)
            if job and job.status == "running":
                _complete_job(db, job, error=error)
        finally:
            db.close()

    logger.info("Job queue worker stopped")


def shutdown_worker() -> None:
    """Signal the worker to stop."""
    _shutdown_event.set()
