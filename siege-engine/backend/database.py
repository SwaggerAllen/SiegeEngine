from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from backend.config import settings


class Base(DeclarativeBase):
    pass


engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False, "timeout": 30},
    echo=False,
)

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


def init_db():
    Base.metadata.create_all(bind=engine)
    # Enable WAL mode for better concurrent access
    with engine.begin() as conn:
        conn.execute(text("PRAGMA journal_mode=WAL"))
        conn.execute(text("PRAGMA busy_timeout=30000"))
    _migrate_missing_columns()


def _migrate_missing_columns():
    """Add columns that create_all won't add to existing tables (SQLite limitation)."""
    inspector = inspect(engine)
    # PipelineConfig.review_prompt_overrides
    if inspector.has_table("pipeline_configs"):
        columns = [c["name"] for c in inspector.get_columns("pipeline_configs")]
        if "review_prompt_overrides" not in columns:
            with engine.begin() as conn:
                conn.execute(text(
                    "ALTER TABLE pipeline_configs ADD COLUMN review_prompt_overrides JSON"
                ))

    # Project.auto_push_enabled
    if inspector.has_table("projects"):
        columns = [c["name"] for c in inspector.get_columns("projects")]
        if "auto_push_enabled" not in columns:
            with engine.begin() as conn:
                conn.execute(text(
                    "ALTER TABLE projects ADD COLUMN auto_push_enabled BOOLEAN DEFAULT 0"
                ))


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
