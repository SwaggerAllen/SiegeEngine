"""Bespoke readiness predicates for tier-generation handlers.

Each predicate has signature ``(session, project_id, scope_ids) ->
(ready, reason)`` and is referenced from a tier's
:class:`backend.graph.handlers._tier_generation.TierGenerationConfig`
via the ``readiness_check`` slot.

These predicates replace the inline precondition checks in the
existing handler bodies (sysarch / comparch / subcomparch / impl).
The driver runs the predicate in a cheap DB session BEFORE the LLM
call, so a precondition failure costs nothing.

Each predicate returns a non-empty ``reason`` string when the gate
fails so the caller (driver) can surface it on the failed Job row.

A small ``all_of`` combinator composes predicates without inventing
a chain syntax — useful for Phase F where comparch's readiness is
``parent_subreqs_approved AND comparch_dep_comps_settled``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from backend.models.node import Node

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

ReadinessFn = Callable[["Session", str, tuple[str, ...]], tuple[bool, str]]


def all_of(*predicates: ReadinessFn) -> ReadinessFn:
    """Compose readiness predicates with short-circuit AND.

    Returns a predicate that runs each input in order and returns
    the first ``(False, reason)`` it sees, or ``(True, "")`` if all
    pass.
    """

    def combined(db: "Session", project_id: str, scope_ids: tuple[str, ...]) -> tuple[bool, str]:
        for predicate in predicates:
            ready, reason = predicate(db, project_id, scope_ids)
            if not ready:
                return (False, reason)
        return (True, "")

    return combined


def sysarch_node_exists(
    db: "Session",
    project_id: str,
    _scope_ids: tuple[str, ...],
) -> tuple[bool, str]:
    """Sysarch handler precondition: a sysarch node has been bootstrapped.

    Splits out the "no sysarch node" check from
    :func:`sysarch_has_top_level_resps` so callers can compose them
    with :func:`all_of` and get distinct error messages for each
    failure mode (the existing tests assert specifically on "no
    sysarch node" vs "no top-level responsibilities").
    """
    from backend.graph.sysarch import get_sysarch_node

    node = get_sysarch_node(db, project_id)
    if node is None:
        return (
            False,
            f"Project {project_id!r} has no sysarch node; was "
            "bootstrap_sysarch_node called at mint_requirements time?",
        )
    return (True, "")


def sysarch_has_top_level_resps(
    db: "Session",
    project_id: str,
    _scope_ids: tuple[str, ...],
) -> tuple[bool, str]:
    """Sysarch needs at least one top-level resp to decompose into components.

    Replaces the zero-resp fail-fast in
    ``sysarch_generation.py`` (today raises ``SysarchHandlerError``
    inside the handler body after gathering inputs). Lifting it
    here means the driver fails fast before opening a CLI session.

    Recoverable causes:
      (a) the requirements tier hasn't been approved yet,
      (b) a force-reset cleared the resp nodes and the reqs regen
          hasn't landed, or
      (c) the sysarch job was enqueued before reqs_mint's post-
          commit fan-out completed.

    All recoverable by the user approving reqs (or waiting for the
    in-flight mint).
    """
    has_resp = (
        db.query(Node.id)
        .filter(
            Node.project_id == project_id,
            Node.tier == "resp",
            Node.parent_id.is_(None),
        )
        .first()
    )
    if has_resp is None:
        return (
            False,
            "no top-level responsibilities exist yet. Sysarch decomposes "
            "reqs into components; with zero resps the validator cannot be "
            "satisfied. Approve the requirements draft first (or wait for "
            "the in-flight reqs_mint to complete) and retry.",
        )
    return (True, "")


def top_level_comp_exists(
    db: "Session",
    project_id: str,
    scope_ids: tuple[str, ...],
) -> tuple[bool, str]:
    """Comparch precondition: target node exists and is a top-level comp.

    Lifts the comp-existence / tier / top-level checks out of the
    handler body so the readiness gate fires before we attempt to
    walk the upstream context. Composed with
    :func:`parent_subreqs_approved` via :func:`all_of` on
    ``COMPARCH_CONFIG``.
    """
    if not scope_ids:
        return (False, "comparch readiness check missing component_id")
    component_id = scope_ids[0]
    comp_node = db.get(Node, component_id)
    if comp_node is None or comp_node.project_id != project_id:
        return (
            False,
            f"Component {component_id!r} not found in project {project_id!r}",
        )
    if comp_node.tier != "comp":
        return (
            False,
            f"Node {component_id!r} is not a comp_* node (tier={comp_node.tier!r})",
        )
    if comp_node.parent_id is not None:
        return (
            False,
            f"Component {component_id!r} is a subcomponent "
            f"(parent_id={comp_node.parent_id!r}). Comparch only runs "
            "on top-level components; subcomponent arch docs are "
            "Phase 5.",
        )
    return (True, "")


def wake_deferred_comparchs(
    db: "Session",
    project_id: str,
    _draft_id: str,
    scope_ids: tuple[str, ...],
) -> None:
    """Phase F: re-enqueue dependents whose blocking dep just settled.

    Wired into ``COMPARCH_CONFIG.post_persist_hooks``. Runs after a
    comparch lands. Walks the dependency graph for top-level comps
    that depend on the just-persisted comp AND have a job in the
    deferred-completed state (``Job.is_deferred=True``), then
    re-enqueues a fresh ``v2.generate_comparch`` for each. The
    freshly-claimed job's readiness predicate runs again; if the
    dep is now settled the regen proceeds, if not it defers again
    and the next persist picks it up.

    Idempotency: after re-enqueueing, the ``is_deferred`` flag is
    cleared on the consumed rows so subsequent wakeups don't
    re-fire on them. The pipeline_queue's payload-dedup against
    currently-queued jobs catches concurrent re-enqueues.
    """
    if not scope_ids:
        return
    just_persisted_comp_id = scope_ids[0]

    from sqlalchemy import select

    from backend.models.job import Job
    from backend.models.node import Edge
    from backend.pipeline import queue as pipeline_queue

    # Top-level dependents — comps with a dependency edge to the
    # just-persisted one. Edge direction: source depends on target.
    dependent_ids = (
        db.execute(
            select(Edge.source_id).where(
                Edge.project_id == project_id,
                Edge.edge_type == "dependency",
                Edge.target_id == just_persisted_comp_id,
            )
        )
        .scalars()
        .all()
    )
    if not dependent_ids:
        return
    top_level_dep_set = {
        row.id
        for row in db.execute(
            select(Node.id).where(
                Node.id.in_(dependent_ids),
                Node.project_id == project_id,
                Node.tier == "comp",
                Node.parent_id.is_(None),
            )
        ).all()
    }
    if not top_level_dep_set:
        return

    # Find deferred jobs for those dependents — typed flag rather
    # than fragile string discrimination on error_message.
    deferred_rows = (
        db.execute(
            select(Job).where(
                Job.job_type == "v2.generate_comparch",
                Job.is_deferred.is_(True),
            )
        )
        .scalars()
        .all()
    )
    woken: set[str] = set()
    for job in deferred_rows:
        payload = job.payload or {}
        if payload.get("project_id") != project_id:
            continue
        comp_id = payload.get("component_id")
        if comp_id not in top_level_dep_set:
            continue
        assert isinstance(comp_id, str)
        if comp_id in woken:
            # Multiple deferred markers for the same dependent —
            # clear all of them but only enqueue once.
            job.is_deferred = False
            continue
        woken.add(comp_id)
        pipeline_queue.enqueue(
            db,
            job_type="v2.generate_comparch",
            payload={
                "project_id": project_id,
                "component_id": comp_id,
                "feedback": None,
            },
        )
        job.is_deferred = False
    if woken:
        db.commit()


def comparch_dep_comps_settled(
    db: "Session",
    project_id: str,
    scope_ids: tuple[str, ...],
) -> tuple[bool, str]:
    """Phase F: comparch's dep comps must be settled before regen.

    "Settled" means: every dependency-edge target of this comp has
    approved comparch content AND no ``v2.generate_comparch`` job
    currently queued or running for that dep. If any dep's comparch
    is in flight, defer this regen so we generate against the
    up-to-date pubapi rather than the pre-update version.

    Composes with :func:`top_level_comp_exists` and
    :func:`parent_subreqs_approved` via :func:`all_of` on
    ``COMPARCH_CONFIG.readiness_check``.

    Raises :class:`TierDeferredError` (via the driver's
    ``readiness_check`` failure path) when a dep is mid-regen, so
    the worker completes the job without recording a failure and a
    wakeup hook re-enqueues when the dep settles.
    """
    from sqlalchemy import select

    from backend.models.job import Job
    from backend.models.node import Edge

    if not scope_ids:
        return (False, "comparch readiness check missing component_id")
    component_id = scope_ids[0]

    # Find dep targets — edges where this comp is the source and the
    # edge type is "dependency". Direction: source depends on target.
    dep_edges = (
        db.execute(
            select(Edge.target_id).where(
                Edge.project_id == project_id,
                Edge.edge_type == "dependency",
                Edge.source_id == component_id,
            )
        )
        .scalars()
        .all()
    )
    if not dep_edges:
        return (True, "")

    # Restrict to top-level comps — sub-deps don't count for this
    # gate. Any non-comp targets (defensive) are ignored.
    dep_node_rows = (
        db.execute(
            select(Node.id, Node.content, Node.parent_id, Node.tier).where(
                Node.id.in_(dep_edges),
                Node.project_id == project_id,
            )
        )
    ).all()
    top_level_dep_ids = {
        row.id for row in dep_node_rows if row.tier == "comp" and row.parent_id is None
    }
    if not top_level_dep_ids:
        return (True, "")

    # Defer only when a dep has an in-flight v2.generate_comparch
    # job. "No approved content yet" by itself doesn't defer — that
    # would deadlock the initial bootstrap (no comparch has approved
    # content at first; everything would defer waiting for everyone
    # else). The gate exists for the regen-cascade case: dep B has
    # approved content AND an in-flight regen will replace it; A
    # depending on B should wait.
    in_flight_jobs = db.execute(
        select(Job.id, Job.payload).where(
            Job.job_type == "v2.generate_comparch",
            Job.status.in_(("queued", "running")),
        )
    ).all()
    in_flight_dep_ids = {
        row.payload.get("component_id")
        for row in in_flight_jobs
        if row.payload
        and row.payload.get("component_id") in top_level_dep_ids
        and row.payload.get("project_id") == project_id
        # Don't defer because of THIS comp's own running job (the
        # one whose readiness we're currently evaluating).
        and row.payload.get("component_id") != component_id
    }
    if in_flight_dep_ids:
        return (
            False,
            f"deferred — comparch dep(s) {sorted(in_flight_dep_ids)!r} "
            "have an in-flight regen. Will retry after they settle.",
        )

    return (True, "")


def parent_subreqs_approved(
    db: "Session",
    project_id: str,
    scope_ids: tuple[str, ...],
) -> tuple[bool, str]:
    """Comparch precondition: this component's subreqs has approved content.

    ``scope_ids = (component_id,)``. Replaces the inline check in
    ``comparch_generation.py`` (today raises
    ``ComparchPreconditionError``). The subreqs node has non-empty
    content only after DraftApproved has landed, so "content is
    non-empty" == "approved."
    """
    from backend.graph.subrequirements import get_subreqs_node

    if not scope_ids:
        return (False, "comparch readiness check missing component_id")
    component_id = scope_ids[0]
    subreqs_node = get_subreqs_node(db, project_id, component_id)
    if subreqs_node is None or not (subreqs_node.content or "").strip():
        return (
            False,
            f"Comparch generation for {component_id!r} blocked — its "
            "owning subreqs_* has not been approved yet. Approve the "
            "component's subrequirements first.",
        )
    return (True, "")


def subcomp_node_exists(
    db: "Session",
    project_id: str,
    scope_ids: tuple[str, ...],
) -> tuple[bool, str]:
    """Subcomparch precondition: target node exists, comp tier, has a comp parent.

    Lifts the structural checks out of the handler body so the
    readiness gate fires before context-gather. Composed with
    :func:`parent_comparch_approved` via :func:`all_of` on
    ``SUBCOMPARCH_CONFIG``.
    """
    if not scope_ids:
        return (False, "subcomparch readiness check missing component_id")
    sub_id = scope_ids[0]
    sub_node = db.get(Node, sub_id)
    if sub_node is None or sub_node.project_id != project_id:
        return (
            False,
            f"Component {sub_id!r} not found in project {project_id!r}",
        )
    if sub_node.tier != "comp":
        return (
            False,
            f"Node {sub_id!r} is not a comp_* node (tier={sub_node.tier!r})",
        )
    if sub_node.parent_id is None:
        return (
            False,
            f"Component {sub_id!r} is a top-level component "
            "(parent_id is None). Subcomparch only runs on "
            "subcomponents; top-level comparch is Phase 4.",
        )
    parent_node = db.get(Node, sub_node.parent_id)
    if parent_node is None or parent_node.tier != "comp":
        return (
            False,
            f"Subcomponent {sub_id!r} has parent_id {sub_node.parent_id!r} "
            "which is not a comp_* node",
        )
    return (True, "")


def parent_comparch_approved(
    db: "Session",
    project_id: str,
    scope_ids: tuple[str, ...],
) -> tuple[bool, str]:
    """Subcomparch precondition: parent component's comparch is approved.

    ``scope_ids = (subcomponent_id,)``. Composes with
    :func:`subcomp_node_exists` via :func:`all_of` so the structural
    checks fire first and produce the right error messages.
    """
    if not scope_ids:
        return (False, "subcomparch readiness check missing component_id")
    sub_id = scope_ids[0]
    sub_node = db.get(Node, sub_id)
    # Subcomp existence is gated by subcomp_node_exists in the
    # composed predicate; here we assume the structural checks have
    # already passed and fail loudly if not (defensive).
    if sub_node is None or sub_node.parent_id is None:
        return (False, f"Subcomponent {sub_id!r} state invalid")
    parent_node = db.get(Node, sub_node.parent_id)
    if parent_node is None:
        return (False, f"Parent of subcomponent {sub_id!r} not found")
    if not (parent_node.content or "").strip():
        return (
            False,
            f"Subcomparch generation for {sub_id!r} blocked — its parent "
            f"component {parent_node.id!r} has no approved comparch content. "
            "Approve the parent's architecture doc first.",
        )
    return (True, "")


def owner_node_exists(
    db: "Session",
    project_id: str,
    scope_ids: tuple[str, ...],
) -> tuple[bool, str]:
    """Impl precondition: the owner comp exists in the project.

    ``scope_ids = (owner_id,)``. Composes with
    :func:`owner_arch_approved` via :func:`all_of` so the structural
    check fires first.
    """
    if not scope_ids:
        return (False, "impl readiness check missing owner_id")
    owner_id = scope_ids[0]
    owner_node = db.get(Node, owner_id)
    if owner_node is None or owner_node.project_id != project_id:
        return (
            False,
            f"Owner component {owner_id!r} not found in project {project_id!r}",
        )
    if owner_node.tier != "comp":
        return (
            False,
            f"Owner {owner_id!r} is not a comp_* node (tier={owner_node.tier!r})",
        )
    return (True, "")


def owner_arch_approved(
    db: "Session",
    project_id: str,
    scope_ids: tuple[str, ...],
) -> tuple[bool, str]:
    """Impl precondition: the owner's arch doc is approved.

    ``scope_ids = (owner_id,)`` where ``owner_id`` is the comp the
    impl is implementing. Composes with :func:`owner_node_exists`
    via :func:`all_of` so the structural check fires first; this
    predicate assumes the owner exists and is a comp tier.
    """
    if not scope_ids:
        return (False, "impl readiness check missing owner_id")
    owner_id = scope_ids[0]
    owner_node = db.get(Node, owner_id)
    if owner_node is None:
        return (False, f"Owner {owner_id!r} not found")
    if not (owner_node.content or "").strip():
        return (
            False,
            f"Impl generation for owner {owner_id!r} blocked — its "
            "architecture doc (comparch / subcomparch) has not yet been "
            "approved. Approve the arch doc first.",
        )
    return (True, "")
