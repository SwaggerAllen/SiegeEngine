"""v2 foundation marker — add is_foundation column to nodes

Revision ID: b10_is_foundation
Revises: b9_decomposition_edge
Create Date: 2026-04-14

Adds an ``is_foundation`` boolean to the ``nodes`` table so the
foundation role minted by sysarch / comparch is first-class state,
readable at comparch-generation time without re-parsing upstream
arch-doc content. The foundation marker was already parsed out of
sysarch / comparch output by the validator (``Component.is_foundation``
/ ``Subcomponent.is_foundation``) but the mint handlers previously
discarded it after satisfying their invariant checks.

Persisting the flag unblocks the "foundations don't nest" carve-out:
a comparch pass whose target component was itself minted as a
foundation skips the "include a foundation subcomponent" invariant
and instead decomposes its territory exhaustively. See
``docs/architecture/v2-rearchitecture.md`` §Foundation components.

Defaults to ``false`` for every existing row. Non-comp tiers ignore
the column.

Forward-only. Downgrade raises NotImplementedError.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b10_is_foundation"
down_revision: Union[str, Sequence[str], None] = "b9_decomposition_edge"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("nodes") as batch:
        batch.add_column(
            sa.Column(
                "is_foundation",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )


def downgrade() -> None:
    raise NotImplementedError("v2 migrations are forward-only.")
