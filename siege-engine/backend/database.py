from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from backend.config import settings

# Resolve alembic.ini relative to the project root (one level above backend/)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_ALEMBIC_INI = str(_PROJECT_ROOT / "alembic.ini")


class Base(DeclarativeBase):
    pass


engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False, "timeout": 30},
    echo=False,
)

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


def init_db():
    """Initialize database: run Alembic migrations and enable WAL."""
    import logging

    from alembic.config import Config
    from alembic.migration import MigrationContext
    from alembic.script import ScriptDirectory

    from alembic import command

    logger = logging.getLogger(__name__)

    # Enable WAL mode for better concurrent access
    with engine.begin() as conn:
        conn.execute(text("PRAGMA journal_mode=WAL"))
        conn.execute(text("PRAGMA busy_timeout=30000"))

    # Run Alembic migrations
    alembic_cfg = Config(_ALEMBIC_INI)
    alembic_cfg.set_main_option("sqlalchemy.url", settings.database_url)

    script = ScriptDirectory.from_config(alembic_cfg)
    head_rev = script.get_current_head()

    with engine.connect() as conn:
        context = MigrationContext.configure(conn)
        current_rev = context.get_current_revision()

    # Recovery for a rewritten migration chain: if alembic_version points
    # at a revision that no longer exists in the script directory (e.g.
    # after a squash), clear it so the stamp-existing-DB branch below
    # picks up. TODO: revert with the next commit once prod has booted.
    if current_rev is not None:
        try:
            script.get_revision(current_rev)
        except Exception:
            logger.warning(
                "alembic_version points at unknown revision %s; clearing", current_rev
            )
            with engine.begin() as conn:
                conn.execute(text("DELETE FROM alembic_version"))
            current_rev = None

    if current_rev is None:
        from sqlalchemy import inspect

        inspector = inspect(engine)
        if inspector.has_table("projects"):
            initial_rev = script.get_base()
            assert initial_rev is not None, "No base revision found in Alembic scripts"
            logger.info("Stamping existing database at initial revision %s", initial_rev)
            command.stamp(alembic_cfg, initial_rev)
            logger.info("Upgrading to head to apply new migrations")
            command.upgrade(alembic_cfg, "head")
        else:
            logger.info("Running initial Alembic migrations")
            command.upgrade(alembic_cfg, "head")
    elif current_rev != head_rev:
        logger.info(f"Upgrading database from {current_rev} to {head_rev}")
        command.upgrade(alembic_cfg, "head")

    # Safety net: create any tables that Alembic missed.
    import backend.models  # noqa: F401

    Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
