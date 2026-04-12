"""gut v1: drop artifact/pipeline/stage/component/chat tables

Revision ID: m3h4i5j6k7l8
Revises: l2g3h4i5j6k7
Create Date: 2026-04-12

This migration is part of the v1 → v2 gut phase. It drops every v1-only
table so the schema matches the trimmed ORM models. Surviving tables:
users, invite_links, github_credentials, projects, jobs, input_documents.

Forward-only. The v1 schema is not reconstructable from v2 code, so the
downgrade raises NotImplementedError. v2's build phase will issue its
own forward migrations for the new model.
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "m3h4i5j6k7l8"
down_revision: Union[str, Sequence[str], None] = "l2g3h4i5j6k7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Drop order: children before parents, so FK references resolve cleanly
# on databases that enforce them.
_V1_TABLES_IN_DROP_ORDER: tuple[str, ...] = (
    # Artifact graph — comments + deps reference artifacts
    "artifact_comments",
    "artifact_dependencies",
    # Stage execution references artifacts, pipeline_runs, stage_definitions
    "stage_executions",
    # Prompt configs reference stage_definitions
    "prompt_configs",
    # Stage definitions reference pipeline_configs
    "stage_definitions",
    # Now safe to drop the artifacts themselves
    "artifacts",
    # Component definitions reference projects (and themselves via parent)
    "component_definitions",
    # Event-sourcing tables reference projects
    "pipeline_events",
    "pipeline_snapshots",
    # Pipeline runs / configs reference projects
    "pipeline_runs",
    "pipeline_configs",
    # Chat module — references projects only
    "chat_messages",
)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = __import__("sqlalchemy").inspect(bind)
    existing = set(inspector.get_table_names())
    for table in _V1_TABLES_IN_DROP_ORDER:
        if table in existing:
            op.drop_table(table)


def downgrade() -> None:
    raise NotImplementedError(
        "v1 gut is forward-only; reconstructing the v1 schema is not supported. "
        "Restore from a pre-gut backup if you need v1 data."
    )
