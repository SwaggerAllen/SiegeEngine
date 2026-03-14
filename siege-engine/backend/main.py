import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.config import settings
from backend.database import SessionLocal, engine, init_db

# Configure logging for the whole backend
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    datefmt="%H:%M:%S",
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Export Anthropic API key so langchain-anthropic can find it.
    # Use direct assignment (not setdefault) so SIEGE_ANTHROPIC_API_KEY
    # always takes precedence over any stale ANTHROPIC_API_KEY in the env.
    if not settings.anthropic_api_key:
        raise RuntimeError(
            "SIEGE_ANTHROPIC_API_KEY is not set. "
            "Add it to your .env file or set it as an environment variable."
        )
    os.environ["ANTHROPIC_API_KEY"] = settings.anthropic_api_key
    logger.info("ANTHROPIC_API_KEY set from config (%d chars)", len(settings.anthropic_api_key))

    # Ensure data directories exist
    Path(settings.git_repos_base_path).mkdir(parents=True, exist_ok=True)
    init_db()

    # Log database diagnostics so we can tell if the volume mounted correctly
    _log_db_diagnostics()

    # Startup recovery: mark any in-flight executions as failed
    _recover_crashed_executions()

    # One-time migration: move human_review_notes → ArtifactComment records
    _migrate_feedback_to_comments()

    yield

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
    from sqlalchemy import text as _text

    db_url = settings.database_url
    logger.info("Database URL: %s", db_url)

    # Extract file path from sqlite URL
    if db_url.startswith("sqlite:///"):
        db_path = db_url.replace("sqlite:///", "/", 1) if db_url.startswith("sqlite:////") else db_url.replace("sqlite:///", "", 1)
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


def _recover_crashed_executions():
    """Mark RUNNING/AI_REVIEW executions as FAILED after a server restart."""
    from backend.models import StageExecution, StageStatus

    db = SessionLocal()
    try:
        stuck = (
            db.query(StageExecution)
            .filter(StageExecution.status.in_([StageStatus.RUNNING, StageStatus.AI_REVIEW]))
            .all()
        )
        if stuck:
            logger.warning("Recovering %d stuck executions from previous run", len(stuck))
            for execution in stuck:
                execution.status = StageStatus.FAILED
                execution.error_message = "Server restarted during execution"
            db.commit()
    finally:
        db.close()


def _migrate_feedback_to_comments():
    """One-time migration: move human_review_notes into ArtifactComment records."""
    from backend.models import Artifact, ArtifactComment

    db = SessionLocal()
    try:
        artifacts_with_notes = (
            db.query(Artifact)
            .filter(Artifact.human_review_notes.isnot(None))
            .filter(Artifact.human_review_notes != "")
            .all()
        )
        if not artifacts_with_notes:
            return

        logger.info("Migrating human_review_notes for %d artifacts", len(artifacts_with_notes))
        for artifact in artifacts_with_notes:
            # Split accumulated notes by --- dividers into individual entries
            entries = [
                e.strip()
                for e in artifact.human_review_notes.split("\n\n---\n\n")
                if e.strip()
            ]
            for entry in entries:
                # Idempotent: skip if this exact feedback already exists
                existing = (
                    db.query(ArtifactComment)
                    .filter_by(
                        artifact_id=artifact.id,
                        comment_type="feedback",
                        content=entry,
                    )
                    .first()
                )
                if not existing:
                    comment = ArtifactComment(
                        artifact_id=artifact.id,
                        project_id=artifact.project_id,
                        author_id=None,  # No author info in legacy data
                        content=entry,
                        comment_type="feedback",
                        artifact_version=artifact.version,
                    )
                    db.add(comment)
            # Clear the old field
            artifact.human_review_notes = None
        db.commit()
        logger.info("Feedback migration complete")
    except Exception as e:
        logger.error("Feedback migration failed: %s", e)
        db.rollback()
    finally:
        db.close()


app = FastAPI(title="SiegeEngine", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API routes
from backend.auth.routes import router as auth_router  # noqa: E402
from backend.projects.routes import router as project_router  # noqa: E402
from backend.pipeline.routes import router as pipeline_router  # noqa: E402
from backend.dag.routes import router as dag_router  # noqa: E402
from backend.github.oauth import router as github_router  # noqa: E402
from backend.chat.routes import router as chat_router  # noqa: E402
from backend.comments.routes import router as comments_router  # noqa: E402

app.include_router(auth_router, prefix="/api/auth", tags=["auth"])
app.include_router(project_router, prefix="/api/projects", tags=["projects"])
app.include_router(pipeline_router, prefix="/api/pipeline", tags=["pipeline"])
app.include_router(dag_router, prefix="/api/dag", tags=["dag"])
app.include_router(github_router, prefix="/api/github", tags=["github"])
app.include_router(chat_router, prefix="/api/chat", tags=["chat"])
app.include_router(comments_router, prefix="/api/comments", tags=["comments"])

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
        # Fall back to index.html for all SPA routes
        return FileResponse(spa_path / "index.html")
