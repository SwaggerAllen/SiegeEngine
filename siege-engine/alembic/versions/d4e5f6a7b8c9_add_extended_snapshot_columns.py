"""add extended snapshot columns

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-03-22 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, Sequence[str], None] = 'c3d4e5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = 'pipeline_snapshots'
_COLS = [
    'artifact_versions',
    'stage_errors',
    'comment_counts',
    'stage_triggers',
    'artifact_meta',
    'artifact_git_shas',
    'cascade_parents',
    'execution_map',
]


def upgrade() -> None:
    """Add extended snapshot columns to pipeline_snapshots."""
    for col in _COLS:
        op.add_column(
            _TABLE,
            sa.Column(
                col, sa.JSON(),
                nullable=False, server_default='{}',
            ),
        )


def downgrade() -> None:
    """Remove extended snapshot columns."""
    for col in reversed(_COLS):
        op.drop_column(_TABLE, col)
