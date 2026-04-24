"""v2 failure-surface fragment — widen ``ck_fragments_fragment_kind``

Revision ID: b19_failure_surface_fragment
Revises: b18_draft_change_summary
Create Date: 2026-04-24

Adds ``failuresurface`` to the fragment-kind CHECK constraint so
the comparch tier can write a per-component ``<failure-surface>``
block as its own fragment. Pairs with the sysarch→comparch move of
``<failure-surface>``: sysarch no longer carries a per-component
failure blurb; comparch writes a sharper, component-local one now
that it has the full techspec + pubapi in hand.

The fragment kind is stored as the single token ``failuresurface``
(no underscore) because fragment IDs are parsed by splitting on
the last underscore — see ``backend/graph/fragments.py``.

Forward-only; downgrade raises NotImplementedError.
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b19_failure_surface_fragment"
down_revision: Union[str, Sequence[str], None] = "b18_draft_change_summary"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


NEW_FRAGMENT_KINDS = (
    "techspec",
    "pubapi",
    "privapi",
    "policies",
    "deps",
    "failuresurface",
)


def upgrade() -> None:
    with op.batch_alter_table("fragments") as batch:
        batch.drop_constraint("ck_fragments_fragment_kind", type_="check")
        batch.create_check_constraint(
            "ck_fragments_fragment_kind",
            f"fragment_kind IN {NEW_FRAGMENT_KINDS}",
        )


def downgrade() -> None:
    raise NotImplementedError("v2 migrations are forward-only.")
