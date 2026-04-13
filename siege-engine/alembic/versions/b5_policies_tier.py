"""v2 policies tier — add policy node kind, policies fragment, policy_application edge

Revision ID: b5_policies_tier
Revises: b4_generation_telemetry
Create Date: 2026-04-12

Widens three CHECK constraints to accommodate the new policies
vocabulary from the revised v2 spec:

- ``ck_nodes_tier`` → adds ``policy``
- ``ck_fragments_fragment_kind`` → adds ``policies``
- ``ck_edges_edge_type`` → adds ``policy_application``

Pure vocabulary additions — no handlers exist yet for the new
kinds; Phase 3/4 implementation work uses this widened vocabulary
when it lands. Pattern matches ``b3_vocab_extension``: forward-only,
batch_alter_table rebuild of the table for SQLite portability.

See ``docs/architecture/v2-rearchitecture.md`` §Policies and
§Subcomponent depth cap for the why. The subcomponent depth cap
itself is enforced in the reducer, not the DB — a CHECK constraint
can't express "this parent's parent is already a comp_*".
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b5_policies_tier"
down_revision: Union[str, Sequence[str], None] = "b4_generation_telemetry"
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
    "sysarch",
    "manifest",
    "fanin",
)

NEW_FRAGMENT_KINDS = ("techspec", "pubapi", "privapi", "policies", "deps")

NEW_EDGE_TYPES = ("dependency", "domain_parent", "policy_application")


def upgrade() -> None:
    with op.batch_alter_table("nodes") as batch:
        batch.drop_constraint("ck_nodes_tier", type_="check")
        batch.create_check_constraint(
            "ck_nodes_tier",
            f"tier IN {NEW_NODE_TIERS}",
        )
    with op.batch_alter_table("fragments") as batch:
        batch.drop_constraint("ck_fragments_fragment_kind", type_="check")
        batch.create_check_constraint(
            "ck_fragments_fragment_kind",
            f"fragment_kind IN {NEW_FRAGMENT_KINDS}",
        )
    with op.batch_alter_table("edges") as batch:
        batch.drop_constraint("ck_edges_edge_type", type_="check")
        batch.create_check_constraint(
            "ck_edges_edge_type",
            f"edge_type IN {NEW_EDGE_TYPES}",
        )


def downgrade() -> None:
    raise NotImplementedError("v2 migrations are forward-only.")
