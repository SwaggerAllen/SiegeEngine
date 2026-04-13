"""Requirements (``reqs_*``) node helpers.

A project's *requirements* node is the second bootstrap doc in the
v2 cold-start chain. It decomposes the approved feature set into
top-level responsibilities that the sysarch pass will later map
onto concrete components. One per project (singleton), same draft
→ feedback → approve → read-only lifecycle as the expansion node.

On approval, the ``v2.mint_requirements`` handler projects each
``<responsibility>`` entry into a top-level ``resp_*`` node. The
``reqs_*`` node then becomes read-only; further responsibility-layer
edits happen against individual ``resp_*`` nodes (Phase 10), not
by re-editing the prose bootstrap.

Shaped like :mod:`backend.graph.expansion` — three helpers plus a
post-approval read-only check. Callers manage transaction
boundaries.

See ``docs/architecture/v2-rearchitecture.md`` §Generation order and
``docs/architecture/v2-roadmap.md`` Phase 3.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.graph import events as ev
from backend.graph.ids import Kind, mint
from backend.graph.reducer import append_event
from backend.models.node import Draft, Node

REQS_NODE_NAME = "Requirements"
REQS_TIER = "reqs"


def bootstrap_reqs_node(session: Session, project_id: str) -> str:
    """Mint the project's reqs node and append ``NodeCreated``.

    Returns the newly-minted node id. Does **not** commit — the
    caller is responsible for transaction boundaries.
    """
    node_id = mint(session, Kind.REQS)
    append_event(
        session,
        project_id,
        ev.NodeCreated(
            node_id=node_id,
            tier="reqs",
            kind="domain",
            parent_id=None,
            name=REQS_NODE_NAME,
        ),
    )
    return node_id


def get_reqs_node(session: Session, project_id: str) -> Node | None:
    """Return the project's reqs node, or ``None`` if missing."""
    return session.execute(
        select(Node).where(
            Node.project_id == project_id,
            Node.tier == REQS_TIER,
        )
    ).scalar_one_or_none()


def pending_reqs_draft(session: Session, project_id: str) -> Draft | None:
    """Return the pending draft targeting the project's reqs node, or None."""
    node = get_reqs_node(session, project_id)
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


def has_been_approved(session: Session, project_id: str) -> bool:
    """Return True if the project's reqs node has ever been approved.

    Same ``content``-based detection as
    :func:`backend.graph.expansion.has_been_approved`: the reducer's
    ``DraftApproved`` branch is the only writer of ``Node.content``,
    so any non-empty content means at least one draft has been
    approved. The MVP relies on this invariant across all bootstrap
    tiers; a formal read-only flag can replace it once we hit a
    case that breaks the assumption.
    """
    node = get_reqs_node(session, project_id)
    if node is None:
        return False
    return bool(node.content)
