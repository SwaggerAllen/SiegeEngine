"""add pipeline_run scoping columns

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-03-21 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'c3d4e5f6a7b8'
down_revision: Union[str, Sequence[str], None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add start_stage_key, start_component_key, regen_generated_only to pipeline_runs."""
    with op.batch_alter_table('pipeline_runs', schema=None) as batch_op:
        batch_op.add_column(sa.Column('start_stage_key', sa.String(100), nullable=True))
        batch_op.add_column(sa.Column('start_component_key', sa.String(255), nullable=True))
        batch_op.add_column(sa.Column('regen_generated_only', sa.Boolean(), nullable=False, server_default='0'))

    # Migrate old stop_point enum values to new ones.
    op.execute("UPDATE pipeline_runs SET stop_point = 'END_OF_PHASE' WHERE stop_point = 'AFTER_ALL'")


def downgrade() -> None:
    """Reverse scoping column additions."""
    with op.batch_alter_table('pipeline_runs', schema=None) as batch_op:
        batch_op.drop_column('regen_generated_only')
        batch_op.drop_column('start_component_key')
        batch_op.drop_column('start_stage_key')

    op.execute("UPDATE pipeline_runs SET stop_point = 'AFTER_ALL' WHERE stop_point = 'END_OF_PHASE'")
