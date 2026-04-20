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
from backend.models.node import Draft, Edge, Fragment, Node, StalenessLedger

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


def list_features(
    session: Session,
    project_id: str,
    *,
    include_deferred: bool = True,
) -> list[Node]:
    """Return the project's ``feat_*`` nodes in document order.

    Document order is the order the features appeared in the
    approved ``<features>`` block at mint time, captured in
    ``Node.display_order`` (assigned by the feature-mint handler
    — see ``backend.graph.handlers.feature_mint``).

    Phase-11 followup B7: callers that feed the generation
    pipeline (requirements, sysarch) pass ``include_deferred=False``
    to filter out features marked ``is_deferred``. Read-only
    surfaces (DAG view, sidebar, feature-detail panels) keep the
    default and show everything.
    """
    query = select(Node).where(Node.project_id == project_id, Node.tier == "feat")
    if not include_deferred:
        query = query.where(Node.is_deferred.is_(False))
    return list(
        session.execute(query.order_by(Node.display_order.asc(), Node.id.asc())).scalars()
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


def domain_parents_of(session: Session, comp_id: str) -> list[Node]:
    """Return the domain-parent ``comp_*`` nodes for a presentational comp.

    Walks ``domain_parent`` edges where ``source_id == comp_id``
    and returns the target components. The sysarch mint handler
    emits these edges with the direction
    ``presentational → domain``, so the source side is always a
    presentational component. Callers that call this on a domain
    component will get an empty list.

    Used by the subreqs generation handler to look up "what
    domain components does this presentational component
    present" so the LLM can see the domain parent's already-
    minted subresps as read-only context when writing UI-side
    subresps.
    """
    return list(
        session.execute(
            select(Node)
            .join(Edge, Edge.target_id == Node.id)
            .where(
                Edge.edge_type == "domain_parent",
                Edge.source_id == comp_id,
                Node.tier == "comp",
            )
            .order_by(Node.display_order.asc(), Node.id.asc())
        ).scalars()
    )


def dependencies_of(session: Session, comp_id: str) -> list[Node]:
    """Return the ``comp_*`` nodes this comp declares as dependencies.

    Walks ``dependency`` edges where ``source_id == comp_id`` and
    returns the target components. The sysarch mint handler emits
    these edges from ``<dependencies>`` / ``<dep from=… to=…/>``
    entries, so the direction is always ``this comp → its dep``.

    Used by the subreqs generation handler to thread read-only
    sibling-dependency context into the prompt: when writing
    subresponsibilities for this comp, the LLM should see what
    each dependency already exposes (via the dep's ``pubapi``
    fragment) and avoid re-deriving responsibilities the deps
    already own.
    """
    return list(
        session.execute(
            select(Node)
            .join(Edge, Edge.target_id == Node.id)
            .where(
                Edge.edge_type == "dependency",
                Edge.source_id == comp_id,
                Node.tier == "comp",
            )
            .order_by(Node.display_order.asc(), Node.id.asc())
        ).scalars()
    )


def presentational_children_of(session: Session, comp_id: str) -> list[Node]:
    """Return the presentational comps that declare ``comp_id`` as a domain parent.

    Inverse of :func:`domain_parents_of`. Walks ``domain_parent``
    edges where ``target_id == comp_id`` and returns the source
    components. Used by the comparch mint handler to discover
    which presentational comps are potentially unblocked by the
    approval of this domain comp's arch doc — each of those
    presentationals gets a readiness check afterwards and, if
    ready, its own comparch generation is enqueued.
    """
    return list(
        session.execute(
            select(Node)
            .join(Edge, Edge.source_id == Node.id)
            .where(
                Edge.edge_type == "domain_parent",
                Edge.target_id == comp_id,
                Node.tier == "comp",
            )
            .order_by(Node.display_order.asc(), Node.id.asc())
        ).scalars()
    )


def all_domain_parents_have_populated_fanin(session: Session, comp_id: str) -> bool:
    """True iff every ``domain_parent`` target of ``comp_id`` has a populated fan-in node.

    Phase 7.5 gate change: a presentational component's comparch
    now waits on the domain side's **fan-in synthesis**, not on
    the domain's comparch approval. The fan-in is the bottom-up
    summary of what the domain component as-built actually does —
    the presentational's public surface aligns to real behavior
    rather than to skeletal comparch intent. This deepens the
    sequencing (domain impl must complete before presentational
    comparch starts) but eliminates drift between the
    presentational's top-down contract and the domain's
    bottom-up reality.

    Returns ``True`` unconditionally for any comp that has no
    ``domain_parent`` edges (including every domain comp). A
    populated fan-in is defined as "a ``fanin_*`` child of the
    domain parent whose ``content`` field is non-empty" —
    ``FanInContentUpdated`` is the only writer.
    """
    parents = domain_parents_of(session, comp_id)
    if not parents:
        return True
    for parent in parents:
        fanin = session.execute(
            select(Node).where(
                Node.tier == "fanin",
                Node.parent_id == parent.id,
            )
        ).scalar_one_or_none()
        if fanin is None or not (fanin.content or "").strip():
            return False
    return True


def all_impls_populated_for(session: Session, owner_comp_id: str) -> bool:
    """True iff every impl_* in ``owner_comp_id``'s subtree has content.

    Phase 7.5 gate for fan-in first-pass completion. Fan-in
    synthesis waits until every impl node under the owner (a
    fanned-out top-level domain comp) has been approved at least
    once before firing for the first time — subsequent approvals
    re-fire (deduped by the queue) so ongoing iteration still
    propagates.

    Returns ``False`` when the subtree has no impl nodes at all
    (no subcomps yet, or comparch hasn't minted them). Returns
    ``False`` when any impl has empty content (never approved, or
    reset-cleared). Returns ``True`` only when every expected
    impl carries approved content.

    Un-fanned-out domain comps aren't expected to call this (they
    have no fan-in) but the helper still handles them correctly
    by looking for a single impl child directly under the owner.
    """
    owner = session.get(Node, owner_comp_id)
    if owner is None:
        return False

    subcomps = list(
        session.execute(
            select(Node).where(
                Node.tier == "comp",
                Node.parent_id == owner_comp_id,
            )
        ).scalars()
    )

    if not subcomps:
        # Un-fanned-out: a single impl child directly under owner.
        impl = session.execute(
            select(Node).where(
                Node.tier == "impl",
                Node.parent_id == owner_comp_id,
            )
        ).scalar_one_or_none()
        if impl is None:
            return False
        return bool((impl.content or "").strip())

    # Fanned-out: each sub must carry a populated impl child.
    for sub in subcomps:
        impl = session.execute(
            select(Node).where(
                Node.tier == "impl",
                Node.parent_id == sub.id,
            )
        ).scalar_one_or_none()
        if impl is None or not (impl.content or "").strip():
            return False
    return True


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


def list_subcomponents_of(session: Session, comp_id: str) -> list[Node]:
    """Return the subcomponent ``comp_*`` nodes under a top-level comp.

    Subcomponents are ``comp`` tier nodes minted by the comparch
    mint handler with ``parent_id`` pointing at the owning
    top-level component. They carry their inherited kind on the
    row. Ordered by display_order (the comparch mint handler
    assigns it at decomposition time, one per
    ``<subcomponent>`` entry).

    Used by the Phase 5 subcomparch regen context to find a
    subcomponent's same-parent siblings and by the route layer to
    render the SubcomponentList UI on the comparch page.
    """
    return list(
        session.execute(
            select(Node)
            .where(
                Node.tier == "comp",
                Node.parent_id == comp_id,
            )
            .order_by(Node.display_order.asc(), Node.id.asc())
        ).scalars()
    )


def pending_draft_kinds_by_comp(session: Session, project_id: str) -> dict[str, str]:
    """Return ``{comp_id: kind}`` for every comp with a pending draft on it.

    "Pending draft on it" is scoped per comp and covers three
    cases, reported as three distinct kinds so the UI can badge
    each comp appropriately:

    - ``"subreqs"`` — the comp has a child ``subreqs_*`` node whose
      pending draft is waiting on user approval. Only top-level
      comps own a subreqs child, so this kind only appears on
      top-level comps. Reported under the *owning comp's* id, not
      the subreqs node's id, because the dashboard surfaces this
      information per component.
    - ``"comparch"`` — the comp is top-level and has a pending
      draft targeting its own ``comp_*`` node. Populated once
      ``generate_comparch`` has landed a draft and is waiting on
      user review.
    - ``"subcomparch"`` — the comp is a subcomponent (``parent_id``
      points at another ``comp_*``) and has a pending draft
      targeting its own ``comp_*`` node. Populated once
      ``generate_subcomparch`` has landed a draft.

    A single comp is never in two states at once under normal
    bootstrap flow: subreqs approval triggers comparch, which
    triggers its subcomponents' subcomparch — each step's draft
    is discarded or approved before the next step's draft lands.
    If a regen fires in a weird order this function returns the
    **first** kind in the order ``subreqs > comparch >
    subcomparch`` for simplicity; callers shouldn't rely on
    seeing only one.

    Does not aggregate subtree state: a top-level comp whose
    *subcomponents* have pending subcomparch drafts is NOT marked
    here. The frontend does the aggregation if it wants
    "anything-below-me pending" semantics, because it also has
    the parent/child map handy.
    """
    result: dict[str, str] = {}

    # subreqs drafts — target_id is a subreqs_* node, we report
    # under the owning comp_* (its parent_id).
    subreqs_rows = session.execute(
        select(Draft, Node)
        .join(Node, Draft.target_id == Node.id)
        .where(
            Draft.project_id == project_id,
            Draft.status == "pending",
            Draft.target_type == "node",
            Node.tier == "subreqs",
            Node.parent_id.isnot(None),
        )
    ).all()
    for _draft, subreqs_node in subreqs_rows:
        if subreqs_node.parent_id is not None:
            result.setdefault(subreqs_node.parent_id, "subreqs")

    # comparch drafts — target_id is a comp_* node with parent_id IS NULL.
    comparch_rows = session.execute(
        select(Node.id)
        .join(Draft, Draft.target_id == Node.id)
        .where(
            Draft.project_id == project_id,
            Draft.status == "pending",
            Draft.target_type == "node",
            Node.tier == "comp",
            Node.parent_id.is_(None),
        )
    ).scalars()
    for comp_id in comparch_rows:
        result.setdefault(comp_id, "comparch")

    # subcomparch drafts — target_id is a comp_* node with parent_id NOT NULL.
    subcomparch_rows = session.execute(
        select(Node.id)
        .join(Draft, Draft.target_id == Node.id)
        .where(
            Draft.project_id == project_id,
            Draft.status == "pending",
            Draft.target_type == "node",
            Node.tier == "comp",
            Node.parent_id.isnot(None),
        )
    ).scalars()
    for sub_id in subcomparch_rows:
        result.setdefault(sub_id, "subcomparch")

    return result


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


def skeleton_snapshot(session: Session, project_id: str) -> dict:
    """Content-stripped projection snapshot for sharing with debuggers.

    Shape mirrors :func:`projection_snapshot` but replaces every
    content / prose field with its character length. Node names
    are kept (they're identifiers, not prose). Adds a
    ``recent_jobs`` section with the latest job per job_type
    and a short tail of the error string when the job failed,
    so someone reading the skeleton can see what's broken
    without needing the full log stream.

    The goal is "paste this to Claude to get help without leaking
    prose content." Every IDs / relationship / count / status
    that matters for debugging is preserved; every paragraph of
    user- or LLM-produced text is stripped to a number.
    """
    return {
        "nodes": [_node_skeleton(n) for n in list_nodes(session, project_id)],
        "edges": [_edge_dict(e) for e in list_edges(session, project_id)],
        "fragments": [_fragment_skeleton(f) for f in list_fragments(session, project_id)],
        "drafts": [_draft_skeleton(d) for d in list_drafts(session, project_id)],
        "recent_jobs": _recent_jobs_skeleton(session, project_id),
        "event_count": event_count(session, project_id),
        "latest_offset": latest_offset(session, project_id),
    }


def _node_skeleton(n: Node) -> dict:
    return {
        "id": n.id,
        "tier": n.tier,
        "kind": n.kind,
        "parent_id": n.parent_id,
        "name": n.name,  # names are identifiers, not prose
        "display_order": n.display_order,
        "content_length": len(n.content or ""),
    }


def _fragment_skeleton(f: Fragment) -> dict:
    return {
        "id": f.id,
        "owner_id": f.owner_id,
        "fragment_kind": f.fragment_kind,
        "content_length": len(f.content or ""),
    }


def _draft_skeleton(d: Draft) -> dict:
    return {
        "id": d.id,
        "target_type": d.target_type,
        "target_id": d.target_id,
        "status": d.status,
        "batch_id": d.batch_id,
        "content_length": len(d.content or ""),
    }


def _recent_jobs_skeleton(session: Session, project_id: str) -> list[dict]:
    """Return the most recent job per job_type with status + error tail.

    Jobs aren't scoped by a project column — filter by
    ``payload['project_id']`` like :func:`latest_generation_status`
    does. For each job_type the project has ever seen, return a
    single entry describing the latest instance. Failed jobs
    include a trailing slice of the error_message so the caller
    can see the symptom without the full log stream.
    """
    rows = session.execute(select(Job).order_by(Job.created_at.desc())).scalars().all()
    seen: set[str] = set()
    out: list[dict] = []
    for job in rows:
        if (job.payload or {}).get("project_id") != project_id:
            continue
        if job.job_type in seen:
            continue
        seen.add(job.job_type)
        entry: dict = {
            "job_type": job.job_type,
            "status": job.status,
            "retry_count": job.retry_count,
            "payload_keys": sorted((job.payload or {}).keys()),
        }
        if job.status == "failed" and job.error_message:
            tail = (job.error_message or "").strip()
            # Keep the last ~400 chars — enough to see the error
            # message + a bit of stack context without dumping
            # thousands of lines.
            entry["error_tail"] = tail[-400:]
        out.append(entry)
    out.sort(key=lambda e: e["job_type"])
    return out


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
    session: Session,
    project_id: str,
    job_type: str,
    payload_filters: dict | None = None,
) -> tuple[GenerationStatus, str | None, str | None, int | None, int | None, str | None]:
    """Derive a generation status from the latest job of ``job_type``.

    Returns ``(status, last_error, started_at_iso, current_attempt,
    max_attempts, failed_raw_output)``:

    * ``("idle", None, None, None, None, None)`` if no matching job
      exists, or the latest matching job ``completed`` or was
      ``cancelled`` (we treat cancellation as "back to idle" so the
      UI can return to the feedback / accept / reject state).
    * ``("running", None, started_at_iso, attempt?, max?, None)`` if
      the latest job is ``queued`` or ``running``. ``started_at_iso``
      is the job's ``created_at`` serialized to ISO-8601 (UTC, naive)
      so the client can render a duration clock off it.
      ``current_attempt`` / ``max_attempts`` are populated once the
      parse-validate loop has started writing them back onto the
      payload (see ``_record_attempt_progress`` in
      ``backend.graph.handlers._bootstrap_generation``); until then
      they are ``None`` (queued, or a non-bootstrap job type).
    * ``("failed", error, None, None, None, raw?)`` if the latest job
      is in a terminal-failure state. ``failed_raw_output`` is the
      last failed attempt's raw LLM text when the parse-validate
      loop exhausted (written by ``_record_failed_raw_output``);
      ``None`` for other failure modes (CLI crash before any
      attempt, transient errors that never produced text).

    ``payload_filters`` lets callers scope the lookup to jobs whose
    payload matches a set of key/value pairs — used by the per-
    component tiers (subreqs / comparch / subcomparch) so a running
    job for a different component doesn't bleed into the UI of the
    one the user is actually viewing.
    """
    filters = dict(payload_filters or {})
    filters.setdefault("project_id", project_id)
    rows = (
        session.execute(
            select(Job).where(Job.job_type == job_type).order_by(Job.created_at.desc()).limit(50)
        )
        .scalars()
        .all()
    )
    for job in rows:
        payload = job.payload or {}
        if any(payload.get(k) != v for k, v in filters.items()):
            continue
        if job.status in ("queued", "running"):
            started = job.created_at.isoformat() if job.created_at else None
            current_attempt_raw = payload.get("_current_attempt")
            max_attempts_raw = payload.get("_max_attempts")
            current_attempt = (
                int(current_attempt_raw) if isinstance(current_attempt_raw, int) else None
            )
            max_attempts = int(max_attempts_raw) if isinstance(max_attempts_raw, int) else None
            return "running", None, started, current_attempt, max_attempts, None
        if job.status == "failed":
            failed_raw = payload.get("_failed_raw_output")
            failed_raw_str = failed_raw if isinstance(failed_raw, str) else None
            return "failed", job.error_message, None, None, None, failed_raw_str
        if job.status == "cancelled":
            # Cancelled: fall through to idle so the UI returns to
            # the draft-review / empty state rather than "failed".
            return "idle", None, None, None, None, None
        # completed
        return "idle", None, None, None, None, None
    return "idle", None, None, None, None, None


