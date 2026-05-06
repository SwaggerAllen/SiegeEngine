"""Add ``experimental_comp_ids`` column to ``cohorts``.

Revision ID: b24_cohort_experimental_comp_ids
Revises: b23_cohorts
Create Date: 2026-05-05

Cohort campaigns now manage two slots: ``comp_ids`` (canonical,
set from the structure-summary) and ``experimental_comp_ids``
(supplementary, set/replaced by each fresh-mode regenerate cycle
and read by the subsequent review cycles until the next fresh
swaps it). Backfills empty list for existing rows.

Forward-only; downgrade raises.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b24_cohort_experimental_comp_ids"
down_revision: Union[str, Sequence[str], None] = "b23_cohorts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("cohorts") as batch:
        batch.add_column(
            sa.Column(
                "experimental_comp_ids",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'[]'"),
            )
        )


def downgrade() -> None:
    raise NotImplementedError("v2 migrations are forward-only.")
