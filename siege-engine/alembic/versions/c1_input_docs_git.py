"""v3 input documents in git — add body_sha + body_path columns

Revision ID: c1_input_docs_git
Revises: b9_decomposition_edge
Create Date: 2026-06-03

Adds nullable ``body_sha`` and ``body_path`` columns to the
``input_documents`` table so input documents migrated to the v3
"artifacts in git, state in Postgres" pattern can record where
their body content lives in the project repo (path + sha) instead
of storing it inline in ``content``.

Legacy input documents continue to store body content in the
``content`` column; readers check ``body_sha`` first and fetch
from git via ``siege.git_view`` when set, falling back to
``content`` otherwise. New input documents created via the
``POST /api/projects/<id>/input-documents`` endpoint set
``body_sha`` + ``body_path`` and write a sentinel into
``content`` (it stays NOT NULL for back-compat).

Forward-only. Downgrade raises NotImplementedError.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c1_input_docs_git"
down_revision: Union[str, Sequence[str], None] = "b25_project_source"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("input_documents") as batch:
        batch.add_column(sa.Column("body_sha", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("body_path", sa.String(length=1024), nullable=True))


def downgrade() -> None:
    raise NotImplementedError("v3 migrations are forward-only.")
