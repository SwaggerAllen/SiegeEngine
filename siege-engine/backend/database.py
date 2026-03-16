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
    _migrate_stage_order()


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

    # InviteLink.role
    if inspector.has_table("invite_links"):
        columns = [c["name"] for c in inspector.get_columns("invite_links")]
        if "role" not in columns:
            with engine.begin() as conn:
                conn.execute(text(
                    "ALTER TABLE invite_links ADD COLUMN role VARCHAR(20) DEFAULT 'member'"
                ))

    # Project.auto_push_enabled
    if inspector.has_table("projects"):
        columns = [c["name"] for c in inspector.get_columns("projects")]
        if "auto_push_enabled" not in columns:
            with engine.begin() as conn:
                conn.execute(text(
                    "ALTER TABLE projects ADD COLUMN auto_push_enabled BOOLEAN DEFAULT 0"
                ))
        if "blocking_pr_url" not in columns:
            with engine.begin() as conn:
                conn.execute(text(
                    "ALTER TABLE projects ADD COLUMN blocking_pr_url VARCHAR(500)"
                ))
        if "blocking_pr_number" not in columns:
            with engine.begin() as conn:
                conn.execute(text(
                    "ALTER TABLE projects ADD COLUMN blocking_pr_number INTEGER"
                ))


def _migrate_stage_order():
    """Reorder stages: move component_plans after extract_sub_components.

    Old order: ..., component_plans(6), extract_sub_components(7), ...
    New order: ..., extract_sub_components(6), component_plans(7), ...

    Also update extract_sub_components input_stage_keys to no longer
    require component_plans (it now takes component_architectures +
    component_requirements).

    Finally, clean up component_plan artifacts and component_plans
    executions for non-leaf components (those that have sub-components),
    since component_plans now only runs for leaf components.
    """
    import json

    from backend.pipeline.defaults import DEFAULT_STAGES

    new_order = {s["stage_key"]: s["order_index"] for s in DEFAULT_STAGES}
    new_inputs = {s["stage_key"]: s["input_stage_keys"] for s in DEFAULT_STAGES}

    with engine.begin() as conn:
        inspector = inspect(engine)
        if not inspector.has_table("stage_definitions"):
            return

        # 1. Update stage order_index and input_stage_keys
        rows = conn.execute(text(
            "SELECT id, stage_key, order_index, input_stage_keys "
            "FROM stage_definitions WHERE stage_key IN ('component_plans', 'extract_sub_components')"
        )).fetchall()

        for row in rows:
            sid, skey, current_order, _ = row
            target_order = new_order.get(skey)
            target_inputs = new_inputs.get(skey)
            if target_order is not None and current_order != target_order:
                conn.execute(text(
                    "UPDATE stage_definitions SET order_index = :order_index, "
                    "input_stage_keys = :input_keys WHERE id = :id"
                ), {
                    "order_index": target_order,
                    "input_keys": json.dumps(target_inputs),
                    "id": sid,
                })

        # 2. Clean up component_plan artifacts for non-leaf components
        #    (components that have sub-components under them).
        if not inspector.has_table("component_definitions"):
            return

        parent_keys = conn.execute(text(
            "SELECT DISTINCT parent_key FROM component_definitions "
            "WHERE parent_key IS NOT NULL"
        )).fetchall()
        non_leaf_keys = [r[0] for r in parent_keys]
        if not non_leaf_keys:
            return

        # Find component_plan artifacts for non-leaf components
        placeholders = ", ".join(f":k{i}" for i in range(len(non_leaf_keys)))
        params = {f"k{i}": k for i, k in enumerate(non_leaf_keys)}

        orphan_ids = conn.execute(text(
            f"SELECT id FROM artifacts "
            f"WHERE artifact_type = 'component_plan' "
            f"AND component_key IN ({placeholders})"
        ), params).fetchall()
        orphan_art_ids = [r[0] for r in orphan_ids]

        if orphan_art_ids:
            art_ph = ", ".join(f":a{i}" for i in range(len(orphan_art_ids)))
            art_params = {f"a{i}": aid for i, aid in enumerate(orphan_art_ids)}

            # Delete dependency edges
            conn.execute(text(
                f"DELETE FROM artifact_dependencies "
                f"WHERE upstream_artifact_id IN ({art_ph}) "
                f"OR downstream_artifact_id IN ({art_ph})"
            ), art_params)

            # Delete comments
            if inspector.has_table("artifact_comments"):
                conn.execute(text(
                    f"DELETE FROM artifact_comments "
                    f"WHERE artifact_id IN ({art_ph})"
                ), art_params)

            # Delete the artifacts
            conn.execute(text(
                f"DELETE FROM artifacts WHERE id IN ({art_ph})"
            ), art_params)

        # Delete component_plans executions for non-leaf components
        conn.execute(text(
            f"DELETE FROM stage_executions "
            f"WHERE stage_key = 'component_plans' "
            f"AND component_key IN ({placeholders})"
        ), params)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
