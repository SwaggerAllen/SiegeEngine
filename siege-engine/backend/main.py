import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.config import settings
from backend.database import SessionLocal, init_db

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Export Anthropic API key so langchain-anthropic can find it
    if settings.anthropic_api_key:
        os.environ.setdefault("ANTHROPIC_API_KEY", settings.anthropic_api_key)

    # Ensure data directories exist
    Path("data/repos").mkdir(parents=True, exist_ok=True)
    init_db()

    # Startup recovery: mark any in-flight executions as failed
    _recover_crashed_executions()

    yield


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

app.include_router(auth_router, prefix="/api/auth", tags=["auth"])
app.include_router(project_router, prefix="/api/projects", tags=["projects"])
app.include_router(pipeline_router, prefix="/api/pipeline", tags=["pipeline"])
app.include_router(dag_router, prefix="/api/dag", tags=["dag"])
app.include_router(github_router, prefix="/api/github", tags=["github"])

# Serve SPA static files (production build)
spa_path = Path("frontend/dist")
if spa_path.exists():
    app.mount("/", StaticFiles(directory=str(spa_path), html=True), name="spa")
