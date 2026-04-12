"""v2 expansion tier — widen nodes.tier CHECK to include 'expansion'

Revision ID: b2_expansion_tier
Revises: b1_v2_foundation
Create Date: 2026-04-12

Widens the ``ck_nodes_tier`` CHECK constraint on ``nodes`` to include
the new ``expansion`` tier. SQLite doesn't support
``ALTER TABLE ... DROP CONSTRAINT`` directly, so this uses
``batch_alter_table`` which rebuilds the table under the hood.

Why: the first vertical slice (input doc → feature expansion → approval)
introduces a new per-project expansion-tier node that carries the
prose feature-expansion markdown. The content is committed onto the
node via the standard ``DraftApproved`` path; no new reducer branch
is needed. But the CHECK constraint from ``b1_v2_foundation`` only
allows the four foundation tiers, so we have to widen it here.

Forward-only. Downgrade raises NotImplementedError.
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b2_expansion_tier"
down_revision: Union[str, Sequence[str], None] = "b1_v2_foundation"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


NEW_NODE_TIERS = ("feat", "resp", "comp", "impl", "expansion")


def upgrade() -> None:
    with op.batch_alter_table("nodes") as batch:
        batch.drop_constraint("ck_nodes_tier", type_="check")
        batch.create_check_constraint(
            "ck_nodes_tier",
            f"tier IN {NEW_NODE_TIERS}",
        )


def downgrade() -> None:
    raise NotImplementedError("v2 migrations are forward-only.")
