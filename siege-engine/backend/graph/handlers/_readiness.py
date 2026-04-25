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
