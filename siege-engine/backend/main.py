import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime
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

    # One-time clean slate migration: reset pipeline state, preserve documents
    _clean_slate_migration()

    # Cancel stale jobs BEFORE reconciling so the zombie execution check
    # sees an empty job table and correctly marks everything as dead.
    from backend.pipeline.queue import shutdown_worker, worker_loop

    _cancel_all_jobs_on_startup()

    # Startup recovery: reconcile all projects (rebuild snapshots, fix
    # projection drift, kill orphaned executions, complete zombie runs).
    # At boot time no processes are alive, so every RUNNING execution is
    # a zombie — the reconciler detects this via the empty job table.
    _reconcile_all_projects()

    # One-time migration: move human_review_notes → ArtifactComment records
    _migrate_feedback_to_comments()

    worker_task = asyncio.create_task(worker_loop())

    yield

    # Stop the job queue worker
    shutdown_worker()
    worker_task.cancel()
    try:
        await worker_task
    except asyncio.CancelledError:
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


def _clean_slate_migration():
    """One-time migration: reset pipeline state while preserving document content.

    Deletes all events, snapshots, executions, runs, and jobs for every project.
    Then creates a synthetic completed run with events so the snapshot shows all
    documents as awaiting_review — as if a real run had produced them.

    Preserves: Artifact content, ArtifactComment, ComponentDefinition,
    ArtifactDependency, InputDocument records.
    """
    # Derive data directory from database_url
    db_url = settings.database_url
    if db_url.startswith("sqlite:///"):
        db_dir = Path(
            db_url.replace("sqlite:////", "/", 1)
            if db_url.startswith("sqlite:////")
            else db_url.replace("sqlite:///", "", 1)
        ).parent
    else:
        db_dir = Path("data")

    marker = db_dir / ".clean_slate_v1"
    if marker.exists():
        return

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
    )
    from backend.models.job import Job
    from backend.models.pipeline_events import PipelineEvent, PipelineSnapshot
    from backend.pipeline import events as evt
    from backend.pipeline.event_store import EventStore

    db = SessionLocal()
    try:
        projects = db.query(Project).all()
        if not projects:
            logger.info("Clean slate migration: no projects, writing marker and skipping")
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text("applied")
            return

        logger.info("Clean slate migration: processing %d projects", len(projects))

        for project in projects:
            pid = project.id

            # 1-5. Delete old pipeline state (preserve artifacts, comments, deps)
            db.query(PipelineEvent).filter_by(project_id=pid).delete(synchronize_session="fetch")
            db.query(PipelineSnapshot).filter_by(project_id=pid).delete(synchronize_session="fetch")
            db.query(StageExecution).filter_by(project_id=pid).delete(synchronize_session="fetch")
            db.query(PipelineRun).filter_by(project_id=pid).delete(synchronize_session="fetch")
            # Delete jobs related to this project
            all_jobs = db.query(Job).filter(Job.status.in_(["queued", "running"])).all()
            for job in all_jobs:
                payload = job.payload or {}
                if payload.get("project_id") == pid:
                    db.delete(job)
            db.flush()

            # 6-8. Categorize artifacts
            all_artifacts = db.query(Artifact).filter_by(project_id=pid).all()
            artifacts_with_content = []
            for art in all_artifacts:
                if art.content and art.content.strip():
                    art.status = ArtifactStatus.AWAITING_REVIEW
                    artifacts_with_content.append(art)
                else:
                    art.status = ArtifactStatus.PENDING
            db.flush()

            if not artifacts_with_content:
                logger.info(
                    "  Project %s (%s): no artifacts with content, skipping",
                    project.name,
                    pid,
                )
                continue

            # 9. Build artifact_type → stage_key mapping from PipelineConfig
            config = db.query(PipelineConfig).filter_by(project_id=pid).first()
            # artifact_type -> (stage_key, order_index)
            type_to_stage: dict[str, tuple[str, int]] = {}
            if config:
                for stage_def in config.stages:
                    type_to_stage[stage_def.output_artifact_type] = (
                        stage_def.stage_key,
                        stage_def.order_index,
                    )

            # Fallback mapping from defaults for project_doc type (not in pipeline config)
            if "project_doc" not in type_to_stage:
                type_to_stage["project_doc"] = ("project_doc", -1)

            # 10. Create synthetic completed run
            now = datetime.utcnow()
            synthetic_run = PipelineRun(
                project_id=pid,
                run_number=1,
                status=PipelineRunStatus.COMPLETED,
                stop_point=StopPoint.END_OF_PHASE,
                started_at=now,
                completed_at=now,
            )
            db.add(synthetic_run)
            db.flush()
            run_id = synthetic_run.run_id

            # Sort artifacts by stage order so events are in pipeline order
            def _sort_key(art):
                type_val = art.artifact_type.value
                _, order = type_to_stage.get(type_val, (type_val, 999))
                return order

            sorted_artifacts = sorted(artifacts_with_content, key=_sort_key)

            # 11. Create executions and emit events
            es = EventStore(db)

            es.emit(
                pid,
                evt.RUN_CREATED,
                {
                    "run_id": run_id,
                    "run_number": 1,
                    "ai_loops": 1,
                    "stop_point": "end_of_phase",
                },
                run_id=run_id,
            )

            for art in sorted_artifacts:
                type_val = art.artifact_type.value
                stage_key, _ = type_to_stage.get(type_val, (type_val, 999))

                # Create execution
                execution = StageExecution(
                    project_id=pid,
                    stage_key=stage_key,
                    component_key=art.component_key,
                    status=StageStatus.AWAITING_REVIEW,
                    artifact_id=art.id,
                    run_id=run_id,
                    started_at=art.created_at or now,
                    completed_at=now,
                )
                db.add(execution)
                db.flush()

                # Common payload fields
                base_payload = {
                    "stage_key": stage_key,
                    "component_key": art.component_key,
                    "artifact_id": art.id,
                    "execution_id": execution.id,
                    "artifact_type": type_val,
                    "artifact_name": art.name,
                }

                es.emit(
                    pid,
                    evt.STAGE_STARTED,
                    {
                        **base_payload,
                        "trigger": "clean_slate_migration",
                    },
                    run_id=run_id,
                )

                es.emit(pid, evt.GENERATION_COMPLETED, base_payload, run_id=run_id)

                es.emit(pid, evt.AWAITING_HUMAN_REVIEW, base_payload, run_id=run_id)

            es.emit(
                pid,
                evt.RUN_COMPLETED,
                {
                    "run_id": run_id,
                    "status": "completed",
                },
                run_id=run_id,
            )

            logger.info(
                "  Project %s (%s): migrated %d artifacts, run_id=%s",
                project.name,
                pid,
                len(sorted_artifacts),
                run_id,
            )

        db.commit()
        logger.info("Clean slate migration complete")

        # Write marker file
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("applied")

    except Exception:
        logger.exception("Clean slate migration failed")
        db.rollback()
    finally:
        db.close()


