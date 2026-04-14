"""Component architecture (comparch) mint handler.

Registered on the pipeline job queue as ``v2.mint_comparch``.
Triggered by the comparch approve route after ``DraftApproved``
commits the approved arch doc content to the comp_* node.

The arch doc is parsed and re-validated (same validator that
ran during generation) and projected into the event stream as:

1. ``FragmentUpdated`` × 5 — one per fragment section
   (techspec, pubapi, privapi, policies, deps). These overwrite
   the skeletal fragments sysarch_mint wrote at top-level-comp
   creation time with the full comparch-produced content.
2. ``NodeCreated`` per subcomponent in ``<subcomponents>`` —
   minted as ``comp_*`` with ``parent_id=<owning comp>``,
   ``kind`` inherited from the owning comp, plus skeletal
   ``comp_X_techspec`` / ``comp_X_pubapi`` fragments seeded
   from the subcomponent's ``role`` and ``api-intent`` (Phase
   5 subcomponent arch doc generation will replace these with
   real content).
3. ``EdgeCreated(edge_type='decomposition')`` per subresp
   reference in a subcomponent's ``<responsibilities>`` block —
   links the pre-minted subresp to its owning subcomponent.
4. ``NodeCreated`` per entry in ``<policies>`` — mints a
   ``policy_*`` with ``parent_id=<owning comp>`` and the
   inline ``<policy>`` XML blob as content (reusing the
   ``_serialize_policy_blob`` helper from sysarch_mint).
5. ``EdgeCreated(edge_type='dependency')`` per entry in
   ``<dependencies>`` — external dep, source is the owning
   comp, target is the sibling comp_id from the XML.
6. ``EdgeCreated(edge_type='dependency')`` per entry in
   ``<sub-dependencies>`` — internal dep between subcomponents,
   with aliases resolved to the newly-minted sub comp IDs.

Commit the whole transaction. **Post-commit**, enqueue the
policy application jobs:

- ``v2.apply_top_level_policies`` with ``{project_id, component_id}``
- ``v2.apply_component_local_policies`` with ``{project_id, component_id}``

These run after mint because the application passes need the
component's techspec + pubapi + subresps to exist and be readable.

Idempotency: skip (return without work) if any subcomponent
``comp_*`` with ``parent_id=<owning comp>`` already exists. The
reducer's unique constraints would catch duplicate mints anyway
but the explicit check avoids event-log noise on crash-recovery
replays.

See ``docs/architecture/v2-roadmap.md`` Phase 4.
"""

from __future__ import annotations

import logging

from backend.database import SessionLocal
from backend.graph import events as ev
from backend.graph.fragments import FragmentKind, fragment_id
from backend.graph.handlers.sysarch_mint import _serialize_policy_blob
from backend.graph.ids import Kind, mint
from backend.graph.parsers.validators import ValidationError, validate_arch_doc
from backend.graph.parsers.xml_sections import ParseError, extract_tag_tree
from backend.graph.queries import (
    list_subresponsibilities,
    list_top_level_components,
    top_level_resps_assigned_to,
)
from backend.graph.reducer import append_event
from backend.models.node import Node
from backend.pipeline import queue as pipeline_queue

logger = logging.getLogger(__name__)

MINT_COMPARCH_JOB_TYPE = "v2.mint_comparch"

# Post-commit fan-out job types. String constants so we don't
# create circular imports with the policy_application handlers
# (those modules import validators from the same package).
_APPLY_TOP_LEVEL_POLICIES_JOB = "v2.apply_top_level_policies"
_APPLY_COMPONENT_LOCAL_POLICIES_JOB = "v2.apply_component_local_policies"
_GENERATE_SUBCOMPARCH_JOB = "v2.generate_subcomparch"


class ComparchMintHandlerError(RuntimeError):
    """Raised when the mint handler cannot proceed."""