# ── Phase 9: staleness ledger queries ────────────────────────────────


def is_stale(session: Session, project_id: str, node_id: str) -> bool:
    """Return True when ``node_id`` has any active staleness ledger rows.

    A node is "stale" if at least one upstream change has invalidated
    it since its last regen. Multiple reasons and multiple upstreams
    collapse to a single boolean here; use
    :func:`staleness_entries_for` when the full reason set matters.
    """
    return (
        session.execute(
            select(func.count()).select_from(
                select(StalenessLedger.id)
                .where(
                    StalenessLedger.project_id == project_id,
                    StalenessLedger.stale_node_id == node_id,
                )
                .subquery()
            )
        ).scalar()
        or 0
    ) > 0


def stale_dependents_of(session: Session, project_id: str, node_id: str) -> list[str]:
    """Return node ids currently stale w.r.t. ``node_id``.

    Reads ledger rows where ``source_node_id == node_id`` and returns
    the distinct dependents. Useful when the fanout module wants to
    inspect what an upstream change has invalidated, or when the UI
    shows "nodes waiting on this one to regenerate."
    """
    rows = (
        session.execute(
            select(StalenessLedger.stale_node_id)
            .where(
                StalenessLedger.project_id == project_id,
                StalenessLedger.source_node_id == node_id,
            )
            .distinct()
        )
        .scalars()
        .all()
    )
    return list(rows)


