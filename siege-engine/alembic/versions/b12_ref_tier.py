"""v2 reference tier + reference edge type

Revision ID: b12_ref_tier
Revises: b11_vocab_tier
Create Date: 2026-04-16

Adds the ``ref`` tier to ``ck_nodes_tier`` and the ``reference``
edge type to ``ck_edges_edge_type``. See:

- ``docs/architecture/v2-rearchitecture.md`` §Project references
- ``docs/architecture/v2-roadmap.md`` Phase 6.6

Refs are first-class documents that any node can pull into its
regen context via an outgoing ``reference`` edge — DSL specs,
deployment runbooks, cross-component invariants. Content is
parseable XML (``<reference>`` grammar with ``<title>`` /
``<body>`` / optional ``<see-also>``) stored verbatim on
``Node.content``; the validator enforces grammar at authoring
time.

The ``reference`` edge type is general-purpose advisory context —
not specific to refs. Any node can draw a ``reference`` edge to
any other node. The reducer enforces ``parent_id = None`` on ref
nodes themselves (refs are never scoped below the project root).

Single migration covers both the tier and edge-type widening,
same pattern as b11_vocab_tier and b9_decomposition_edge. Forward-
only. Downgrade raises NotImplementedError.
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b12_ref_tier"
down_revision: Union[str, Sequence[str], None] = "b11_vocab_tier"
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
    "ref",
)


NEW_EDGE_TYPES = (
    "dependency",
    "domain_parent",
    "policy_application",
    "decomposition",
    "reference",
)


def upgrade() -> None:
    with op.batch_alter_table("nodes") as batch:
        batch.drop_constraint("ck_nodes_tier", type_="check")
        batch.create_check_constraint(
            "ck_nodes_tier",
            f"tier IN {NEW_NODE_TIERS}",
        )
    with op.batch_alter_table("edges") as batch:
        batch.drop_constraint("ck_edges_edge_type", type_="check")
        batch.create_check_constraint(
            "ck_edges_edge_type",
            f"edge_type IN {NEW_EDGE_TYPES}",
        )


def downgrade() -> None:
    raise NotImplementedError("v2 migrations are forward-only.")
