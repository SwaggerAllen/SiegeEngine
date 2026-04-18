"""v2 Phase 8 — AI self-review text columns on nodes + drafts

Revision ID: b13_review_text
Revises: b12_ref_tier
Create Date: 2026-04-18

Adds ``review_text TEXT NOT NULL DEFAULT ''`` to both the
``nodes`` and ``drafts`` tables so Phase 8's per-draft AI self-
review has a place to land:

- ``drafts.review_text``: normal draft-bearing tiers
  (expansion, requirements, sysarch, subreqs, comparch,
  subcomparch, impl) stash their review output here. The Draft
  row is thrown away on regen/discard, which also discards the
  stale review.
- ``nodes.review_text``: fanin uses this since it has no draft
  lifecycle (content writes direct-to-node). The retroactive
  review path (Generate review button on approved content also
  targets the node row — reviews minted against pre-Phase-8
  content or against content approved with
  ``SIEGE_DISABLE_AI_REVIEW=1`` both land here.

See ``docs/architecture/v2-roadmap.md`` Phase 8.5.

Forward-only. Downgrade raises NotImplementedError.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b13_review_text"
down_revision: Union[str, Sequence[str], None] = "b12_ref_tier"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("nodes") as batch:
        batch.add_column(
            sa.Column(
                "review_text",
                sa.Text(),
                nullable=False,
                server_default="",
            )
        )
    with op.batch_alter_table("drafts") as batch:
        batch.add_column(
            sa.Column(
                "review_text",
                sa.Text(),
                nullable=False,
                server_default="",
            )
        )


def downgrade() -> None:
    raise NotImplementedError("v2 migrations are forward-only.")
