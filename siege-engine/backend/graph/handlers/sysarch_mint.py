"""System-architecture minting handler.

Registered on the pipeline job queue as ``v2.mint_sysarch``.
Triggered by the sysarch approve route after a ``DraftApproved``
event has committed the approved sysarch content to the sysarch
node. The handler parses that content, validates it (re-running
the same validator the generation pass used, which catches resp
drift between generation and mint), and emits every downstream
structural event in a single transaction.

Flow:

1. Open a DB session. Look up the sysarch node's current content
   and the set of known top-level ``resp_*`` IDs.
2. **Idempotency check:** if any top-level ``comp_*`` nodes
   already exist in this project (``tier=comp AND parent_id IS
   NULL``), log and return. Handles crash-recovery replays.
3. Parse + validate the approved content via
   :func:`validate_sysarch`.
4. **Phase 1 — mint components.** One ``NodeCreated`` per
   ``Component``, with ``tier="comp"``, ``kind`` per the
   validated entry, ``parent_id=None`` (top-level),
   ``name`` = display name, ``display_order`` = position in
   the components list, and ``content=""`` (role and api-intent
   live in fragments). Build an ``alias → comp_id`` map.
5. **Phase 2 — component fragments.** For each new comp_*,
   emit one ``FragmentUpdated`` per fragment kind: ``techspec``
   (the role paragraph) and ``pubapi`` (the api-intent paragraph).
   These are skeletal placeholders; Phase 4 comparch replaces
   them with full content.
6. **Phase 3 — resp → comp decomposition edges.** For each
   component's ``resp_refs``, emit ``EdgeCreated`` with
   ``edge_type="decomposition"``, ``source_id=resp_id``,
   ``target_id=comp_id``. This is the top-level 1:1 resp→comp
   assignment, implemented as edges (not ``parent_id``) so
   subresps can later use ``parent_id=comp_id`` for structural
   containment without collision.
7. **Phase 4 — sysarch techspec fragment.** Write the
   ``<techspec>`` section text to the ``sysarch_X_techspec``
   fragment via ``FragmentUpdated``.
8. **Phase 5 — mint policies.** One ``NodeCreated`` per
   ``Policy``, with ``tier="policy"``, ``kind="domain"``
   (convention — the field is tier-structural, policies aren't
   really either kind), ``parent_id=None``,
   ``name=policy.name``, and ``content`` set to an inline
   ``<policy>`` XML blob carrying trigger / required / rationale.
9. **Phase 6 — dependency edges.** Translate each ``DepEdge``'s
   aliases to real comp_* IDs, mint an ``edge_*`` ID, emit
   ``EdgeCreated(edge_type="dependency")``.
10. **Phase 7 — domain-parent edges.** Same shape with
    ``edge_type="domain_parent"``.
11. Commit the whole transaction.
12. **Phase 8 — subreqs bootstrap fan-out (post-commit).** For
    each top-level comp_*, bootstrap a ``subreqs_*`` node with
    ``parent_id=comp_id`` and enqueue
    ``v2.generate_subrequirements``. The fan-out happens after
    the main commit so a transient enqueue failure doesn't roll
    back the mint; a missing subreqs node can be lazy-
    bootstrapped later.

The mint handler does **not** run an LLM call. It is
deterministic and idempotent. Parse/validate failures are a bug
state because generation already ran its own parse-validate
loop with the same check.

See ``docs/architecture/v2-roadmap.md`` Phase 3.
"""

from __future__ import annotations

import logging

from backend.database import SessionLocal
from backend.graph import events as ev
from backend.graph.broadcast import commit_and_publish
from backend.graph.fragments import FragmentKind, fragment_id
from backend.graph.ids import Kind, mint
from backend.graph.parsers.validators import (
    Policy,
    ValidationError,
    format_component_pubapi,
    format_component_techspec,
    format_techspec_fragment,
    validate_sysarch,
)
from backend.graph.parsers.xml_sections import ParseError, extract_tag_tree
from backend.graph.reducer import append_event
from backend.graph.sysarch import get_sysarch_node
from backend.models.node import Node
from backend.pipeline import queue as pipeline_queue

logger = logging.getLogger(__name__)

MINT_SYSARCH_JOB_TYPE = "v2.mint_sysarch"

# String — avoids circular import with subreqs_generation. We just
# need the job type name to enqueue fan-out jobs; the handler
# registration is in a different module.
_GENERATE_COMPARCH_JOB_TYPE = "v2.generate_comparch"


