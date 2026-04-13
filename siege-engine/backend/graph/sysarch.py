"""System-architecture (``sysarch_*``) node helpers.

The sysarch node is the third bootstrap doc in the v2 cold-start
chain. It takes the approved feature set (via ``feat_*``) and the
approved top-level responsibilities (via ``resp_*`` with
``parent_id=None``) and produces the full component graph:
top-level components with role summaries and API intent, top-level
policies, dependency edges, domain-parent edges, and a
system-level technical specification. Singleton per project.

On approval, the ``v2.mint_sysarch`` handler:

1. Mints one ``comp_*`` node per validated component entry with
   ``parent_id=None`` and stores the role + api-intent as
   ``comp_X_techspec`` / ``comp_X_pubapi`` fragments.
2. Mints one ``policy_*`` node per validated policy entry with
   the policy body stored in ``Node.content`` as an inline XML
   blob.
3. Emits ``decomposition`` edges from each top-level ``resp_*``
   to its assigned ``comp_*`` (the 1:1 resp→comp assignment;
   see §Feature → Responsibility → Component).
4. Emits ``dependency`` and ``domain_parent`` edges.
5. Writes a ``sysarch_X_techspec`` fragment with the system-level
   tech spec prose.
6. Bootstraps one ``subreqs_*`` node per top-level ``comp_*`` and
   enqueues its first generation job (Phase 3 stage 3 fan-out).

The sysarch node then becomes read-only; further changes land on
individual component arch docs (Phase 4) or via structural edit
UIs (Phase 11).

Shaped like :mod:`backend.graph.expansion` and
:mod:`backend.graph.requirements` — three helpers plus a
post-approval read-only check. Callers manage transaction
boundaries.

See ``docs/architecture/v2-rearchitecture.md`` §Generation order
and ``docs/architecture/v2-roadmap.md`` Phase 3.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.graph import events as ev
from backend.graph.ids import Kind, mint
from backend.graph.reducer import append_event
from backend.models.node import Draft, Node

SYSARCH_NODE_NAME = "System Architecture"
SYSARCH_TIER = "sysarch"


def bootstrap_sysarch_node(session: Session, project_id: str) -> str:
    """Mint the project's sysarch node and append ``NodeCreated``.

    Returns the newly-minted node id. Does **not** commit — the
    caller is responsible for transaction boundaries.
    """
    node_id = mint(session, Kind.SYSARCH)
    append_event(
        session,
        project_id,
        ev.NodeCreated(
            node_id=node_id,
            tier="sysarch",
            kind="domain",
            parent_id=None,
            name=SYSARCH_NODE_NAME,
        ),
    )
    return node_id


def get_sysarch_node(session: Session, project_id: str) -> Node | None:
    """Return the project's sysarch node, or ``None`` if missing."""
    return session.execute(
        select(Node).where(
            Node.project_id == project_id,
            Node.tier == SYSARCH_TIER,
        )
    ).scalar_one_or_none()


def pending_sysarch_draft(session: Session, project_id: str) -> Draft | None:
    """Return the pending draft targeting the project's sysarch node, or None."""
    node = get_sysarch_node(session, project_id)
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
    """Return True if the project's sysarch node has ever been approved.

    Same content-based detection as
    :func:`backend.graph.expansion.has_been_approved` and
    :func:`backend.graph.requirements.has_been_approved`: the
    reducer's ``DraftApproved`` branch is the only writer of
    ``Node.content``, so any non-empty content means at least one
    draft has been approved. MVP relies on this invariant.
    """
    node = get_sysarch_node(session, project_id)
    if node is None:
        return False
    return bool(node.content)