def staleness_entries_for(session: Session, project_id: str, node_id: str) -> list[StalenessLedger]:
    """Return every active staleness ledger row for ``node_id``.

    Full detail — one row per ``(source_node_id, reason)`` pair this
    node is stale against. The UI uses this to surface per-reason
    stale markers on the per-tier draft panel.
    """
    rows = (
        session.execute(
            select(StalenessLedger)
            .where(
                StalenessLedger.project_id == project_id,
                StalenessLedger.stale_node_id == node_id,
            )
            .order_by(StalenessLedger.created_at.asc())
        )
        .scalars()
        .all()
    )
    return list(rows)


# ── Phase 11: edge lookup + cycle detection on live projections ──────


def find_edge_by_endpoints(
    session: Session,
    project_id: str,
    edge_type: str,
    source_id: str,
    target_id: str,
) -> Edge | None:
    """Return the edge of ``edge_type`` between the two endpoints, if any.

    Used by the Phase 11 apply handler to resolve ``Remove*`` edge
    instructions to a concrete edge id for deletion.
    """
    return session.execute(
        select(Edge).where(
            Edge.project_id == project_id,
            Edge.edge_type == edge_type,
            Edge.source_id == source_id,
            Edge.target_id == target_id,
        )
    ).scalar_one_or_none()


