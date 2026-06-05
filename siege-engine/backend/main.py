import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.config import settings
from backend.database import SessionLocal, engine, init_db
from backend.pipeline import queue as pipeline_queue

# Configure logging for the whole backend
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    datefmt="%H:%M:%S",
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Export Anthropic API key for langchain-anthropic (structured extraction).
    # CLI subprocesses use their own login credentials and do NOT inherit this.
    if not settings.anthropic_api_key:
        raise RuntimeError(
            "SIEGE_ANTHROPIC_API_KEY is not set. "
            "Add it to your .env file or set it as an environment variable."
        )
    os.environ["ANTHROPIC_API_KEY"] = settings.anthropic_api_key
    logger.info("ANTHROPIC_API_KEY set for API use (%d chars)", len(settings.anthropic_api_key))

    # Ensure data directories exist
    Path(settings.git_repos_base_path).mkdir(parents=True, exist_ok=True)
    init_db()

    # Log database diagnostics so we can tell if the volume mounted correctly
    _log_db_diagnostics()

    # Start the pipeline job-queue worker loop unless disabled.
    # Tests set SIEGE_DISABLE_WORKER_LOOP=1 to drive handlers inline.
    worker_task: asyncio.Task | None = None
    if os.environ.get("SIEGE_DISABLE_WORKER_LOOP"):
        logger.info("SIEGE_DISABLE_WORKER_LOOP set — pipeline worker loop not started")
    else:
        # Reap any rows left in ``status="running"`` from a previous
        # process death. The new worker has no continuation for them,
        # so they're tombstones — flip to ``cancelled`` so the
        # resume-tier flow can pick them back up.
        from backend.database import SessionLocal as _SessionLocal

        _reap_db = _SessionLocal()
        try:
            pipeline_queue.reap_orphaned_running_jobs(_reap_db)
        finally:
            _reap_db.close()
        worker_task = asyncio.create_task(pipeline_queue.worker_loop())
        logger.info("Pipeline worker loop started")

    yield

    # Signal the worker loop to stop and wait briefly for it to drain.
    if worker_task is not None:
        logger.info("Shutting down — stopping pipeline worker loop...")
        pipeline_queue.shutdown_worker()
        try:
            await asyncio.wait_for(worker_task, timeout=5)
        except asyncio.TimeoutError:
            logger.warning("Pipeline worker did not stop in 5s; cancelling")
            worker_task.cancel()
            try:
                await worker_task
            except (asyncio.CancelledError, Exception):
                pass

    # Graceful shutdown: checkpoint WAL so all data is in the main DB file
    # This prevents data loss when Fly.io stops the machine during deploys
    logger.info("Shutting down — checkpointing SQLite WAL...")
    try:
        from sqlalchemy import text as _text

        with engine.begin() as conn:
            conn.execute(_text("PRAGMA wal_checkpoint(TRUNCATE)"))
        engine.dispose()
        logger.info("SQLite WAL checkpointed and connections closed.")
    except Exception as e:
        logger.error("Failed to checkpoint WAL on shutdown: %s", e)


def _log_db_diagnostics():
    """Log database file info at startup to help debug persistence issues."""

    db_url = settings.database_url
    logger.info("Database URL: %s", db_url)

    # Extract file path from sqlite URL
    if db_url.startswith("sqlite:///"):
        db_path = (
            db_url.replace("sqlite:///", "/", 1)
            if db_url.startswith("sqlite:////")
            else db_url.replace("sqlite:///", "", 1)
        )
        db_file = Path(db_path)
        if db_file.exists():
            size_kb = db_file.stat().st_size / 1024
            logger.info("Database file: %s (%.1f KB)", db_file, size_kb)
        else:
            logger.warning("Database file does not exist yet: %s (fresh deploy?)", db_file)

    # Count projects and users as a sanity check
    db = SessionLocal()
    try:
        from backend.models import Project, User

        project_count = db.query(Project).count()
        user_count = db.query(User).count()
        logger.info("Database contains %d projects, %d users", project_count, user_count)
        if project_count == 0 and user_count == 0:
            logger.warning("Database is empty — volume may not have mounted correctly!")
    except Exception as e:
        logger.error("Failed to query database diagnostics: %s", e)
    finally:
        db.close()