async def mint_comparch(payload: dict) -> None:
    """Job handler for ``v2.mint_comparch``.

    Payload: ``{"project_id": str, "component_id": str}``.
    """
    project_id = payload.get("project_id")
    component_id = payload.get("component_id")
    if not isinstance(project_id, str) or not project_id:
        raise ComparchMintHandlerError("mint_comparch payload missing project_id")
    if not isinstance(component_id, str) or not component_id:
        raise ComparchMintHandlerError("mint_comparch payload missing component_id")

    db = SessionLocal()
    try:
        comp_node = db.get(Node, component_id)
        if comp_node is None or comp_node.project_id != project_id:
            raise ComparchMintHandlerError(
                f"Component {component_id!r} not found in project {project_id!r}"
            )
        if comp_node.tier != "comp":
            raise ComparchMintHandlerError(
                f"Node {component_id!r} is not a comp_* node (tier={comp_node.tier!r})"
            )
        if comp_node.parent_id is not None:
            raise ComparchMintHandlerError(
                f"Component {component_id!r} is a subcomponent; comparch is top-level only."
            )
        content = comp_node.content or ""
        if not content.strip():
            raise ComparchMintHandlerError(
                f"Component {component_id!r} has empty content; was "
                "mint_comparch enqueued before DraftApproved?"
            )

        # Idempotency: any existing subcomponents means we've
        # already processed this mint. The reducer's unique
        # constraint on (project_id, node_id) would reject a
        # duplicate NodeCreated anyway, but explicit-return is
        # cleaner for crash-recovery replays.
        existing_subcomps = (
            db.query(Node)
            .filter(
                Node.project_id == project_id,
                Node.tier == "comp",
                Node.parent_id == component_id,
            )
            .count()
        )
        if existing_subcomps > 0:
            logger.info(
                "mint_comparch project=%s comp=%s skipped (already has %d subcomponents)",
                project_id,
                component_id,
                existing_subcomps,
            )
            return

        # Rebuild the known-ID sets the validator needs. These are
        # the same sets the generation handler used, but we read
        # them fresh from the DB to catch any drift between
        # generation and approval (e.g., if a sibling comp was
        # renamed or a subresp was deleted post-generation).
        parent_resp_rows = top_level_resps_assigned_to(db, component_id)
        subresp_rows = list_subresponsibilities(db, component_id)
        known_subresp_ids: set[str] = {r.id for r in subresp_rows}
        siblings = [c for c in list_top_level_components(db, project_id) if c.id != component_id]
        known_sibling_comp_ids: set[str] = {c.id for c in siblings}
        known_resp_ids_for_policies: set[str] = {r.id for r in parent_resp_rows} | known_subresp_ids

        try:
            tree = extract_tag_tree(content, "comparch")
            doc = validate_arch_doc(
                tree,
                known_subresp_ids=known_subresp_ids,
                known_sibling_comp_ids=known_sibling_comp_ids,
                known_resp_ids_for_policies=known_resp_ids_for_policies,
                target_is_foundation=bool(comp_node.is_foundation),
            )
        except (ParseError, ValidationError) as exc:
            raise ComparchMintHandlerError(
                f"mint_comparch project={project_id} comp={component_id} "
                f"could not parse approved arch doc: {exc}"
            ) from exc

        # ── Phase 1: fragment projection ────────────────────────
        _emit_fragment(db, project_id, component_id, FragmentKind.TECHSPEC, doc.techspec)
        _emit_fragment(db, project_id, component_id, FragmentKind.PUBAPI, doc.pubapi)
        _emit_fragment(db, project_id, component_id, FragmentKind.PRIVAPI, doc.privapi)
        # The policies and deps sections are stored as their raw
        # XML content in their fragment — serialize the tuples
        # back to XML for the fragment body so downstream readers
        # can re-parse them if needed.
        policies_fragment_body = _serialize_policies_fragment(doc.policies)
        deps_fragment_body = _serialize_deps_fragment(doc.external_deps)
        _emit_fragment(db, project_id, component_id, FragmentKind.POLICIES, policies_fragment_body)
        _emit_fragment(db, project_id, component_id, FragmentKind.DEPS, deps_fragment_body)

        # ── Phase 2: subcomponent minting ───────────────────────
        alias_to_sub_id: dict[str, str] = {}
        minted_sub_ids: list[str] = []
        for index, subcomp in enumerate(doc.subcomponents):
            sub_id = mint(db, Kind.COMP)
            append_event(
                db,
                project_id,
                ev.NodeCreated(
                    node_id=sub_id,
                    tier="comp",
                    kind=comp_node.kind,  # type: ignore[arg-type]
                    parent_id=component_id,
                    name=subcomp.name,
                    display_order=index,
                    content="",
                    is_foundation=subcomp.is_foundation,
                ),
            )
            alias_to_sub_id[subcomp.alias] = sub_id
            minted_sub_ids.append(sub_id)

            # Skeletal fragments for the subcomponent seeded from
            # its role + api-intent. The Phase 5 subcomparch
            # generation handler (enqueued post-commit below) will
            # replace these with real content once the subcomponent's
            # own arch doc is drafted and approved.
            _emit_fragment(db, project_id, sub_id, FragmentKind.TECHSPEC, subcomp.role)
            _emit_fragment(db, project_id, sub_id, FragmentKind.PUBAPI, subcomp.api_intent)

            # Decomposition edges: subresp → this subcomponent.
            for subresp_id in subcomp.resp_refs:
                edge_id = mint(db, Kind.EDGE)
                append_event(
                    db,
                    project_id,
                    ev.EdgeCreated(
                        edge_id=edge_id,
                        edge_type="decomposition",
                        source_id=subresp_id,
                        target_id=sub_id,
                    ),
                )

        # ── Phase 3: component-local policy minting ─────────────
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
                    parent_id=component_id,
                    name=policy.name,
                    display_order=index,
                    content=_serialize_policy_blob(policy),
                ),
            )
            minted_policy_ids.append(policy_id)

        # ── Phase 4: external dependency edges ──────────────────
        for target_comp_id in doc.external_deps:
            edge_id = mint(db, Kind.EDGE)
            append_event(
                db,
                project_id,
                ev.EdgeCreated(
                    edge_id=edge_id,
                    edge_type="dependency",
                    source_id=component_id,
                    target_id=target_comp_id,
                ),
            )

        # ── Phase 5: sub-dependency edges (alias-resolved) ──────
        for sub_dep in doc.sub_deps:
            from_sub_id = alias_to_sub_id[sub_dep.from_alias]
            to_sub_id = alias_to_sub_id[sub_dep.to_alias]
            edge_id = mint(db, Kind.EDGE)
            append_event(
                db,
                project_id,
                ev.EdgeCreated(
                    edge_id=edge_id,
                    edge_type="dependency",
                    source_id=from_sub_id,
                    target_id=to_sub_id,
                ),
            )

        db.commit()

        # ── Phase 6: post-commit policy application fan-out ─────
        pipeline_queue.enqueue(
            db,
            job_type=_APPLY_TOP_LEVEL_POLICIES_JOB,
            payload={"project_id": project_id, "component_id": component_id},
        )
        pipeline_queue.enqueue(
            db,
            job_type=_APPLY_COMPONENT_LOCAL_POLICIES_JOB,
            payload={"project_id": project_id, "component_id": component_id},
        )

        # ── Phase 7: post-commit subcomparch generation fan-out ─
        # One v2.generate_subcomparch per newly-minted subcomponent.
        # The subcomparch handler's precondition (parent comparch
        # approved) is guaranteed at this point since we just
        # committed the parent's arch doc content. Topological
        # ordering within the sibling set is a Phase 11 optimization;
        # for MVP we fan out all siblings at once and let the queue
        # handle them in arrival order, using skeletal pubapis as
        # each other's cross-context until subcomparch lands.
        for sub_id in minted_sub_ids:
            pipeline_queue.enqueue(
                db,
                job_type=_GENERATE_SUBCOMPARCH_JOB,
                payload={
                    "project_id": project_id,
                    "component_id": sub_id,
                    "feedback": None,
                },
            )

        logger.info(
            "mint_comparch project=%s comp=%s minted %d subcomponents, "
            "%d component-local policies, %d external deps, %d sub-deps; "
            "enqueued policy application passes",
            project_id,
            component_id,
            len(minted_sub_ids),
            len(minted_policy_ids),
            len(doc.external_deps),
            len(doc.sub_deps),
        )
    finally:
        db.close()