class SysarchMintHandlerError(RuntimeError):
    """Raised when the mint handler cannot proceed."""


def _serialize_policy_blob(p: Policy) -> str:
    """Render a :class:`Policy` as an inline ``<policy>`` XML blob.

    This is the string stored on the minted ``policy_*`` node's
    ``content`` column. Comparch (Phase 4) re-parses it via
    :func:`validate_policy_blob` when deciding applicability.

    Phase-11 followup B8: universal-scope policies have
    ``required_resp_id is None`` and emit no ``<required>``
    child at all (as opposed to an empty tag). The validator
    accepts both forms; omission is the canonical rendering.
    """
    parts = ["<policy>", f"<name>{p.name}</name>", f"<trigger>{p.trigger}</trigger>"]
    if p.required_resp_id is not None:
        parts.append(f"<required>{p.required_resp_id}</required>")
    parts.append(f"<rationale>{p.rationale}</rationale>")
    parts.append("</policy>")
    return "".join(parts)


async def mint_sysarch(payload: dict) -> None:
    """Job handler for ``v2.mint_sysarch``.

    Payload shape: ``{"project_id": str}``.
    """
    project_id = payload.get("project_id")
    if not isinstance(project_id, str) or not project_id:
        raise SysarchMintHandlerError("mint_sysarch payload missing project_id")

    db = SessionLocal()
    try:
        node = get_sysarch_node(db, project_id)
        if node is None:
            raise SysarchMintHandlerError(
                f"Project {project_id!r} has no sysarch node; "
                "was mint_sysarch enqueued before bootstrap?"
            )
        content = node.content or ""
        if not content.strip():
            raise SysarchMintHandlerError(
                f"Project {project_id!r} sysarch node has empty content; "
                "was mint_sysarch enqueued before DraftApproved?"
            )
        sysarch_node_id: str = node.id

        # Known top-level resp IDs for the validator cross-check.
        known_top_level_resp_ids: set[str] = {
            rid
            for (rid,) in db.query(Node.id)
            .filter(
                Node.project_id == project_id,
                Node.tier == "resp",
                Node.parent_id.is_(None),
            )
            .all()
        }

        # Idempotency: skip if any top-level comp_* already exist.
        existing_top_level_comps = (
            db.query(Node)
            .filter(
                Node.project_id == project_id,
                Node.tier == "comp",
                Node.parent_id.is_(None),
            )
            .count()
        )
        if existing_top_level_comps > 0:
            logger.info(
                "mint_sysarch project=%s skipped (already has %d top-level comp_* nodes)",
                project_id,
                existing_top_level_comps,
            )
            return

        try:
            tree = extract_tag_tree(content, "sysarch")
            doc = validate_sysarch(tree, known_top_level_resp_ids=known_top_level_resp_ids)
        except (ParseError, ValidationError) as exc:
            raise SysarchMintHandlerError(
                f"mint_sysarch project={project_id} could not parse approved sysarch content: {exc}"
            ) from exc

        # ── Phase 1: mint comp_* nodes ──────────────────────────
        alias_to_comp_id: dict[str, str] = {}
        minted_comp_ids: list[str] = []
        for index, component in enumerate(doc.components):
            comp_id = mint(db, Kind.COMP)
            append_event(
                db,
                project_id,
                ev.NodeCreated(
                    node_id=comp_id,
                    tier="comp",
                    kind=component.kind,
                    parent_id=None,
                    name=component.name,
                    display_order=index,
                    # ``content`` stays empty — the platform-wide signal
                    # for "this node's downstream tier has not landed
                    # yet" (see :func:`backend.graph.fanout._has_approved_content`).
                    # The sysarch-level ``<failure-surface>`` is enforced
                    # at validate time and read by the sysarch AI review
                    # from the draft content; it does not need a
                    # per-comp persistence slot yet. A comparch
                    # `<failure-surface>` in its own fragment is the
                    # downstream home if / when this signal needs to
                    # propagate past sysarch review.
                    content="",
                    is_foundation=component.is_foundation,
                ),
            )
            alias_to_comp_id[component.alias] = comp_id
            minted_comp_ids.append(comp_id)

            # ── Phase 2: per-comp fragments ─────────────────────
            # Techspec fragment = formatted purpose + owned-invariants.
            # Pubapi fragment = formatted primary-operations. Both are
            # skeletal — Phase 4 comparch replaces them with real content.
            techspec_fid = fragment_id(comp_id, FragmentKind.TECHSPEC)
            append_event(
                db,
                project_id,
                ev.FragmentUpdated(
                    fragment_id=techspec_fid,
                    owner_id=comp_id,
                    fragment_kind=FragmentKind.TECHSPEC,
                    new_content=format_component_techspec(component),
                ),
            )
            pubapi_fid = fragment_id(comp_id, FragmentKind.PUBAPI)
            append_event(
                db,
                project_id,
                ev.FragmentUpdated(
                    fragment_id=pubapi_fid,
                    owner_id=comp_id,
                    fragment_kind=FragmentKind.PUBAPI,
                    new_content=format_component_pubapi(component),
                ),
            )

            # ── Phase 3: resp → comp decomposition edges ────────
            # Every top-level resp assigned to this component gets
            # a decomposition edge. Direction is upstream →
            # downstream matching the existing feat→resp convention.
            for resp_id in component.resp_refs:
                edge_id = mint(db, Kind.EDGE)
                append_event(
                    db,
                    project_id,
                    ev.EdgeCreated(
                        edge_id=edge_id,
                        edge_type="decomposition",
                        source_id=resp_id,
                        target_id=comp_id,
                    ),
                )

        # ── Phase 4: sysarch techspec fragment ──────────────────
        sysarch_techspec_fid = fragment_id(sysarch_node_id, FragmentKind.TECHSPEC)
        append_event(
            db,
            project_id,
            ev.FragmentUpdated(
                fragment_id=sysarch_techspec_fid,
                owner_id=sysarch_node_id,
                fragment_kind=FragmentKind.TECHSPEC,
                new_content=format_techspec_fragment(doc.techspec),
            ),
        )

        # ── Phase 5: mint policy_* nodes ────────────────────────
        minted_policy_ids: list[str] = []
        for index, policy in enumerate(doc.policies):
            policy_id = mint(db, Kind.POLICY)
            append_event(
                db,
                project_id,
                ev.NodeCreated(
                    node_id=policy_id,
                    tier="policy",
                    kind="domain",
                    parent_id=None,
                    name=policy.name,
                    display_order=index,
                    content=_serialize_policy_blob(policy),
                ),
            )
            minted_policy_ids.append(policy_id)

        # ── Phase 6: dependency edges ───────────────────────────
        for dep in doc.deps:
            from_comp_id = alias_to_comp_id[dep.from_alias]
            to_comp_id = alias_to_comp_id[dep.to_alias]
            edge_id = mint(db, Kind.EDGE)
            append_event(
                db,
                project_id,
                ev.EdgeCreated(
                    edge_id=edge_id,
                    edge_type="dependency",
                    source_id=from_comp_id,
                    target_id=to_comp_id,
                ),
            )

        # ── Phase 7: domain-parent edges ────────────────────────
        for dp in doc.domain_parents:
            from_comp_id = alias_to_comp_id[dp.from_alias]
            to_comp_id = alias_to_comp_id[dp.to_alias]
            edge_id = mint(db, Kind.EDGE)
            append_event(
                db,
                project_id,
                ev.EdgeCreated(
                    edge_id=edge_id,
                    edge_type="domain_parent",
                    source_id=from_comp_id,
                    target_id=to_comp_id,
                ),
            )

        # commit_and_publish so the NodeCreated events for comp_* /
        # policy_* broadcast over SSE and the sidebar + Components
        # tab update without a manual refresh (B1).
        commit_and_publish(db, project_id)

        # Enqueue comparch generation directly per top-level comp
        # post-commit. The subreqs tier is gone; comparch is the
        # immediate next stage and reads parent resps + their feat
        # tags directly via regen_context.
        for comp_id in minted_comp_ids:
            pipeline_queue.enqueue(
                db,
                job_type=_GENERATE_COMPARCH_JOB_TYPE,
                payload={
                    "project_id": project_id,
                    "component_id": comp_id,
                    "feedback": None,
                },
            )

        logger.info(
            "mint_sysarch project=%s minted %d comp_* nodes, %d policy_* nodes; "
            "deps=%d domain_parents=%d",
            project_id,
            len(minted_comp_ids),
            len(minted_policy_ids),
            len(doc.deps),
            len(doc.domain_parents),
        )
    finally:
        db.close()


def register() -> None:
    """Register the handler with the pipeline job queue."""
    pipeline_queue.register_handler(MINT_SYSARCH_JOB_TYPE, mint_sysarch)
