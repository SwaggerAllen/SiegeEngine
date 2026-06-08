"""v3 references in git — add body_sha + body_path to nodes

Revision ID: c2_refs_git
Revises: c1_input_docs_git
Create Date: 2026-06-03

Adds nullable ``body_sha`` and ``body_path`` columns to the
``nodes`` table so reference (``ref_*``) nodes — the first node
tier migrating to "artifacts in git, state in Postgres" — can
record where their body content lives in the project repo
(path + sha) instead of storing it inline in ``content``.

Legacy ref nodes continue to store content inline in ``content``;
readers check ``body_sha`` first and fetch from git via
``siege.git_view`` when set. New refs created via the v3
``POST /api/projects/<id>/references`` endpoint set ``body_sha``
+ ``body_path`` and write a sentinel into ``content`` (it stays
NOT NULL for back-compat).

The same columns are reusable by vocab + any other tier we
later move to git in subsequent migrations — the column shape
is generic.

Forward-only. Downgrade raises NotImplementedError.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c2_refs_git"
down_revision: Union[str, Sequence[str], None] = "c1_input_docs_git"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("nodes") as batch:
        batch.add_column(sa.Column("body_sha", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("body_path", sa.String(length=1024), nullable=True))


def downgrade() -> None:
    raise NotImplementedError("v3 migrations are forward-only.")
