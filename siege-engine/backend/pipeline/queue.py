"""SQLite-backed job queue for pipeline background tasks.

Jobs are stored in the database and picked up by an in-process async worker loop.
This provides crash recovery (jobs survive restarts), visibility (queryable status),
and backpressure (configurable concurrency).
"""

import asyncio
import logging
import uuid
from collections.abc import Callable, Coroutine
from contextvars import ContextVar
from datetime import datetime
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from backend.database import SessionLocal
from backend.models.job import Job

JobHandler = Callable[[dict], Coroutine[Any, Any, None]]

logger = logging.getLogger(__name__)

# Current job ID, scoped to the asyncio task running a handler. Set by
# ``worker_loop`` before dispatching the handler task and read by any
# code that wants to surface handler-side progress back onto the Job
# row (e.g. ``run_parse_validate_loop`` bumping the current attempt
# counter). ``None`` outside a handler task.
current_job_id_var: ContextVar[str | None] = ContextVar("current_job_id", default=None)

# Singleton worker ID for this process
_WORKER_ID = str(uuid.uuid4())[:8]

# Shutdown event
_shutdown_event = asyncio.Event()

# Notify event — set by enqueue() to wake the worker immediately
_job_notify = asyncio.Event()

# Registry of in-flight handler tasks, keyed by job_id. Populated when
# the worker loop claims a job and wraps its handler in a task;
# removed in the ``finally`` after the task completes. Used by
# :func:`cancel_job` so an HTTP route can cancel a running generation
# by propagating ``asyncio.CancelledError`` into the handler (which in
# turn kills the CLI subprocess — see ``backend.cli.manager._invoke``).
_active_handler_tasks: dict[str, asyncio.Task] = {}

# Default priority for a generation / mint job. Lower number wins.
DEFAULT_JOB_PRIORITY = 10
# AI self-review jobs run in the same single-worker queue as
# generations but jump ahead of pending generations so a finished
# draft gets its critique while the user is still looking at it,
# rather than waiting behind every queued downstream regen.
REVIEW_JOB_PRIORITY = 5


def enqueue(
    db: Session,
    job_type: str,
    payload: dict,
    priority: int = 10,
    max_retries: int = 0,
    *,
    batch_id: str | None = None,
) -> str:
    """Enqueue a job for background processing. Returns job ID.

    Duplicate-safe: if a queued job with the same type, payload, and
    batch_id already exists, the existing job ID is returned instead
    of creating a new one. ``batch_id`` participates in dedup so the
    same logical job under two different batches doesn't collapse
    into one.

    When ``batch_id`` is set, the value is stamped onto both the
    ``Job.batch_id`` column (for batch-scoped queries) and the job
    payload (so handlers can read it without a Job lookup —
    bootstrap-generation reads it to stamp ``Draft.batch_id`` so
    multi-draft tier-ops share one batch on the resulting drafts).
    """
    import json

    if batch_id is not None and "batch_id" not in payload:
        # Mutate-in-place is fine — the caller is building a fresh
        # dict for this enqueue call. Keeping the field in the
        # payload makes it visible to handlers without a Job
        # lookup, which matters because handlers may run in a
        # different DB session.
        payload = {**payload, "batch_id": batch_id}

    # Check for an existing queued job with the same type + payload to
    # avoid duplicate work (e.g. rapid UI clicks on force-restart).
    # batch_id is part of the payload above so it participates in
    # this comparison.
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
        batch_id=batch_id,
    )
    db.add(job)
    db.commit()
    logger.info(f"Enqueued job {job.id} type={job_type} batch_id={batch_id or '-'}")
    # Wake the worker loop — safe to call from sync code on the event loop
    _job_notify.set()
    return job.id


