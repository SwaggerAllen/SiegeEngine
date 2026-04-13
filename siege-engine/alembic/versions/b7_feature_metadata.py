"""v2 feature metadata — add group_label + is_implicit columns to nodes

Revision ID: b7_feature_metadata
Revises: b6_subreqs_tier
Create Date: 2026-04-12

Adds two optional columns to the ``nodes`` table so feature nodes
minted from an approved expansion can carry:

- ``group_label`` — the optional feature group the feature lives
  in (e.g. "User Management"). Set when the ``<feature>`` is
  inside a ``<group>`` block in the expansion output; null
  otherwise. Grouping is a feat_* concern — other tiers leave
  this column null and the frontend ignores it for them.
- ``is_implicit`` — whether the feature was marked with an
  ``<implicit/>`` tag in the expansion, signalling that the LLM
  inferred it as obviously-necessary rather than finding it in
  the user's input doc. Defaults to false for backward compat
  and for all non-feature tiers.

Both columns are on the ``nodes`` table rather than a feat_*-
specific side table because (a) they're cheap and (b) future
tiers may find their own uses. Non-feat_* rows keep the default
values and ignore the columns.

See ``docs/architecture/v2-rearchitecture.md`` §Feature expansion
(implicit features + feature groups) and
``docs/architecture/v2-roadmap.md`` Phase 2.

Forward-only. Downgrade raises NotImplementedError.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b7_feature_metadata"
down_revision: Union[str, Sequence[str], None] = "b6_subreqs_tier"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("nodes") as batch:
        batch.add_column(
            sa.Column("group_label", sa.String(length=255), nullable=True)
        )
        batch.add_column(
            sa.Column(
                "is_implicit",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )


def downgrade() -> None:
    raise NotImplementedError("v2 migrations are forward-only.")
