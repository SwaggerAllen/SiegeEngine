"""v2 decomposition edge type — widen ck_edges_edge_type

Revision ID: b9_decomposition_edge
Revises: b8_project_settings
Create Date: 2026-04-13

Widens the ``ck_edges_edge_type`` CHECK constraint to include
the new ``decomposition`` edge type introduced for many-to-many
feature→responsibility and top-level-responsibility→subresponsibility
relationships. See:

- ``docs/architecture/v2-rearchitecture.md`` §Edge type vocabulary
- ``docs/architecture/v2-rearchitecture.md`` §Feature → Responsibility → Component
- ``docs/architecture/v2-rearchitecture.md`` §Subrequirements decomposition
- ``docs/architecture/v2-roadmap.md`` Phase 3 shared-infrastructure

The ``decomposition`` edge type covers two shapes:

- ``feat_X → resp_Y`` — the feature implicates the top-level
  responsibility. Emitted by the ``v2.mint_requirements``
  handler when approving a ``reqs_*`` draft that carries
  ``<covers>`` children on each ``<responsibility>`` entry.
- ``top_level_resp_X → subresp_Y`` — the top-level responsibility
  decomposes into the subresp within the subresp's owning
  component. Emitted by the ``v2.mint_subreqs`` handler
  (Phase 3 stage 3).

Same shape as b5_policies_tier — pure vocabulary widen, no data
changes, no new tables. Handlers that need the new edge type
will be updated in the same commit that lands them.

Pattern matches b5_policies_tier. Forward-only. Downgrade raises
NotImplementedError.
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b9_decomposition_edge"
down_revision: Union[str, Sequence[str], None] = "b8_project_settings"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


NEW_EDGE_TYPES = (
    "dependency",
    "domain_parent",
    "policy_application",
    "decomposition",
)


def upgrade() -> None:
    with op.batch_alter_table("edges") as batch:
        batch.drop_constraint("ck_edges_edge_type", type_="check")
        batch.create_check_constraint(
            "ck_edges_edge_type",
            f"edge_type IN {NEW_EDGE_TYPES}",
        )


def downgrade() -> None:
    raise NotImplementedError("v2 migrations are forward-only.")
