"""v2 vocab tier — add vocab to NODE_TIERS check constraint

Revision ID: b11_vocab_tier
Revises: b10_is_foundation
Create Date: 2026-04-14

Adds the `vocab` tier to the ``nodes`` check constraint so
project vocabulary entries can be persisted as first-class
nodes. See ``docs/architecture/v2-rearchitecture.md`` §Project
vocabulary for the full rationale.

Vocab is a node tier rather than a fragment because vocab
entries are entities with independent lifecycles — edit /
review / reparent / direct user creation via the instruction
vocabulary. The tier itself is simple; the grammar of the
content (parseable ``<vocab-entry>`` XML with definition /
disambiguation / see-also children) is enforced by the
validator at authoring time, not by the schema.

Forward-only. Downgrade raises NotImplementedError.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b11_vocab_tier"
down_revision: Union[str, Sequence[str], None] = "b10_is_foundation"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


NEW_NODE_TIERS = (
    "feat",
    "resp",
    "comp",
    "impl",
    "plan",
    "policy",
    "expansion",
    "reqs",
    "subreqs",
    "sysarch",
    "manifest",
    "fanin",
    "vocab",
)


def upgrade() -> None:
    with op.batch_alter_table("nodes") as batch:
        batch.drop_constraint("ck_nodes_tier", type_="check")
        batch.create_check_constraint(
            "ck_nodes_tier",
            f"tier IN {NEW_NODE_TIERS}",
        )


def downgrade() -> None:
    raise NotImplementedError("v2 migrations are forward-only.")
