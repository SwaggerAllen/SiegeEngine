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

    if current_rev is None:
        # Check if tables already exist (pre-Alembic database)
        from sqlalchemy import inspect

        inspector = inspect(engine)
        if inspector.has_table("projects"):
            # Existing database — stamp at the initial migration (which matches
            # the pre-Alembic schema), then upgrade to apply new migrations
            initial_rev = script.get_base()
            assert initial_rev is not None, "No base revision found in Alembic scripts"
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

    # Safety net: create any tables that Alembic missed (e.g. if a previous
    # deploy stamped head without actually running migrations).
    import backend.models  # noqa: F401

    Base.metadata.create_all(bind=engine)

    # Safety net: add columns that create_all can't add to existing tables.
    _add_missing_columns()

    _migrate_stage_order()


def _add_missing_columns():
    """Add new columns to existing tables that create_all won't handle."""
    from sqlalchemy import inspect

    inspector = inspect(engine)

    _ensure_column(inspector, "pipeline_runs", "propagation_run", "BOOLEAN DEFAULT 0")
    _ensure_column(inspector, "pipeline_runs", "start_stage_key", "VARCHAR(100)")
    _ensure_column(inspector, "pipeline_runs", "start_component_key", "VARCHAR(255)")
    _ensure_column(inspector, "pipeline_runs", "regen_generated_only", "BOOLEAN DEFAULT 0")
    _ensure_column(inspector, "artifact_comments", "updated_at", "DATETIME")

    # is_stale boolean on artifacts (replaces STALE enum value)
    _ensure_column(inspector, "artifacts", "is_stale", "BOOLEAN DEFAULT 0")

    # Track the git SHA before the latest generation for accurate diffs
    _ensure_column(inspector, "artifacts", "prev_git_commit_sha", "VARCHAR(40)")

    # Pre-computed summary for context budget management
    _ensure_column(inspector, "artifacts", "summary", "TEXT")

    # Extended snapshot columns (added in d4e5f6a7b8c9 migration)
    for col in (
        "artifact_versions",
        "stage_errors",
        "comment_counts",
        "stage_triggers",
        "artifact_meta",
        "artifact_git_shas",
        "cascade_parents",
        "execution_map",
        "artifact_stale",
    ):
        _ensure_column(inspector, "pipeline_snapshots", col, "JSON NOT NULL DEFAULT '{}'")

    # Migrate existing STALE status to is_stale boolean
    if inspector.has_table("artifacts"):
        columns = [c["name"] for c in inspector.get_columns("artifacts")]
        if "is_stale" in columns:
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "UPDATE artifacts SET is_stale = 1, status = 'approved' "
                        "WHERE status = 'stale'"
                    )
                )


def _ensure_column(inspector, table: str, column: str, col_def: str):
    """Add a column to a table if it doesn't exist."""
    if not inspector.has_table(table):
        return
    columns = [c["name"] for c in inspector.get_columns(table)]
    if column not in columns:
        with engine.begin() as conn:
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {col_def}"))


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

        # 1b. Add new stages that don't exist yet for each pipeline config
        config_rows = conn.execute(
            text(
                "SELECT pipeline_config_id, stage_key FROM stage_definitions"
            )
        ).fetchall()
        configs_stages: dict[str, set[str]] = {}
        for config_id, skey in config_rows:
            configs_stages.setdefault(config_id, set()).add(skey)

        all_config_ids = conn.execute(
            text("SELECT id FROM pipeline_configs")
        ).fetchall()

        import uuid as _uuid

        for (config_id,) in all_config_ids:
            existing = configs_stages.get(config_id, set())
            for stage_data in DEFAULT_STAGES:
                skey = stage_data["stage_key"]
                if skey not in existing:
                    conn.execute(
                        text(
                            "INSERT INTO stage_definitions "
                            "(id, pipeline_config_id, stage_key, display_name, "
                            "order_index, output_artifact_type, input_stage_keys, "
                            "fan_out_strategy, prompt_template_key, "
                            "model_override, ai_review_enabled, human_review_enabled) "
                            "VALUES (:id, :config_id, :stage_key, :display_name, "
                            ":order_index, :output_artifact_type, :input_stage_keys, "
                            ":fan_out_strategy, :prompt_template_key, "
                            ":model_override, :ai_review_enabled, :human_review_enabled)"
                        ),
                        {
                            "id": str(_uuid.uuid4()),
                            "config_id": config_id,
                            "stage_key": skey,
                            "display_name": stage_data["display_name"],
                            "order_index": stage_data["order_index"],
                            "output_artifact_type": stage_data["output_artifact_type"],
                            "input_stage_keys": json.dumps(
                                stage_data["input_stage_keys"]
                            ),
                            "fan_out_strategy": stage_data["fan_out_strategy"],
                            "prompt_template_key": stage_data.get(
                                "prompt_template_key"
                            ),
                            "model_override": stage_data.get("model_override"),
                            "ai_review_enabled": stage_data.get(
                                "ai_review_enabled", True
                            ),
                            "human_review_enabled": stage_data.get(
                                "human_review_enabled", True
                            ),
                        },
                    )

        # 2. Clean up artifacts/executions for removed stages
        for removed_type in (
            "high_level_plan",
            "component_requirements",
            "sub_component_requirements",
        ):
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
