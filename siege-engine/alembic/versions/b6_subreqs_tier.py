"""v2 subreqs tier — add subreqs node kind for per-component subresponsibility decomposition

Revision ID: b6_subreqs_tier
Revises: b5_policies_tier
Create Date: 2026-04-12

Widens the ``ck_nodes_tier`` CHECK constraint to include the new
``subreqs`` node kind introduced by the subrequirements decomposition
tier. One ``subreqs_*`` node is minted per top-level ``comp_*`` at
sysarch approval time; each decomposes its owning component's
top-level responsibilities into subresponsibilities on approval. See
``docs/architecture/v2-rearchitecture.md`` §Subrequirements
decomposition for the rationale.

Pure vocabulary addition — no handler exists yet; Phase 3's
per-component subreqs handler will use this widened vocabulary when
it lands. Pattern matches b3_vocab_extension and b5_policies_tier.

Forward-only. Downgrade raises NotImplementedError.
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b6_subreqs_tier"
down_revision: Union[str, Sequence[str], None] = "b5_policies_tier"
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
