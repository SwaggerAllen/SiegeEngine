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


def upgrade() -> None:
    """Add extended snapshot columns to pipeline_snapshots."""
    op.add_column('pipeline_snapshots', sa.Column('artifact_versions', sa.JSON(), nullable=False, server_default='{}'))
    op.add_column('pipeline_snapshots', sa.Column('stage_errors', sa.JSON(), nullable=False, server_default='{}'))
    op.add_column('pipeline_snapshots', sa.Column('comment_counts', sa.JSON(), nullable=False, server_default='{}'))
    op.add_column('pipeline_snapshots', sa.Column('stage_triggers', sa.JSON(), nullable=False, server_default='{}'))
    op.add_column('pipeline_snapshots', sa.Column('artifact_meta', sa.JSON(), nullable=False, server_default='{}'))
    op.add_column('pipeline_snapshots', sa.Column('artifact_git_shas', sa.JSON(), nullable=False, server_default='{}'))
    op.add_column('pipeline_snapshots', sa.Column('cascade_parents', sa.JSON(), nullable=False, server_default='{}'))


def downgrade() -> None:
    """Remove extended snapshot columns."""
    op.drop_column('pipeline_snapshots', 'cascade_parents')
    op.drop_column('pipeline_snapshots', 'artifact_git_shas')
    op.drop_column('pipeline_snapshots', 'artifact_meta')
    op.drop_column('pipeline_snapshots', 'stage_triggers')
    op.drop_column('pipeline_snapshots', 'comment_counts')
    op.drop_column('pipeline_snapshots', 'stage_errors')
    op.drop_column('pipeline_snapshots', 'artifact_versions')
