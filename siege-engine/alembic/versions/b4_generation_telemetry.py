"""v2 generation telemetry — side table for per-LLM-call token usage

Revision ID: b4_generation_telemetry
Revises: b3_vocab_extension
Create Date: 2026-04-12

Adds the ``generation_telemetry`` table. Telemetry is observability,
not state — it is **not** part of the event-sourced projection and
is not written through the reducer. Handlers write rows as a side
effect of each LLM call so the UI can surface token counts on every
node and section.

See ``docs/architecture/v2-rearchitecture.md`` §Generation telemetry
for the why.

Forward-only. Downgrade raises NotImplementedError.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b4_generation_telemetry"
down_revision: Union[str, Sequence[str], None] = "b3_vocab_extension"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "generation_telemetry",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(length=64),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("node_id", sa.String(length=64), nullable=True),
        sa.Column("section", sa.String(length=32), nullable=True),
        sa.Column("model", sa.String(length=64), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completion_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_generation_telemetry_project_id",
        "generation_telemetry",
        ["project_id"],
    )
    op.create_index(
        "ix_generation_telemetry_project_node_created",
        "generation_telemetry",
        ["project_id", "node_id", "created_at"],
    )


def downgrade() -> None:
    raise NotImplementedError("v2 migrations are forward-only.")
