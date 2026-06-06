"""Project reference node lookups.

Reference entries are ``ref_*`` nodes — a first-class node tier
carrying supplemental documents (DSL specs, deployment runbooks,
cross-component invariants) whose bodies live in the project repo
at ``refs/<ref_id>/body.md`` (v3 git-backed). The dashboard reads
the projected state via these helpers; authoring happens in
Claude Code via the ``/create_ref`` skill.

Unlike vocabulary (scoped via ``parent_id`` to project or feature),
refs are always top-level: the reducer
(``_enforce_reference_parent_constraint``) rejects any attempt to
parent a ref under another node.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models.node import Edge, Node

REF_TIER = "ref"
REFERENCE_EDGE_TYPE = "reference"


def list_project_references(session: Session, project_id: str) -> list[Node]:
    """Return every ``ref_*`` node in the project, ordered by name."""
    return list(
        session.execute(
            select(Node)
            .where(
                Node.project_id == project_id,
                Node.tier == REF_TIER,
            )
            .order_by(Node.name.asc())
        ).scalars()
    )


def reference_by_id(session: Session, ref_id: str) -> Node | None:
    """Return the ``ref_*`` node with ``id == ref_id``, or ``None``."""
    node = session.get(Node, ref_id)
    if node is None or node.tier != REF_TIER:
        return None
    return node


def reference_by_name(session: Session, project_id: str, name: str) -> Node | None:
    """Look up a ref by its title/name within the project."""
    return session.execute(
        select(Node).where(
            Node.project_id == project_id,
            Node.tier == REF_TIER,
            Node.name == name,
        )
    ).scalar_one_or_none()


def outgoing_reference_edges(session: Session, project_id: str, source_id: str) -> list[Edge]:
    """Return every ``reference`` edge whose source is ``source_id``."""
    return list(
        session.execute(
            select(Edge).where(
                Edge.project_id == project_id,
                Edge.edge_type == REFERENCE_EDGE_TYPE,
                Edge.source_id == source_id,
            )
        ).scalars()
    )


def incoming_reference_edges(session: Session, project_id: str, target_id: str) -> list[Edge]:
    """Return every ``reference`` edge whose target is ``target_id``."""
    return list(
        session.execute(
            select(Edge).where(
                Edge.project_id == project_id,
                Edge.edge_type == REFERENCE_EDGE_TYPE,
                Edge.target_id == target_id,
            )
        ).scalars()
    )
