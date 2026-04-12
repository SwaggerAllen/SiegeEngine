"""drop v1 leftover columns

Revision ID: a1_drop_v1_leftover_cols
Revises: v2_initial_schema
Create Date: 2026-04-12

Drops three columns that survived the v1 → v2 gut but have no v2 consumers:

- projects.blocking_pr_url / projects.blocking_pr_number: v1 pipeline
  paused on an open PR; v2 has no such concept.
- input_documents.inject_into_stages: v1 injected docs into specific
  pipeline stages; v2 has no stage registry.

Uses batch_alter_table for SQLite compatibility (SQLite has no native
ALTER TABLE DROP COLUMN before 3.35 and alembic's batch mode is the
portable path).
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1_drop_v1_leftover_cols"
down_revision: Union[str, Sequence[str], None] = "v2_initial_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("projects") as batch:
        batch.drop_column("blocking_pr_url")
        batch.drop_column("blocking_pr_number")

    with op.batch_alter_table("input_documents") as batch:
        batch.drop_column("inject_into_stages")


def downgrade() -> None:
    raise NotImplementedError(
        "v2 migrations are forward-only."
    )
