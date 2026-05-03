"""Add ``cohorts`` + ``cohort_sampler_configs`` tables.

Revision ID: b23_cohorts
Revises: b22_batches_table
Create Date: 2026-05-03

Phase 14 follow-up — saved cohorts of comp IDs to drive iterative
generation campaigns at the next tier down. ``Cohort`` rows are
the user's "canonical sample" plus rotating exploration-sample
selections; ``CohortSamplerConfig`` holds per-tier axis weights
so the stratified sampler can be tuned without a deploy.

Forward-only; downgrade raises NotImplementedError.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b23_cohorts"
down_revision: Union[str, Sequence[str], None] = "b22_batches_table"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "cohorts",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(),
            sa.ForeignKey(
                "projects.id", name="fk_cohorts_project_id", ondelete="CASCADE"
            ),
            nullable=False,
            index=True,
        ),
        sa.Column("tier", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False, server_default="canonical"),
        sa.Column("comp_ids", sa.JSON(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("archived", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
    )

    op.create_table(
        "cohort_sampler_configs",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(),
            sa.ForeignKey(
                "projects.id",
                name="fk_cohort_sampler_configs_project_id",
                ondelete="CASCADE",
            ),
            nullable=False,
            index=True,
        ),
        sa.Column("tier", sa.String(length=32), nullable=False),
        sa.Column("axes", sa.JSON(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
        sa.UniqueConstraint(
            "project_id", "tier", name="uq_cohort_sampler_configs_project_tier"
        ),
    )


def downgrade() -> None:
    raise NotImplementedError("v2 migrations are forward-only.")
