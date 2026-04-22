"""v2 Phase 12 auto-revision — draft discard_reason column

Revision ID: b17_draft_discard_reason
Revises: b16_review_batches
Create Date: 2026-04-22

Adds the ``drafts.discard_reason`` column backing the auto-revision
diff baseline filter. When a discard comes from a user-initiated
Reject & Regenerate the reducer projects ``"user_regen"``; when it
comes from the AI-driven auto-revision loop (intermediate passes
the user never sees as pending) the reducer projects
``"auto_revision"``. Existing discarded drafts stay ``NULL`` and
are treated as user-initiated by construction.

``most_recent_discarded_draft_content`` filters on this so the
default regen-time diff compares against the last user-visible
pending draft, not the latest AI intermediate.

Forward-only; downgrade raises NotImplementedError.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b17_draft_discard_reason"
down_revision: Union[str, Sequence[str], None] = "b16_review_batches"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "drafts",
        sa.Column("discard_reason", sa.String(16), nullable=True),
    )


def downgrade() -> None:
    raise NotImplementedError("v2 migrations are forward-only.")
