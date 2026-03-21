"""add event sourcing tables

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-03-20 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create pipeline_events and pipeline_snapshots tables."""
    op.create_table(
        'pipeline_events',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('project_id', sa.String(), nullable=False),
        sa.Column('run_id', sa.String(), nullable=True),
        sa.Column('sequence', sa.Integer(), nullable=False),
        sa.Column('event_type', sa.String(50), nullable=False),
        sa.Column('payload', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('project_id', 'sequence', name='uq_event_project_sequence'),
    )
    op.create_index('ix_events_project_seq', 'pipeline_events', ['project_id', 'sequence'])
    op.create_index('ix_pipeline_events_project_id', 'pipeline_events', ['project_id'])
    op.create_index('ix_pipeline_events_run_id', 'pipeline_events', ['run_id'])

    op.create_table(
        'pipeline_snapshots',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('project_id', sa.String(), nullable=False),
        sa.Column('last_sequence', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('run_status', sa.JSON(), nullable=False),
        sa.Column('stage_statuses', sa.JSON(), nullable=False),
        sa.Column('artifact_statuses', sa.JSON(), nullable=False),
        sa.Column('is_running', sa.Boolean(), nullable=True, server_default='0'),
        sa.Column('is_paused', sa.Boolean(), nullable=True, server_default='0'),
        sa.Column('paused_stage', sa.String(), nullable=True),
        sa.Column('current_run_id', sa.String(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('project_id'),
    )


def downgrade() -> None:
    """Drop event sourcing tables."""
    op.drop_table('pipeline_snapshots')
    op.drop_index('ix_pipeline_events_run_id', table_name='pipeline_events')
    op.drop_index('ix_pipeline_events_project_id', table_name='pipeline_events')
    op.drop_index('ix_events_project_seq', table_name='pipeline_events')
    op.drop_table('pipeline_events')
