"""Read-side helpers for the v2 structured model.

Application code reads projections through these functions, not by
touching the ORM models directly. This keeps the projection surface
swappable and gives us a single place to enforce project scoping.

This phase only exposes enough to back the debug endpoint. Later
phases will add paginated/filtered list APIs for the UI.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from backend.graph.fragments import FragmentKind, fragment_id
from backend.models.graph_event import GraphEvent
from backend.models.job import Job
from backend.models.node import Draft, Edge, Fragment, Node

GenerationStatus = Literal["idle", "running", "failed"]


@dataclass(frozen=True)
class ComponentContext:
    """The full context a Phase 4 comparch pass needs about one component.

    Bundles everything a comparch-generation handler would otherwise
    have to re-derive with five separate queries: the component row,
    its two sysarch-minted fragments (techspec = role paragraph,
    pubapi = api-intent paragraph), the top-level responsibilities
    assigned to it (``known_parent_resp_ids`` for validator
    cross-checks), its already-minted subresponsibilities (useful
    for comparch to know "what did subreqs land on"), and its
    dependency neighborhood (outbound and inbound ``dep`` edges
    resolved to the other end's ``comp_*`` nodes).

    Consumers should treat this as an immutable snapshot — the
    underlying rows are live ORM objects and mutating them will
    bypass the reducer. Read only.
    """

    node: Node
    techspec: str
    pubapi: str
    parent_resps: tuple[Node, ...]
    subresps: tuple[Node, ...]
    outbound_deps: tuple[Node, ...]
    inbound_deps: tuple[Node, ...]


def list_nodes(session: Session, project_id: str) -> list[Node]:
    return list(
        session.execute(
            select(Node)
            .where(Node.project_id == project_id)
            .order_by(Node.tier.asc(), Node.display_order.asc(), Node.id.asc())
        ).scalars()
    )


def list_features(session: Session, project_id: str) -> list[Node]:
    """Return the project's ``feat_*`` nodes in document order.

    Document order is the order the features appeared in the
    approved ``<features>`` block at mint time, captured in
    ``Node.display_order`` (assigned by the feature-mint handler
    — see ``backend.graph.handlers.feature_mint``).
    """
    return list(
        session.execute(
            select(Node)
            .where(Node.project_id == project_id, Node.tier == "feat")
            .order_by(Node.display_order.asc(), Node.id.asc())
        ).scalars()
    )


def top_level_resps_assigned_to(session: Session, comp_id: str) -> list[Node]:
    """Return the top-level ``resp_*`` nodes assigned to a component.

    Walks the ``decomposition`` edges with ``target_id == comp_id``
    and returns the source resp nodes (with ``parent_id=None`` to
    exclude subresps, which shouldn't ever appear as decomposition
    sources pointing at components but defence-in-depth). Ordered
    by the resp's display_order to match how they appeared in the
    original reqs output.

    Used by the subreqs generation handler to build its prompt,
    and by any route that needs to show "which top-level
    responsibilities does this component cover".
    """
    return list(
        session.execute(
            select(Node)
            .join(Edge, Edge.source_id == Node.id)
            .where(
                Edge.edge_type == "decomposition",
                Edge.target_id == comp_id,
                Node.tier == "resp",
                Node.parent_id.is_(None),
            )
            .order_by(Node.display_order.asc(), Node.id.asc())
        ).scalars()
    )


def list_subresponsibilities(session: Session, comp_id: str) -> list[Node]:
    """Return the subresponsibilities under a given component.

    Subresps minted by ``v2.mint_subrequirements`` have
    ``parent_id=comp_id``. Ordered by display_order.
    """
    return list(
        session.execute(
            select(Node)
            .where(
                Node.tier == "resp",
                Node.parent_id == comp_id,
            )
            .order_by(Node.display_order.asc(), Node.id.asc())
        ).scalars()
    )


def get_component_context(session: Session, comp_id: str) -> ComponentContext:
    """Return the full context bundle for a single top-level component.

    One-stop fetch for Phase 4 comparch generation: the component
    itself, its two sysarch-minted fragments (``comp_X_techspec``
    carries the role paragraph, ``comp_X_pubapi`` carries the
    api-intent paragraph), the top-level responsibilities assigned
    to it via ``decomposition`` edges, the subresponsibilities
    already minted under it (``parent_id=comp_id``), and the
    dependency neighborhood (resolved to the ``comp_*`` node at
    the other end of each ``dependency`` edge).

    Missing fragments return empty strings rather than raising —
    fragments may not exist yet if the caller is inspecting a
    component whose sysarch-mint ran before comparch landed the
    full techspec. Missing component raises ``ValueError`` because
    every caller we anticipate has already validated the comp_id
    via path parameters or an earlier lookup.

    Single-query strategy for the dep neighborhood: one combined
    ``SELECT`` with ``OR`` on source/target instead of two round
    trips. Same for parent_resps and subresps (two queries,
    since they live under different edge types and node
    constraints).
    """
    node = session.get(Node, comp_id)
    if node is None:
        raise ValueError(f"No node with id {comp_id!r}")
    if node.tier != "comp":
        raise ValueError(f"Node {comp_id!r} is tier={node.tier!r}, not a component")

    techspec_frag = session.get(Fragment, fragment_id(comp_id, FragmentKind.TECHSPEC))
    pubapi_frag = session.get(Fragment, fragment_id(comp_id, FragmentKind.PUBAPI))
    techspec = techspec_frag.content if techspec_frag is not None else ""
    pubapi = pubapi_frag.content if pubapi_frag is not None else ""

    parent_resps = tuple(top_level_resps_assigned_to(session, comp_id))
    subresps = tuple(list_subresponsibilities(session, comp_id))

    # Dependency neighborhood: one SELECT that returns every dep
    # edge touching this component at either end. Split into
    # outbound (source=comp_id) and inbound (target=comp_id)
    # after fetch, then resolve the other-end comp_* IDs to
    # Node rows in a second query. Two queries total for the
    # dep neighborhood.
    dep_edges = list(
        session.execute(
            select(Edge).where(
                Edge.edge_type == "dependency",
                or_(Edge.source_id == comp_id, Edge.target_id == comp_id),
            )
        ).scalars()
    )
    outbound_ids = [e.target_id for e in dep_edges if e.source_id == comp_id]
    inbound_ids = [e.source_id for e in dep_edges if e.target_id == comp_id]
    neighbor_ids = set(outbound_ids) | set(inbound_ids)

    neighbor_nodes: dict[str, Node] = {}
    if neighbor_ids:
        rows = session.execute(
            select(Node).where(Node.id.in_(neighbor_ids), Node.tier == "comp")
        ).scalars()
        neighbor_nodes = {n.id: n for n in rows}

    outbound_deps = tuple(neighbor_nodes[i] for i in outbound_ids if i in neighbor_nodes)
    inbound_deps = tuple(neighbor_nodes[i] for i in inbound_ids if i in neighbor_nodes)

    return ComponentContext(
        node=node,
        techspec=techspec,
        pubapi=pubapi,
        parent_resps=parent_resps,
        subresps=subresps,
        outbound_deps=outbound_deps,
        inbound_deps=inbound_deps,
    )


def list_top_level_components(session: Session, project_id: str) -> list[Node]:
    """Return the project's top-level ``comp_*`` nodes in document order.

    Top-level components are the ones minted by ``v2.mint_sysarch``
    on approval of the sysarch node. They have ``parent_id=None``
    — subcomponents minted by later comparch passes have a
    non-null ``parent_id`` and are not included here.
    """
    return list(
        session.execute(
            select(Node)
            .where(
                Node.project_id == project_id,
                Node.tier == "comp",
                Node.parent_id.is_(None),
            )
            .order_by(Node.display_order.asc(), Node.id.asc())
        ).scalars()
    )


def list_policies(session: Session, project_id: str) -> list[Node]:
    """Return the project's ``policy_*`` nodes in document order.

    Includes both top-level policies (minted at sysarch approval)
    and component-local policies (minted at comparch approval, Phase
    4). Sysarch-minted policies have ``parent_id=None``; comparch-
    minted policies have ``parent_id`` = the owning component. For
    MVP the list surface returns both; UI can filter as needed.
    """
    return list(
        session.execute(
            select(Node)
            .where(Node.project_id == project_id, Node.tier == "policy")
            .order_by(Node.display_order.asc(), Node.id.asc())
        ).scalars()
    )


def list_top_level_responsibilities(session: Session, project_id: str) -> list[Node]:
    """Return the project's top-level ``resp_*`` nodes in document order.

    Top-level responsibilities are the ones minted by
    ``v2.mint_requirements`` on approval of the reqs node. They
    have ``parent_id=None`` — subresponsibilities minted later by
    per-component subreqs handlers have a non-null ``parent_id``
    and are not included here.
    """
    return list(
        session.execute(
            select(Node)
            .where(
                Node.project_id == project_id,
                Node.tier == "resp",
                Node.parent_id.is_(None),
            )
            .order_by(Node.display_order.asc(), Node.id.asc())
        ).scalars()
    )


def list_edges(session: Session, project_id: str) -> list[Edge]:
    return list(
        session.execute(
            select(Edge)
            .where(Edge.project_id == project_id)
            .order_by(Edge.edge_type.asc(), Edge.id.asc())
        ).scalars()
    )


def list_fragments(session: Session, project_id: str) -> list[Fragment]:
    return list(
        session.execute(
            select(Fragment).where(Fragment.project_id == project_id).order_by(Fragment.id.asc())
        ).scalars()
    )


def list_drafts(session: Session, project_id: str) -> list[Draft]:
    return list(
        session.execute(
            select(Draft)
            .where(Draft.project_id == project_id)
            .order_by(Draft.created_at.asc(), Draft.id.asc())
        ).scalars()
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


def latest_generation_status(
    session: Session, project_id: str, job_type: str
) -> tuple[GenerationStatus, str | None]:
    """Derive a generation status from the latest job of ``job_type``.

    Returns ``("idle", None)`` if no matching job exists, or a project
    has never had one for this type. Returns ``("running", None)`` if
    the latest job is ``queued`` or ``running``. Returns
    ``("failed", error)`` if the latest job is in a terminal-failure
    state. Completed jobs are reported as ``("idle", None)``.
    """
    rows = (
        session.execute(
            select(Job).where(Job.job_type == job_type).order_by(Job.created_at.desc()).limit(10)
        )
        .scalars()
        .all()
    )
    for job in rows:
        if job.payload.get("project_id") != project_id:
            continue
        if job.status in ("queued", "running"):
            return "running", None
        if job.status in ("failed", "cancelled"):
            return "failed", job.error_message
        # completed
        return "idle", None
    return "idle", None
