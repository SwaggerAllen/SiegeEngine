"""v2 deferred features — add is_deferred column to nodes

Revision ID: b15_is_deferred
Revises: b14_staleness_ledger
Create Date: 2026-04-20

Phase-11 followup B7. Adds an ``is_deferred`` boolean column
to the ``nodes`` table so feature nodes can be marked as
"design-toward but skip for now" — visible in the expansion
and DAG, but excluded from the requirements and sysarch
generation passes so the downstream design pipeline doesn't
commit to structure for deferred capabilities.

Mirrors the ``is_implicit`` column added by ``b7_feature_metadata``:
on the ``nodes`` table rather than a feat_*-specific side table
because the schema pattern is established; non-feature tiers
keep the default (false) and ignore it.

Forward-only. Downgrade raises NotImplementedError.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b15_is_deferred"
down_revision: Union[str, Sequence[str], None] = "b14_staleness_ledger"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("nodes") as batch:
        batch.add_column(
            sa.Column(
                "is_deferred",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )


def downgrade() -> None:
    raise NotImplementedError("v2 migrations are forward-only.")