def would_create_cycle(
    session: Session,
    project_id: str,
    source_id: str,
    target_id: str,
) -> list[str] | None:
    """Check if adding ``source_id → target_id`` closes a dependency cycle.

    DFS from ``target_id`` following outgoing ``dependency`` edges.
    Returns the cycle path ``[source_id, …, target_id, source_id]``
    if ``source_id`` is reachable from ``target_id``, otherwise
    ``None``. ``source_id == target_id`` is treated as a trivial
    self-cycle.

    The parser layer has its own cycle detection over LLM-authored
    aliases (``_detect_dep_cycles`` in ``parsers.validators``); this
    helper operates on live projection ids and is reused by the
    Phase 11 apply handler and the dependency editor's pre-check.
    """
    if source_id == target_id:
        return [source_id, target_id]

    adjacency: dict[str, list[str]] = {}
    rows = session.execute(
        select(Edge.source_id, Edge.target_id).where(
            Edge.project_id == project_id,
            Edge.edge_type == "dependency",
        )
    ).all()
    for src, tgt in rows:
        adjacency.setdefault(src, []).append(tgt)

    parent: dict[str, str] = {}
    stack: list[str] = [target_id]
    visited: set[str] = set()
    while stack:
        current = stack.pop()
        if current in visited:
            continue
        visited.add(current)
        if current == source_id:
            path: list[str] = [current]
            while path[-1] in parent:
                path.append(parent[path[-1]])
            path.reverse()
            return path + [target_id]
        for nxt in adjacency.get(current, ()):
            if nxt not in visited:
                parent[nxt] = current
                stack.append(nxt)
    return None