def cancel_job(db: Session, job_id: str) -> bool:
    """Cancel a job. Works for both queued and running jobs.

    - Queued jobs are marked ``cancelled`` directly.
    - Running jobs have their handler task cancelled via the
      active-tasks registry. The worker loop's ``CancelledError``
      handler then marks the row ``cancelled`` once the handler
      unwinds (the CLI manager kills the subprocess on
      ``CancelledError``).

    Returns True if the cancel was dispatched, False if the job
    doesn't exist or is already in a terminal state.

    Thread-safety: this function is safe to call from FastAPI's
    sync route thread pool. Task cancellation crosses threads via
    ``loop.call_soon_threadsafe``.
    """
    job = db.get(Job, job_id)
    if not job:
        return False
    if job.status == "queued":
        job.status = "cancelled"
        job.completed_at = datetime.utcnow()
        db.commit()
        return True
    if job.status == "running":
        task = _active_handler_tasks.get(job_id)
        if task is None or task.done():
            # Task ref lost or already finishing — best we can do is
            # report failure; the worker's own completion path will
            # write the final row status.
            return False
        loop = task.get_loop()
        loop.call_soon_threadsafe(task.cancel)
        return True
    return False


def cancel_jobs_by_type(
    db: Session,
    job_type: str,
    *,
    exclude_batch_id: str | None = None,
    **payload_filters: Any,
) -> int:
    """Cancel all queued or running jobs of a given type matching payload filters.

    Returns the number of jobs cancelled. Running jobs are cancelled
    via the active-tasks registry (see :func:`cancel_job`); queued
    jobs are marked ``cancelled`` directly in the DB.

    ``exclude_batch_id`` (optional) — jobs whose ``Job.batch_id``
    matches this value are preserved. Used by multi-scope batch
    operations (cohort regenerate, exploration-sample, full-corpus)
    so each iteration's cancel sweep doesn't cannibalise sibling
    jobs already queued under the same batch.
    """
    jobs = (
        db.query(Job).filter(Job.job_type == job_type, Job.status.in_(["queued", "running"])).all()
    )
    cancelled = 0
    commit_needed = False
    for job in jobs:
        if exclude_batch_id is not None and job.batch_id == exclude_batch_id:
            continue
        if not all((job.payload or {}).get(k) == v for k, v in payload_filters.items()):
            continue
        if job.status == "queued":
            job.status = "cancelled"
            job.completed_at = datetime.utcnow()
            commit_needed = True
            cancelled += 1
        elif job.status == "running":
            task = _active_handler_tasks.get(job.id)
            if task is not None and not task.done():
                task.get_loop().call_soon_threadsafe(task.cancel)
                cancelled += 1
    if commit_needed:
        db.commit()
    return cancelled


def reap_orphaned_running_jobs(db: Session) -> int:
    """Mark every ``status='running'`` job as cancelled.

    Called from the lifespan startup hook before the worker loop
    begins polling. The pipeline runs as a single in-process worker
    (``backend.main`` starts exactly one ``worker_loop`` task per
    process), so any row in ``running`` at startup is a tombstone
    from a previous process that died mid-flight — there is no
    in-process continuation that could finish it.

    Marks them ``cancelled`` (rather than ``failed``) with an
    explicit ``error_message`` so the queue panel surfaces the
    "abandoned at restart" reason rather than reading like a real
    failure. The Resume Tier flow's "latest review/gen was
    cancelled → resume-eligible" rule then picks them up on the
    next click.

    Returns the number of rows reaped.
    """
    rows = db.query(Job).filter(Job.status == "running").all()
    if not rows:
        return 0
    now = datetime.utcnow()
    for job in rows:
        job.status = "cancelled"
        job.error_message = "Abandoned at server restart"
        job.completed_at = now
    db.commit()
    logger.info("Reaped %d orphaned running jobs at startup", len(rows))
    return len(rows)


def find_active_job(
    db: Session,
    job_type: str,
    payload_filters: dict | None = None,
) -> Job | None:
    """Return the most recent queued/running job matching type + payload filters.

    Used by cancel routes to locate the job to cancel without the
    client needing to track job IDs. ``payload_filters`` is matched
    against ``job.payload`` subset-wise; a filter of ``{"project_id":
    "p1"}`` matches any job with that project_id regardless of other
    payload keys.
    """
    filters = dict(payload_filters or {})
    rows = (
        db.execute(
            select(Job)
            .where(Job.job_type == job_type, Job.status.in_(["queued", "running"]))
            .order_by(Job.created_at.desc())
            .limit(50)
        )
        .scalars()
        .all()
    )
    for job in rows:
        payload = job.payload or {}
        if all(payload.get(k) == v for k, v in filters.items()):
            return job
    return None


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