def _emit_fragment(db, project_id: str, owner_id: str, kind: FragmentKind, content: str) -> None:
    """Helper: emit a FragmentUpdated event for one section."""
    append_event(
        db,
        project_id,
        ev.FragmentUpdated(
            fragment_id=fragment_id(owner_id, kind),
            owner_id=owner_id,
            fragment_kind=kind,
            new_content=content,
        ),
    )


def _serialize_policies_fragment(policies) -> str:  # type: ignore[no-untyped-def]
    """Render the validated Policy tuple back to a <policies> XML blob.

    The arch-doc validator strips the fragment sections to
    structured dataclasses, but the on-disk fragment needs to be
    round-trippable so consumers that read fragments directly
    (e.g., Phase 5 subcomponent regen) get the full content. We
    serialize by re-emitting each policy as its inline blob,
    then wrap in a <policies> element.
    """
    if not policies:
        return "<policies></policies>"
    inner = "".join(_serialize_policy_blob(p) for p in policies)
    return f"<policies>{inner}</policies>"


def _serialize_deps_fragment(external_deps) -> str:  # type: ignore[no-untyped-def]
    """Render the external deps tuple back to a <dependencies> XML blob."""
    if not external_deps:
        return "<dependencies></dependencies>"
    inner = "".join(f'<dep to="{comp_id}"/>' for comp_id in external_deps)
    return f"<dependencies>{inner}</dependencies>"


def register() -> None:
    """Register the handler with the pipeline job queue."""
    pipeline_queue.register_handler(MINT_COMPARCH_JOB_TYPE, mint_comparch)
