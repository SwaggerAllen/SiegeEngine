"""add generation_completed_at to stage_executions

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-04-08 00:00:00.000000

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
    """Add generation_completed_at to stage_executions."""
    with op.batch_alter_table('stage_executions', schema=None) as batch_op:
        batch_op.add_column(sa.Column('generation_completed_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    """Remove generation_completed_at from stage_executions."""
    with op.batch_alter_table('stage_executions', schema=None) as batch_op:
        batch_op.drop_column('generation_completed_at')
