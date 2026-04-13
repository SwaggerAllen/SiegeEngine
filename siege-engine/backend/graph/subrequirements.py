"""Subrequirements (``subreqs_*``) node helpers.

A subreqs node is the per-top-level-component analogue of
``reqs_*`` — it decomposes a single component's assigned
top-level responsibilities into **subresponsibilities** that the
component-arch pass (Phase 4) later maps onto subcomponents.
Not a singleton: there is one ``subreqs_*`` per top-level
``comp_*``, each ``parent_id=comp_id``. This module owns the
lookup helpers; the generation handler, validator, and mint
handler land in Phase 3 stage 3.

Shaped like :mod:`backend.graph.expansion` and
:mod:`backend.graph.requirements`, but scoped by owning
component. Every helper takes both ``project_id`` (so the
query filters can use the indexed ``Node.project_id`` column)
and ``comp_id`` (the ``parent_id`` scope).

See ``docs/architecture/v2-rearchitecture.md`` §Subrequirements
decomposition and ``docs/architecture/v2-roadmap.md`` Phase 3.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.graph import events as ev
from backend.graph.ids import Kind, mint
from backend.graph.reducer import append_event
from backend.models.node import Draft, Node

SUBREQS_NODE_NAME = "Subrequirements"
SUBREQS_TIER = "subreqs"


def bootstrap_subreqs_node(session: Session, project_id: str, comp_id: str) -> str:
    """Mint a subreqs node parented to ``comp_id`` and append ``NodeCreated``.

    Returns the newly-minted node id. Does **not** commit — the
    caller is responsible for transaction boundaries.
    """
    node_id = mint(session, Kind.SUBREQS)
    append_event(
        session,
        project_id,
        ev.NodeCreated(
            node_id=node_id,
            tier="subreqs",
            kind="domain",
            parent_id=comp_id,
            name=SUBREQS_NODE_NAME,
        ),
    )
    return node_id


def get_subreqs_node(session: Session, project_id: str, comp_id: str) -> Node | None:
    """Return the subreqs node for a given component, or ``None``."""
    return session.execute(
        select(Node).where(
            Node.project_id == project_id,
            Node.tier == SUBREQS_TIER,
            Node.parent_id == comp_id,
        )
    ).scalar_one_or_none()


def pending_subreqs_draft(session: Session, project_id: str, comp_id: str) -> Draft | None:
    """Return the pending draft targeting this component's subreqs node, or None."""
    node = get_subreqs_node(session, project_id, comp_id)
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


def has_been_approved(session: Session, project_id: str, comp_id: str) -> bool:
    """Return True if the component's subreqs node has ever been approved.

    Same content-based detection as the other bootstrap tiers: the
    reducer's ``DraftApproved`` branch is the only writer of
    ``Node.content``, so any non-empty content means at least one
    draft has been approved.
    """
    node = get_subreqs_node(session, project_id, comp_id)
    if node is None:
        return False
    return bool(node.content)
