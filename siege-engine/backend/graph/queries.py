"""Read-side helpers for the v2 structured model.

Application code reads projections through these functions, not by
touching the ORM models directly. This keeps the projection surface
swappable and gives us a single place to enforce project scoping.

This phase only exposes enough to back the debug endpoint. Later
phases will add paginated/filtered list APIs for the UI.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.models.graph_event import GraphEvent
from backend.models.node import Draft, Edge, Fragment, Node


def list_nodes(session: Session, project_id: str) -> list[Node]:
    return list(
        session.execute(
            select(Node)
            .where(Node.project_id == project_id)
            .order_by(Node.tier.asc(), Node.display_order.asc(), Node.id.asc())
        )
        .scalars()
    )


def list_edges(session: Session, project_id: str) -> list[Edge]:
    return list(
        session.execute(
            select(Edge)
            .where(Edge.project_id == project_id)
            .order_by(Edge.edge_type.asc(), Edge.id.asc())
        )
        .scalars()
    )


def list_fragments(session: Session, project_id: str) -> list[Fragment]:
    return list(
        session.execute(
            select(Fragment)
            .where(Fragment.project_id == project_id)
            .order_by(Fragment.id.asc())
        )
        .scalars()
    )


def list_drafts(session: Session, project_id: str) -> list[Draft]:
    return list(
        session.execute(
            select(Draft)
            .where(Draft.project_id == project_id)
            .order_by(Draft.created_at.asc(), Draft.id.asc())
        )
        .scalars()
    )


def event_count(session: Session, project_id: str) -> int:
    return (
        session.execute(
            select(func.count(GraphEvent.id)).where(GraphEvent.project_id == project_id)
        ).scalar()
        or 0
    )


def latest_offset(session: Session, project_id: str) -> int | None:
    return session.execute(
        select(func.max(GraphEvent.offset)).where(GraphEvent.project_id == project_id)
    ).scalar()


def projection_snapshot(session: Session, project_id: str) -> dict:
    """Return the full projection state for the debug endpoint."""
    return {
        "nodes": [_node_dict(n) for n in list_nodes(session, project_id)],
        "edges": [_edge_dict(e) for e in list_edges(session, project_id)],
        "fragments": [_fragment_dict(f) for f in list_fragments(session, project_id)],
        "drafts": [_draft_dict(d) for d in list_drafts(session, project_id)],
        "event_count": event_count(session, project_id),
        "latest_offset": latest_offset(session, project_id),
    }


# ── Serializers ──────────────────────────────────────────────────────


def _node_dict(n: Node) -> dict:
    return {
        "id": n.id,
        "tier": n.tier,
        "kind": n.kind,
        "parent_id": n.parent_id,
        "name": n.name,
        "display_order": n.display_order,
        "content": n.content,
    }


def _edge_dict(e: Edge) -> dict:
    return {
        "id": e.id,
        "edge_type": e.edge_type,
        "source_id": e.source_id,
        "target_id": e.target_id,
    }


def _fragment_dict(f: Fragment) -> dict:
    return {
        "id": f.id,
        "owner_id": f.owner_id,
        "fragment_kind": f.fragment_kind,
        "content": f.content,
    }


def _draft_dict(d: Draft) -> dict:
    return {
        "id": d.id,
        "target_type": d.target_type,
        "target_id": d.target_id,
        "content": d.content,
        "status": d.status,
        "batch_id": d.batch_id,
    }
