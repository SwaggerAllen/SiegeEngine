"""add generation_completed_at to stage_executions

Revision ID: j0e1f2g3h4i5
Revises: i9d0e1f2g3h4
Create Date: 2026-04-08 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'j0e1f2g3h4i5'
down_revision: Union[str, Sequence[str], None] = 'i9d0e1f2g3h4'
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
