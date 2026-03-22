"""add component_definition unique index

Revision ID: a1b2c3d4e5f6
Revises: 7ecd24d05694
Create Date: 2026-03-19 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '7ecd24d05694'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add unique index on (project_id, key, COALESCE(parent_key, ''))."""
    # Remove any duplicate rows before creating the unique index.
    # Keep the most recently created row per (project_id, key, parent_key).
    op.execute("""
        DELETE FROM component_definitions
        WHERE id NOT IN (
            SELECT id FROM (
                SELECT id,
                       ROW_NUMBER() OVER (
                           PARTITION BY project_id, key, COALESCE(parent_key, '')
                           ORDER BY created_at DESC
                       ) AS rn
                FROM component_definitions
            ) sub
            WHERE rn = 1
        )
    """)

    op.execute("""
        CREATE UNIQUE INDEX uq_comp_def_project_key_parent
        ON component_definitions (project_id, key, COALESCE(parent_key, ''))
    """)


def downgrade() -> None:
    """Remove unique index."""
    op.drop_index("uq_comp_def_project_key_parent", table_name="component_definitions")
