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
    """Initialize database: run Alembic migrations, enable WAL, sync stages."""
    import logging

    from alembic import command
    from alembic.config import Config
    from alembic.migration import MigrationContext
    from alembic.script import ScriptDirectory

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

    if current_rev is None:
        # Check if tables already exist (pre-Alembic database)
        from sqlalchemy import inspect

        inspector = inspect(engine)
        if inspector.has_table("projects"):
            # Existing database — stamp at the initial migration (which matches
            # the pre-Alembic schema), then upgrade to apply new migrations
            initial_rev = script.get_base()
            logger.info("Stamping existing database at initial revision %s", initial_rev)
            command.stamp(alembic_cfg, initial_rev)
            logger.info("Upgrading to head to apply new migrations")
            command.upgrade(alembic_cfg, "head")
        else:
            # Fresh database — run all migrations
            logger.info("Running initial Alembic migrations")
            command.upgrade(alembic_cfg, "head")
    elif current_rev != head_rev:
        logger.info(f"Upgrading database from {current_rev} to {head_rev}")
        command.upgrade(alembic_cfg, "head")

    _migrate_stage_order()


def _migrate_stage_order():
    """Sync stage definitions with DEFAULT_STAGES.

    - Removes the high_level_plan stage (and its artifacts/executions)
    - Reindexes all stages to match DEFAULT_STAGES order
    - Updates input_stage_keys for stages whose inputs changed
    - Cleans up component_plan artifacts for non-leaf components
    """
    import json

    from sqlalchemy import inspect

    from backend.pipeline.defaults import DEFAULT_STAGES

    new_order = {s["stage_key"]: s["order_index"] for s in DEFAULT_STAGES}
    new_inputs = {s["stage_key"]: json.dumps(s["input_stage_keys"]) for s in DEFAULT_STAGES}
    valid_keys = set(new_order.keys())

    with engine.begin() as conn:
        inspector = inspect(engine)
        if not inspector.has_table("stage_definitions"):
            return

        # 1. Sync every stage definition: update order + inputs, delete removed
        rows = conn.execute(
            text("SELECT id, stage_key, order_index, input_stage_keys FROM stage_definitions")
        ).fetchall()

        for sid, skey, current_order, current_inputs in rows:
            if skey not in valid_keys:
                # Stage was removed (e.g. high_level_plan) — delete it
                conn.execute(text("DELETE FROM stage_definitions WHERE id = :id"), {"id": sid})
                continue

            target_order = new_order[skey]
            target_inputs = new_inputs[skey]
            if current_order != target_order or current_inputs != target_inputs:
                conn.execute(
                    text(
                        "UPDATE stage_definitions SET order_index = :order_index, "
                        "input_stage_keys = :input_keys WHERE id = :id"
                    ),
                    {"order_index": target_order, "input_keys": target_inputs, "id": sid},
                )

        # 2. Clean up artifacts/executions for removed stages
        for removed_type in ("high_level_plan", "component_requirements", "sub_component_requirements"):
            _cleanup_artifacts_for_type(conn, inspector, removed_type)
            conn.execute(
                text("DELETE FROM stage_executions WHERE stage_key = :sk"),
                {"sk": removed_type},
            )

        # 3. Clean up component_plan artifacts for non-leaf components
        if not inspector.has_table("component_definitions"):
            return

        parent_keys = conn.execute(
            text(
                "SELECT DISTINCT parent_key FROM component_definitions WHERE parent_key IS NOT NULL"
            )
        ).fetchall()
        non_leaf_keys = [r[0] for r in parent_keys]
        if not non_leaf_keys:
            return

        placeholders = ", ".join(f":k{i}" for i in range(len(non_leaf_keys)))
        params = {f"k{i}": k for i, k in enumerate(non_leaf_keys)}

        orphan_ids = conn.execute(
            text(
                f"SELECT id FROM artifacts "
                f"WHERE artifact_type = 'component_plan' "
                f"AND component_key IN ({placeholders})"
            ),
            params,
        ).fetchall()
        _delete_artifact_ids(conn, inspector, [r[0] for r in orphan_ids])

        conn.execute(
            text(
                f"DELETE FROM stage_executions "
                f"WHERE stage_key = 'component_plans' "
                f"AND component_key IN ({placeholders})"
            ),
            params,
        )


def _cleanup_artifacts_for_type(conn, inspector, artifact_type: str):
    """Delete all artifacts of a given type and their related records."""
    art_ids = conn.execute(
        text("SELECT id FROM artifacts WHERE artifact_type = :atype"), {"atype": artifact_type}
    ).fetchall()
    _delete_artifact_ids(conn, inspector, [r[0] for r in art_ids])


def _delete_artifact_ids(conn, inspector, art_ids: list[str]):
    """Delete artifacts by ID along with their dependency edges and comments."""
    if not art_ids:
        return
    ph = ", ".join(f":a{i}" for i in range(len(art_ids)))
    params = {f"a{i}": aid for i, aid in enumerate(art_ids)}

    conn.execute(
        text(
            f"DELETE FROM artifact_dependencies "
            f"WHERE upstream_artifact_id IN ({ph}) "
            f"OR downstream_artifact_id IN ({ph})"
        ),
        params,
    )

    if inspector.has_table("artifact_comments"):
        conn.execute(text(f"DELETE FROM artifact_comments WHERE artifact_id IN ({ph})"), params)

    conn.execute(text(f"DELETE FROM artifacts WHERE id IN ({ph})"), params)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
