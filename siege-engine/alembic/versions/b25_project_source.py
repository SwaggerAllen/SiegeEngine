"""project source column — remote vs upload

Revision ID: b25_project_source
Revises: b24_cohort_experimental_comp_ids
Create Date: 2026-05-24

Adds a ``source`` column to ``projects`` distinguishing the two
create-project flows: the existing GitHub-remote path (``"remote"``)
and the new tarball-upload path (``"upload"``). Existing rows backfill
to ``"remote"`` via ``server_default`` — that's the only kind of
project the table has carried until now, so the default is correct.

The column drives the ``Project.is_writable`` property. Upload
projects have no remote to push to, so the writer endpoints
(``/remote``, ``/push``, ``/open-pr``, the auto-push toggle) refuse
them. The implicit ``remote_url is None`` check today already does the
right thing for the GitHub push paths, but a project legitimately
created via the remote flow with the URL field blank would conflate
with an upload — the explicit column removes that ambiguity.

Forward-only. Downgrade raises NotImplementedError.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b25_project_source"
down_revision: Union[str, Sequence[str], None] = "b24_cohort_experimental_comp_ids"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("projects") as batch:
        batch.add_column(
            sa.Column("source", sa.String(16), nullable=False, server_default="remote")
        )


def downgrade() -> None:
    raise NotImplementedError("v2 migrations are forward-only.")