def _cancel_all_jobs_on_startup():
    """Cancel all queued/running jobs on startup.

    At boot time no worker is alive, so any leftover jobs from the
    previous process are stale.  Cancelling them first ensures the
    reconciler's zombie-execution check sees an empty job table and
    correctly marks every RUNNING execution as dead.
    """
    from backend.models.job import Job

    db = SessionLocal()
    try:
        count = (
            db.query(Job)
            .filter(Job.status.in_(["queued", "running"]))
            .update(
                {"status": "cancelled"},
                synchronize_session="fetch",
            )
        )
        db.commit()
        if count:
            logger.info("Startup: cancelled %d stale jobs", count)
    except Exception:
        logger.exception("Failed to cancel stale jobs (non-fatal)")
        db.rollback()
    finally:
        db.close()


def _reconcile_all_projects():
    """Reconcile all projects on startup.

    Rebuilds snapshots from events, syncs DB projections, fixes orphaned
    executions and zombie runs.  This replaces the old approach of just
    marking stuck executions as failed — full reconcile catches all cases
    including projection drift and zombie runs.
    """
    from backend.pipeline.reconcile import reconcile_all_projects

    db = SessionLocal()
    try:
        results = reconcile_all_projects(db)
        if results:
            total = sum(len(c) for c in results.values())
            logger.warning(
                "Startup reconcile: %d corrections across %d projects",
                total,
                len(results),
            )
        else:
            logger.info("Startup reconcile: all projects clean")
    except Exception:
        logger.exception("Startup reconcile failed (non-fatal)")
    finally:
        db.close()


def _migrate_feedback_to_comments():
    """One-time migration: move human_review_notes into ArtifactComment records."""
    import re

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
        total_migrated = 0
        for artifact in artifacts_with_notes:
            raw = artifact.human_review_notes
            logger.info(
                "  Artifact %s (v%d): human_review_notes is %d chars",
                artifact.id,
                artifact.version,
                len(raw),
            )

            # Split accumulated notes by --- dividers.
            # Handle variations: \n\n---\n\n, \r\n\r\n---\r\n\r\n, \n---\n, etc.
            entries = [
                e.strip()
                for e in re.split(r"\r?\n\r?\n---\r?\n\r?\n|\r?\n---\r?\n", raw)
                if e.strip()
            ]
            logger.info(
                "  Split into %d entries for artifact %s",
                len(entries),
                artifact.id,
            )

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
                    total_migrated += 1
            # Clear the old field
            artifact.human_review_notes = None
        db.commit()
        logger.info("Feedback migration complete: %d entries migrated", total_migrated)
    except Exception as e:
        logger.error("Feedback migration failed: %s", e)
        db.rollback()
    finally:
        db.close()


app = FastAPI(title="SiegeEngine", version="0.1.0", lifespan=lifespan)


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API routes
from backend.auth.routes import router as auth_router  # noqa: E402
from backend.chat.routes import router as chat_router  # noqa: E402
from backend.comments.routes import router as comments_router  # noqa: E402
from backend.dag.routes import router as dag_router  # noqa: E402
from backend.github.oauth import router as github_router  # noqa: E402
from backend.pipeline.routes import router as pipeline_router  # noqa: E402
from backend.projects.routes import router as project_router  # noqa: E402

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
        # Fall back to index.html for all SPA routes.
        # Must not be cached so browsers always get the latest chunk URLs after deploys.
        return FileResponse(
            spa_path / "index.html",
            headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
        )
