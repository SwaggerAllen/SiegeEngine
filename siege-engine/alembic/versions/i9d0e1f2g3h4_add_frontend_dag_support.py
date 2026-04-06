"""Add dag_type and domain_parents columns to component_definitions.

Revision ID: i9d0e1f2g3h4
Revises: h8c9d0e1f2g3
Create Date: 2026-04-06

"""

from typing import Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "i9d0e1f2g3h4"
down_revision: Union[str, None] = "h8c9d0e1f2g3"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    with op.batch_alter_table("component_definitions") as batch_op:
        batch_op.add_column(
            sa.Column("dag_type", sa.String(20), nullable=False, server_default="domain")
        )
        batch_op.add_column(
            sa.Column("domain_parents", sa.JSON(), nullable=True)
        )
        # Drop the old unique index and create a new one that includes dag_type
        batch_op.drop_index("uq_comp_def_project_key_parent")
        batch_op.create_index(
            "uq_comp_def_project_key_parent_dag",
            ["project_id", "key", sa.text("COALESCE(parent_key, '')"), "dag_type"],
            unique=True,
        )


def downgrade() -> None:
    with op.batch_alter_table("component_definitions") as batch_op:
        batch_op.drop_index("uq_comp_def_project_key_parent_dag")
        batch_op.create_index(
            "uq_comp_def_project_key_parent",
            ["project_id", "key", sa.text("COALESCE(parent_key, '')")],
            unique=True,
        )
        batch_op.drop_column("domain_parents")
        batch_op.drop_column("dag_type")
