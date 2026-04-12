"""SQLite-backed job queue for pipeline background tasks.

Jobs are stored in the database and picked up by an in-process async worker loop.
This provides crash recovery (jobs survive restarts), visibility (queryable status),
and backpressure (configurable concurrency).
"""

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.database import SessionLocal
from backend.models.job import Job

JobHandler = Callable[[dict], Awaitable[None]]

logger = logging.getLogger(__name__)

# Singleton worker ID for this process
_WORKER_ID = str(uuid.uuid4())[:8]

# Shutdown event
_shutdown_event = asyncio.Event()

# Notify event — set by enqueue() to wake the worker immediately
_job_notify = asyncio.Event()


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
#
# Handlers are registered by the v2 build phase. The queue infrastructure is
# generic and transport-only; it knows nothing about pipeline semantics.

_JOB_HANDLERS: dict[str, JobHandler] = {}


def register_handler(job_type: str, handler: JobHandler) -> None:
    """Register a job handler. Called at app startup by the v2 pipeline."""
    _JOB_HANDLERS[job_type] = handler


# ── Worker Loop ───────────────────────────────────────────────────────────────


async def worker_loop(poll_interval: float = 5.0) -> None:
    """Main worker loop. Waits for job notifications, polls in a thread.

    DB operations run in asyncio.to_thread() so they never block the event loop.
    """
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

        error = None
        try:
            await handler(payload)
        except asyncio.CancelledError:
            logger.info("Job %s (%s) was cancelled", job_id, job_type)
            error = "Cancelled"
        except Exception as e:
            logger.exception(f"Job {job_id} ({job_type}) failed")
            error = str(e)[:1000]

        await asyncio.to_thread(_complete_job_sync, job_id, error)

    logger.info("Job queue worker stopped")


def shutdown_worker() -> None:
    """Signal the worker to stop."""
    _shutdown_event.set()