def _complete_job_sync(job_id: str, error: str | None = None, cancelled: bool = False) -> None:
    """Synchronous: mark a job as completed, failed, or cancelled.

    Runs in a thread pool. ``cancelled=True`` takes precedence over
    ``error`` and marks the row ``cancelled`` (no retries) so the
    UI's ``latest_generation_status`` reads it as idle and the user
    can give feedback again.
    """
    db = SessionLocal()
    try:
        job = db.get(Job, job_id)
        if not job or job.status != "running":
            return
        if cancelled:
            job.status = "cancelled"
            job.error_message = error or "Cancelled"
            job.completed_at = datetime.utcnow()
            logger.info(f"Job {job.id} cancelled")
        elif error:
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


def _complete_deferred_job_sync(job_id: str) -> None:
    """Synchronous: mark a deferred job as completed without recording a failure.

    Phase F: handlers can raise :class:`TierDeferredError` when a
    readiness predicate signals "retry later" (e.g. a comparch's
    dep is mid-regen). The worker completes the job cleanly here —
    no failure on the row, no retry — and the wakeup hook on the
    blocking dep's persist re-enqueues a fresh job. The row is
    tagged ``status="completed"`` with an ``error_message`` body
    so observability can tell deferred completions apart from
    regular ones; the message is informational, not a failure
    signal.
    """
    db = SessionLocal()
    try:
        job = db.get(Job, job_id)
        if not job or job.status != "running":
            return
        job.status = "completed"
        job.is_deferred = True
        job.error_message = "readiness predicate signalled retry-later"
        job.completed_at = datetime.utcnow()
        logger.info(f"Job {job.id} completed (deferred)")
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

        # Wrap the handler in its own task so an external caller
        # (the /cancel HTTP route) can cancel it without cancelling
        # the worker loop itself. The task is registered in
        # ``_active_handler_tasks`` while it runs so ``cancel_job``
        # can reach it.
        #
        # The ``current_job_id_var`` contextvar is set before the
        # handler task is created so every coroutine spawned from
        # the handler inherits the job id — handlers use this to
        # post progress (e.g. parse-validate attempt counters) back
        # onto the Job row without threading the id through every
        # helper.
        error: str | None = None
        cancelled = False
        token = current_job_id_var.set(job_id)
        try:
            handler_task: asyncio.Task[None] = asyncio.create_task(handler(payload))
        finally:
            current_job_id_var.reset(token)
        _active_handler_tasks[job_id] = handler_task
        deferred = False
        try:
            await handler_task
        except asyncio.CancelledError:
            logger.info("Job %s (%s) was cancelled", job_id, job_type)
            cancelled = True
            error = "Cancelled"
        except Exception as e:
            # Phase F: TierDeferredError signals "retry later" without
            # recording a failure. Worker completes the job cleanly;
            # the staleness ledger row stays so the wakeup hook (or a
            # future cascade trigger) re-enqueues this work.
            from backend.graph.handlers._tier_generation import TierDeferredError

            if isinstance(e, TierDeferredError):
                logger.info(
                    "Job %s (%s) deferred: %s",
                    job_id,
                    job_type,
                    str(e)[:500],
                )
                deferred = True
            else:
                logger.exception(f"Job {job_id} ({job_type}) failed")
                error = str(e)[:1000]
        finally:
            _active_handler_tasks.pop(job_id, None)
        # Deferred jobs complete cleanly with status="done" + a
        # marker on the row so observability can distinguish them
        # from regular completions.
        if deferred:
            await asyncio.to_thread(_complete_deferred_job_sync, job_id)
            continue

        await asyncio.to_thread(_complete_job_sync, job_id, error, cancelled)

    logger.info("Job queue worker stopped")


def shutdown_worker() -> None:
    """Signal the worker to stop."""
    _shutdown_event.set()
