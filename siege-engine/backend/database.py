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
    """
    from backend.pipeline.defaults import DEFAULT_STAGES

    new_order = {s["stage_key"]: s["order_index"] for s in DEFAULT_STAGES}
    new_inputs = {s["stage_key"]: s["input_stage_keys"] for s in DEFAULT_STAGES}

    with engine.begin() as conn:
        # Check if stage_definitions table exists
        inspector = inspect(engine)
        if not inspector.has_table("stage_definitions"):
            return

        rows = conn.execute(text(
            "SELECT id, stage_key, order_index, input_stage_keys "
            "FROM stage_definitions WHERE stage_key IN ('component_plans', 'extract_sub_components')"
        )).fetchall()

        for row in rows:
            sid, skey, current_order, _ = row
            target_order = new_order.get(skey)
            target_inputs = new_inputs.get(skey)
            if target_order is not None and current_order != target_order:
                import json
                conn.execute(text(
                    "UPDATE stage_definitions SET order_index = :order_index, "
                    "input_stage_keys = :input_keys WHERE id = :id"
                ), {
                    "order_index": target_order,
                    "input_keys": json.dumps(target_inputs),
                    "id": sid,
                })


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
