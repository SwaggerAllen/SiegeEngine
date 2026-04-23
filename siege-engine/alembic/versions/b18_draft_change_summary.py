"""v2 Phase 13 change summaries — draft change_summary column

Revision ID: b18_draft_change_summary
Revises: b17_draft_discard_reason
Create Date: 2026-04-23

Adds the ``drafts.change_summary`` column backing the Phase 13
change-summary flow. Every bootstrap-tier (and reference) generator
prompt instructs the LLM to emit a ``<change-summary>`` sibling to
``<introduction>`` in its output; ``persist_draft`` lifts the tag
body out and stores it here, stripping it from the draft's content
so downstream readers see only document prose.

Existing drafts stay ``NULL`` — the walker and the regen diff
header both treat NULL as "no summary recorded" and render nothing.

Forward-only; downgrade raises NotImplementedError.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b18_draft_change_summary"
down_revision: Union[str, Sequence[str], None] = "b17_draft_discard_reason"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "drafts",
        sa.Column("change_summary", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    raise NotImplementedError("v2 migrations are forward-only.")