COMMIT_HASH = os.environ.get("COMMIT_HASH", "dev")

app = FastAPI(title="SiegeEngine", version="0.1.0", lifespan=lifespan)


@app.get("/healthz")
def healthz():
    return {"status": "ok", "commit": COMMIT_HASH}


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Global exception handler: unhandled server errors get a JSON
# response in the same shape as FastAPI's HTTPException so the
# frontend (which reads ``err.response.data.detail`` for every error)
# shows a useful message instead of a blank "Failed to X" fallback.
#
# The actual traceback is logged server-side; the response only
# carries the exception class name + its stringified message, which
# is safe to surface to the user and specific enough to debug from.
@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception(
        "Unhandled exception in %s %s: %s",
        request.method,
        request.url.path,
        exc,
    )
    # Short-circuit for subclasses that FastAPI handles natively —
    # this handler is the fallback for anything else that bubbles up.
    from fastapi.exceptions import HTTPException as FastAPIHTTPException
    from starlette.exceptions import HTTPException as StarletteHTTPException

    if isinstance(exc, (FastAPIHTTPException, StarletteHTTPException)):
        raise exc  # let FastAPI's own handler take it
    detail = f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__
    return JSONResponse(
        status_code=500,
        content={"detail": detail},
    )


# API routes
# Importing backend.graph has the side effect of registering the
# v2.apply_instructions handler with the pipeline job queue.
import backend.graph  # noqa: E402,F401
from backend.auth.routes import router as auth_router  # noqa: E402
from backend.github.oauth import router as github_router  # noqa: E402
from backend.graph.debug_routes import router as debug_router  # noqa: E402
from backend.graph.input_documents_routes import router as input_docs_router  # noqa: E402
from backend.graph.jobs_routes import router as jobs_router  # noqa: E402
from backend.graph.queue_routes import router as queue_router  # noqa: E402
from backend.graph.routes import router as graph_router  # noqa: E402
from backend.projects.routes import router as project_router  # noqa: E402

app.include_router(auth_router, prefix="/api/auth", tags=["auth"])
app.include_router(project_router, prefix="/api/projects", tags=["projects"])
app.include_router(graph_router, prefix="/api/projects", tags=["graph"])
app.include_router(queue_router, prefix="/api/projects", tags=["queue"])
app.include_router(jobs_router, prefix="/api/projects", tags=["jobs"])
app.include_router(debug_router, prefix="/api/projects", tags=["debug"])
app.include_router(input_docs_router, prefix="/api/projects", tags=["input-documents"])
app.include_router(github_router, prefix="/api/github", tags=["github"])

# Mount the siege read API — the dashboard's read-only projection of
# project git state. Dormant until the graph viz is repointed to it
# (migration step 6); the legacy write surface above is deleted in
# step 8.
from siege.server import app as siege_app  # noqa: E402

app.mount("/siege", siege_app)


# Serve SPA static files (production build)
spa_path = Path("frontend/dist")
if spa_path.exists():
    # Mount static assets (JS, CSS, images) at /assets
    assets_path = spa_path / "assets"
    if assets_path.exists():
        app.mount("/assets", StaticFiles(directory=str(assets_path)), name="assets")

    # Serve other static files (favicon, etc.) and SPA catch-all
    @app.get("/{full_path:path}")
    async def serve_spa(request: Request, full_path: str):
        """Serve static files if they exist, otherwise return index.html for SPA routing."""
        # Try to serve the exact file first (e.g., favicon.ico, robots.txt)
        file_path = spa_path / full_path
        if full_path and file_path.is_file():
            return FileResponse(file_path)
        # Fall back to index.html for all SPA routes.
        # Must not be cached so browsers always get the latest chunk URLs after deploys.
        return FileResponse(
            spa_path / "index.html",
            headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
        )
