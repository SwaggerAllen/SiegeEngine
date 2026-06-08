"""Drop legacy write-pipeline tables (pending_instructions, views, batches).

Revision ID: c3_drop_legacy_write_tables
Revises: c2_refs_git
Create Date: 2026-06-07

Three tables go: the Phase-11 ``pending_instructions`` (UI-issued
instruction queue), its companion ``views`` (event-log offset
markers from the projection-rebuild flow), and the Phase-14
universal-tagging ``batches``. All backed the legacy write path
that retired with the v3 substrate cutover; nothing in this
backend writes or reads any of them anymore.

**Not dropped here:**

- ``jobs`` — still read by ``backend.graph.queries`` to surface
  pre-retirement generation history on the dashboard (skeleton
  panel, feedback-history panel, latest-generation badges). The
  pipeline that wrote these rows is gone (no new rows land), but
  the historical projection is still served. A follow-up
  migration can drop the table once the FE consumers retire too.
- ``staleness_ledger`` — write-frozen but read-active for
  sidebar badges. Same plan as ``jobs``.

The ``jobs.batch_id`` FK references ``batches.id``; we drop the
index first so the FK constraint can be dropped via SQLite's
batch_alter_table, then drop the column itself, before dropping
the parent ``batches`` table.

Forward-only; downgrade raises NotImplementedError.
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c3_drop_legacy_write_tables"
down_revision: Union[str, Sequence[str], None] = "c2_refs_git"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_table("pending_instructions")
    op.drop_table("views")

    # ``jobs.batch_id`` FK → ``batches.id`` blocks the parent drop.
    # Remove the index + column first via SQLite batch mode.
    op.drop_index("ix_jobs_batch_id", table_name="jobs", if_exists=True)
    with op.batch_alter_table("jobs") as batch:
        batch.drop_column("batch_id")

    op.drop_table("batches")


def downgrade() -> None:
    raise NotImplementedError("v2 migrations are forward-only.")
