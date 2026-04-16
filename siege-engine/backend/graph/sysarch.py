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


# ── Destructive reset ─────────────────────────────────────────────────

# Tier names for every node that can exist downstream of sysarch
# approval. Anything with a tier in this set is fair game for the
# destructive reset walker to delete. Upstream tiers (feat, top-level
# resp, reqs, expansion, sysarch itself) are *never* in this set —
# they survive the reset so the user can regen sysarch against the
# same upstream state.
#
# Note that ``resp`` is deliberately absent: top-level responsibilities
# (``parent_id IS NULL``) are upstream of sysarch and must survive.
# Sub-responsibilities (``parent_id`` set to a ``comp_*`` id) live in
# the ``resp`` tier too but are downstream of sysarch mint + subreqs
# mint, so the reset walker queries them with an explicit parent_id
# filter rather than by tier alone.
_DOWNSTREAM_OF_SYSARCH_TIERS: tuple[str, ...] = (
    "comp",
    "policy",
    "subreqs",
    "impl",
    "plan",
    "manifest",
    "fanin",
)

# Queued job types to cancel when the reset runs. Everything that
# downstream of ``v2.generate_sysarch`` in the pipeline: the sysarch
# mint, subrequirements + comparch + subcomparch generation and mint
# jobs, and the two policy-application tiers. ``v2.generate_sysarch``
# itself is also cancelled — the reset route enqueues a fresh one
# afterward and we don't want a stale pre-reset job running against
# the new state.
_DOWNSTREAM_JOB_TYPES: tuple[str, ...] = (
    "v2.generate_sysarch",
    "v2.mint_sysarch",
    "v2.generate_subrequirements",
    "v2.mint_subrequirements",
    "v2.generate_comparch",
    "v2.mint_comparch",
    "v2.generate_subcomparch",
    "v2.mint_subcomparch",
    "v2.apply_top_level_policies",
    "v2.apply_component_local_policies",
)


def collect_downstream_nodes(session: Session, project_id: str) -> list[Node]:
    """Return every projection node that was minted downstream of
    the project's sysarch approval.

    Covers:

    * Every node with a tier in :data:`_DOWNSTREAM_OF_SYSARCH_TIERS`
      (top-level components, subcomponents, top-level + local
      policies, subreqs nodes, any impl / plan / manifest / fanin
      nodes if they exist yet).
    * Every ``resp_*`` node with a non-null ``parent_id`` — those
      are sub-responsibilities minted by ``subreqs_mint`` under a
      component, distinct from the top-level resps that survive.

    Order is unspecified. The reset route emits ``NodeDeleted``
    events for each node; the reducer handles each deletion
    independently, and DB-level ``ON DELETE CASCADE`` on the
    fragment + edge tables takes care of owned fragments and
    touching edges automatically.
    """
    from sqlalchemy import or_

    tier_query = select(Node).where(
        Node.project_id == project_id,
        Node.tier.in_(_DOWNSTREAM_OF_SYSARCH_TIERS),
    )
    nested_resp_query = select(Node).where(
        Node.project_id == project_id,
        Node.tier == "resp",
        Node.parent_id.is_not(None),
    )
    # Two separate queries rather than a single OR because the tier
    # filter is a clean inclusion test and the resp-with-parent
    # filter is a specific carve-out; keeping them separate makes
    # the intent obvious to a reader and lets each query hit its
    # natural index.
    _ = or_  # kept imported in case a future rewrite merges them
    return [
        *session.execute(tier_query).scalars().all(),
        *session.execute(nested_resp_query).scalars().all(),
    ]


def collect_pending_drafts_for_nodes(
    session: Session, project_id: str, node_ids: list[str]
) -> list[Draft]:
    """Return every pending draft that targets a node in ``node_ids``
    or a fragment owned by one of those nodes.

    Drafts have no foreign key on ``target_id`` (the column is a
    plain string that can point at either a node id or a fragment
    id), so deleting a node via the reducer leaves orphaned
    pending drafts pointing at the now-deleted target. This helper
    finds them so the reset route can emit ``DraftDiscarded`` for
    each before the ``NodeDeleted`` cascade fires.

    The returned list includes drafts targeting *fragments* owned
    by the to-be-deleted nodes, because fragment drafts are what
    Phase 4+ tiers (comparch's pubapi / techspec fragments) regen
    against, and if left pending they'd be orphaned the same way.
    """
    if not node_ids:
        return []
    from backend.models.node import Fragment

    drafts: list[Draft] = []
    # Direct node drafts.
    drafts.extend(
        session.execute(
            select(Draft).where(
                Draft.project_id == project_id,
                Draft.target_type == "node",
                Draft.target_id.in_(node_ids),
                Draft.status == "pending",
            )
        )
        .scalars()
        .all()
    )
    # Fragment drafts whose owner is one of the to-be-deleted nodes.
    fragment_ids = (
        session.execute(
            select(Fragment.id).where(
                Fragment.project_id == project_id,
                Fragment.owner_id.in_(node_ids),
            )
        )
        .scalars()
        .all()
    )
    if fragment_ids:
        drafts.extend(
            session.execute(
                select(Draft).where(
                    Draft.project_id == project_id,
                    Draft.target_type == "fragment",
                    Draft.target_id.in_(fragment_ids),
                    Draft.status == "pending",
                )
            )
            .scalars()
            .all()
        )
    return drafts
