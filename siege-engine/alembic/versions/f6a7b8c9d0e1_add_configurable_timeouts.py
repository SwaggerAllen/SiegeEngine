"""add configurable timeouts to pipeline_configs

Revision ID: l2g3h4i5j6k7
Revises: k1f2g3h4i5j6
Create Date: 2026-04-08 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'l2g3h4i5j6k7'
down_revision: Union[str, Sequence[str], None] = 'k1f2g3h4i5j6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add timeout override columns to pipeline_configs."""
    with op.batch_alter_table('pipeline_configs', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('cli_timeout_document', sa.Integer(), nullable=True)
        )
        batch_op.add_column(
            sa.Column('cli_timeout_code', sa.Integer(), nullable=True)
        )
        batch_op.add_column(
            sa.Column('cli_timeout_summary', sa.Integer(), nullable=True)
        )
        batch_op.add_column(
            sa.Column('cli_max_budget_code', sa.Float(), nullable=True)
        )


def downgrade() -> None:
    """Remove timeout override columns from pipeline_configs."""
    with op.batch_alter_table('pipeline_configs', schema=None) as batch_op:
        batch_op.drop_column('cli_max_budget_code')
        batch_op.drop_column('cli_timeout_summary')
        batch_op.drop_column('cli_timeout_code')
        batch_op.drop_column('cli_timeout_document')
