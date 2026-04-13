"""v2 project settings — add settings JSON column to projects

Revision ID: b8_project_settings
Revises: b7_feature_metadata
Create Date: 2026-04-13

Adds a nullable ``settings`` JSON column to the ``projects`` table
so per-project preferences can be stored and updated without
schema churn each time we add one. The first setting we use the
column for is ``generation_timeout_seconds`` — the CLI timeout
budget for feature-expansion (and future) generation jobs —
but the shape is deliberately open so later phases can land
additional keys (retry budgets, model overrides, etc.) without
another migration.

Stored as a JSON blob rather than a dedicated column-per-setting
because (a) settings are rare to access (once per generation),
(b) they're a policy boundary rather than a query boundary, and
(c) keeping them in one blob avoids a sprawl of nullable columns
as we learn what settings we actually need.

``None`` means "no overrides" — handlers fall back to the
hardcoded default. Never written as ``{}``; we treat that and
``None`` as equivalent for reads.

See ``docs/architecture/v2-rearchitecture.md`` §Project settings
(to be written alongside Phase 2.5).

Forward-only. Downgrade raises NotImplementedError.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b8_project_settings"
down_revision: Union[str, Sequence[str], None] = "b7_feature_metadata"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("projects") as batch:
        batch.add_column(sa.Column("settings", sa.JSON(), nullable=True))


def downgrade() -> None:
    raise NotImplementedError("v2 migrations are forward-only.")
