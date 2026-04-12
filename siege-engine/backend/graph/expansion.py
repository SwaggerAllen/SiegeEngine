"""Feature-expansion node helpers.

A project's *feature expansion* is a single prose markdown document
that explores what features the project should have. It is stored on
a dedicated `expansion`-tier ``Node`` (one per project), and iterated
via draft approval — the user submits prose feedback, the handler
regenerates the draft, and the user approves the final version. The
approval path reuses the standard ``DraftApproved`` reducer branch,
so no new reducer code is needed here.

This module is the minimal plumbing for:
  * minting the expansion node on project creation (``bootstrap_expansion_node``)
  * looking it up again from routes and handlers (``get_expansion_node``)
  * looking up the current pending draft for regen / approval flows
    (``pending_expansion_draft``)

All three are synchronous and session-bound; callers manage commits.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.graph import events as ev
from backend.graph.ids import Kind, mint
from backend.graph.reducer import append_event
from backend.models.node import Draft, Node

EXPANSION_NODE_NAME = "Feature Expansion"
EXPANSION_TIER = "expansion"


def bootstrap_expansion_node(session: Session, project_id: str) -> str:
    """Mint the project's expansion node and append ``NodeCreated``.

    Returns the newly-minted node id. Does **not** commit — the caller
    is responsible for transaction boundaries so that the node row and
    any follow-up job enqueue land in a consistent order.
    """
    node_id = mint(session, Kind.EXPANSION)
    append_event(
        session,
        project_id,
        ev.NodeCreated(
            node_id=node_id,
            tier="expansion",
            kind="domain",
            parent_id=None,
            name=EXPANSION_NODE_NAME,
        ),
    )
    return node_id


def get_expansion_node(session: Session, project_id: str) -> Node | None:
    """Return the project's expansion node, or ``None`` if missing."""
    return session.execute(
        select(Node).where(
            Node.project_id == project_id,
            Node.tier == EXPANSION_TIER,
        )
    ).scalar_one_or_none()


def pending_expansion_draft(session: Session, project_id: str) -> Draft | None:
    """Return the pending draft targeting the project's expansion node.

    Returns ``None`` if there is no expansion node yet or no draft in
    ``pending`` status for it. The partial unique index
    ``uq_drafts_pending_target`` guarantees at most one such row.
    """
    node = get_expansion_node(session, project_id)
    if node is None:
        return None
    return session.execute(
        select(Draft).where(
            Draft.project_id == project_id,
            Draft.target_type == "node",
            Draft.target_id == node.id,
            Draft.status == "pending",
        )
    ).scalar_one_or_none()
