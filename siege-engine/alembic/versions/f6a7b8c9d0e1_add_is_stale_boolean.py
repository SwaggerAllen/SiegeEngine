"""add is_stale boolean to artifacts, artifact_stale to snapshots

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-03-26 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'f6a7b8c9d0e1'
down_revision: Union[str, Sequence[str], None] = 'e5f6a7b8c9d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add is_stale boolean column to artifacts
    op.add_column('artifacts', sa.Column('is_stale', sa.Boolean(), server_default='0', nullable=False))

    # Add artifact_stale JSON column to pipeline_snapshots
    op.add_column('pipeline_snapshots', sa.Column('artifact_stale', sa.JSON(), server_default='{}', nullable=False))

    # Migrate existing STALE status to is_stale=True, restore status to approved
    op.execute("UPDATE artifacts SET is_stale = 1, status = 'approved' WHERE status = 'stale'")


def downgrade() -> None:
    # Restore STALE status from is_stale boolean
    op.execute("UPDATE artifacts SET status = 'stale' WHERE is_stale = 1")

    op.drop_column('pipeline_snapshots', 'artifact_stale')
    op.drop_column('artifacts', 'is_stale')
