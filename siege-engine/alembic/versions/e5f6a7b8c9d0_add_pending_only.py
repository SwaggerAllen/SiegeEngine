"""add pending_only to pipeline_runs

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-04-08 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'e5f6a7b8c9d0'
down_revision: Union[str, Sequence[str], None] = 'd4e5f6a7b8c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add pending_only to pipeline_runs."""
    with op.batch_alter_table('pipeline_runs', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('pending_only', sa.Boolean(), nullable=False, server_default='0')
        )


def downgrade() -> None:
    """Remove pending_only from pipeline_runs."""
    with op.batch_alter_table('pipeline_runs', schema=None) as batch_op:
        batch_op.drop_column('pending_only')
