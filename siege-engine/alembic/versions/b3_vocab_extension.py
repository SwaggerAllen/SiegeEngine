"""v2 vocabulary extension — add new node tiers and fragment kinds

Revision ID: b3_vocab_extension
Revises: b2_expansion_tier
Create Date: 2026-04-12

Widens the ``ck_nodes_tier`` and ``ck_fragments_fragment_kind``
CHECK constraints to include the node tiers and fragment kind the
updated v2 spec describes but for which no handler exists yet:

- Node tiers: ``plan``, ``reqs``, ``sysarch``, ``manifest``, ``fanin``
- Fragment kinds: ``techspec``

These are pure vocabulary additions — no existing rows move, no new
tables are created. The goal is to keep the schema in sync with the
ID/fragment enums in ``backend.graph.ids`` / ``backend.graph.fragments``
so that Phase 2+ handlers don't each have to ship their own one-line
constraint-widening migration.

Why: the first v2 spec revision (session 01VhwPhMYZwXQ2Lx7L61CKMe)
introduced several new entity kinds — see
``docs/architecture/v2-rearchitecture.md`` §ID scheme and
§Shared fragments. This migration lands the enum-widening now so that
a future reducer or handler trying to mint one of the new kinds
doesn't fail on a CHECK-constraint violation.

Forward-only. Downgrade raises NotImplementedError, matching the
other v2 migrations.
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b3_vocab_extension"
down_revision: Union[str, Sequence[str], None] = "b2_expansion_tier"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


NEW_NODE_TIERS = (
    "feat",
    "resp",
    "comp",
    "impl",
    "plan",
    "expansion",
    "reqs",
    "sysarch",
    "manifest",
    "fanin",
)

NEW_FRAGMENT_KINDS = ("techspec", "pubapi", "privapi", "deps")


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


def downgrade() -> None:
    raise NotImplementedError("v2 migrations are forward-only.")
