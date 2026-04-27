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
from backend.graph.broadcast import commit_and_publish
from backend.graph.fragments import FragmentKind, fragment_id
from backend.graph.handlers.sysarch_mint import _serialize_policy_blob
from backend.graph.ids import Kind, mint
from backend.graph.parsers.validators import (
    ValidationError,
    format_subcomponent_pubapi,
    format_subcomponent_techspec,
    validate_arch_doc,
)
from backend.graph.parsers.xml_sections import ParseError, extract_tag_tree
from backend.graph.queries import (
    list_top_level_components,
    top_level_resps_assigned_to,
)
from backend.graph.reducer import append_event
from backend.models.node import Edge, Node
from backend.pipeline import queue as pipeline_queue
from sqlalchemy import select

logger = logging.getLogger(__name__)

MINT_COMPARCH_JOB_TYPE = "v2.mint_comparch"

# Post-commit fan-out job types. String constants so we don't
# create circular imports with the policy_application handlers
# (those modules import validators from the same package).
_APPLY_TOP_LEVEL_POLICIES_JOB = "v2.apply_top_level_policies"
_APPLY_COMPONENT_LOCAL_POLICIES_JOB = "v2.apply_component_local_policies"
_GENERATE_SUBCOMPARCH_JOB = "v2.generate_subcomparch"
_GENERATE_IMPL_JOB = "v2.generate_impl"


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

        # Rebuild the known-ID sets the validator needs. Read fresh
        # from the DB to catch any drift between generation and
        # approval (e.g., a sibling renamed, a parent resp's feat
        # set changed).
        parent_resp_rows = top_level_resps_assigned_to(db, component_id)
        parent_resp_ids: set[str] = {r.id for r in parent_resp_rows}
        # Build the parent-resp → feat-set map by walking incoming
        # feat → resp decomposition edges. The validator needs to
        # know which feats each parent resp legitimately tags so
        # the per-resp feat-slice claims can be checked.
        known_parent_resp_ids: dict[str, frozenset[str]] = {rid: frozenset() for rid in parent_resp_ids}
        if parent_resp_ids:
            feat_edge_rows = list(
                db.execute(
                    select(Edge.target_id, Edge.source_id)
                    .where(
                        Edge.edge_type == "decomposition",
                        Edge.target_id.in_(parent_resp_ids),
                    )
                )
            )
            grouped: dict[str, set[str]] = {rid: set() for rid in parent_resp_ids}
            for resp_id, feat_id in feat_edge_rows:
                if feat_id and feat_id.startswith("feat_"):
                    grouped[resp_id].add(feat_id)
            known_parent_resp_ids = {rid: frozenset(feats) for rid, feats in grouped.items()}

        siblings = [c for c in list_top_level_components(db, project_id) if c.id != component_id]
        known_sibling_comp_ids: set[str] = {c.id for c in siblings}

        try:
            tree = extract_tag_tree(content, "comparch")
            doc = validate_arch_doc(
                tree,
                known_parent_resp_ids=known_parent_resp_ids,
                known_sibling_comp_ids=known_sibling_comp_ids,
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
        _emit_fragment(
            db,
            project_id,
            component_id,
            FragmentKind.FAILURE_SURFACE,
            doc.failure_surface,
        )
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

            # Phase 8: mint an empty impl shell under every
            # subcomponent. One impl per leaf, per the architecture
            # doc. The shell starts with content="" and
            # Phase 8's v2.generate_impl job (enqueued post-commit
            # below) fills it after the subcomparch is approved.
            _mint_impl_shell(db, project_id, sub_id, comp_node.kind, subcomp.name)

            # Skeletal fragments for the subcomponent seeded from
            # its role + api-intent. The Phase 5 subcomparch
            # generation handler (enqueued post-commit below) will
            # replace these with real content once the subcomponent's
            # own arch doc is drafted and approved.
            _emit_fragment(
                db,
                project_id,
                sub_id,
                FragmentKind.TECHSPEC,
                format_subcomponent_techspec(subcomp),
            )
            _emit_fragment(
                db,
                project_id,
                sub_id,
                FragmentKind.PUBAPI,
                format_subcomponent_pubapi(subcomp),
            )

            # Decomposition edges: parent resp → this subcomp, plus
            # one feat → this subcomp per claimed feat slice. The
            # reducer dedups on
            # ``(project_id, edge_type, source_id, target_id)`` so a
            # re-mint is safe. Multi-owner cases produce multiple
            # edges from the same source to different subcomp
            # targets — the staleness walker handles that fan-out
            # naturally.
            for owned in subcomp.owns:
                resp_edge_id = mint(db, Kind.EDGE)
                append_event(
                    db,
                    project_id,
                    ev.EdgeCreated(
                        edge_id=resp_edge_id,
                        edge_type="decomposition",
                        source_id=owned.resp_id,
                        target_id=sub_id,
                    ),
                )
                for feat_id in owned.feat_ids:
                    feat_edge_id = mint(db, Kind.EDGE)
                    append_event(
                        db,
                        project_id,
                        ev.EdgeCreated(
                            edge_id=feat_edge_id,
                            edge_type="decomposition",
                            source_id=feat_id,
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

        # Phase 8: if this comp is un-fanned-out (no subcomponents
        # in the approved comparch), mint a single impl shell
        # under the comp itself. The architecture doc is explicit:
        # "A component with no subcomponents has one impl_*
        # directly." Fanned-out comps get no impl of their own —
        # their impl lives in subcomponent impls.
        if not minted_sub_ids:
            _mint_impl_shell(db, project_id, component_id, comp_node.kind, comp_node.name)

        # Phase 7: if this is a fanned-out domain comp, mint its
        # fan-in synthesis shell. One ``fanin_*`` per fanned-out
        # domain comp, sitting as a child of the comp. Content
        # starts empty; the fan-in generation handler
        # (``v2.generate_fanin``) is enqueued by the
        # impl-approval hook on the first descendant impl
        # approval, so mint-time enqueue is deliberately skipped.
        # Presentational comps do not get fan-ins — only domain
        # comps have the "built vs contract" drift concern that
        # fan-in solves.
        if comp_node.kind == "domain" and minted_sub_ids:
            _mint_fanin_shell(db, project_id, component_id, comp_node.name)

        # commit_and_publish so the NodeCreated events for subcomps +
        # policies + fanin shells + the EdgeCreated events broadcast,
        # keeping the sidebar + DAG in sync without a manual refresh
        # (B1).
        commit_and_publish(db, project_id)

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

        # ── Phase 8: impl generation enqueue (un-fanned-out only) ─
        # Only un-fanned-out top-level comps get their impl
        # enqueued here — their owner (the comp itself) has
        # content approved at this point. Subcomponent impls are
        # enqueued by subcomparch_mint after the subcomparch is
        # approved; enqueueing them here would fail the
        # precondition check (subs still have empty content).
        if not minted_sub_ids:
            pipeline_queue.enqueue(
                db,
                job_type=_GENERATE_IMPL_JOB,
                payload={
                    "project_id": project_id,
                    "owner_id": component_id,
                    "feedback": None,
                },
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

        # Phase 7.5: the presentational-child unblock walk has
        # moved to fanin_generation's post-commit hook — gating on
        # the domain parent's fanin content rather than its
        # comparch content. See ``fanin_generation.on_fanin_commit``
        # for the replacement path.
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


def _mint_impl_shell(
    db,  # type: ignore[no-untyped-def]
    project_id: str,
    owner_id: str,
    owner_kind: str,
    owner_name: str,
) -> str | None:
    """Mint an empty ``impl_*`` shell under ``owner_id``, or return None if one exists.

    Idempotent: if an impl_* child already exists under this
    owner, logs and returns None. The existing shell's id is not
    returned because the caller uses the return value only to
    know whether an enqueue happened. Generation is enqueued
    separately in the comparch_mint post-commit fan-out, keyed
    on owner_id (which is stable).

    Kind is inherited from the owner. For subcomponents, that's
    the owning top-level's kind (which is what comparch_mint
    already writes into the subcomponent NodeCreated). For an
    un-fanned-out top-level owner, it's the comp's own kind.
    Matches the implicit "kind flows down" rule used everywhere
    else in the v2 model.
    """
    from sqlalchemy import select

    existing = db.execute(
        select(Node).where(
            Node.project_id == project_id,
            Node.tier == "impl",
            Node.parent_id == owner_id,
        )
    ).scalar_one_or_none()
    if existing is not None:
        logger.info(
            "mint_comparch project=%s owner=%s impl shell already exists (id=%s); skipping",
            project_id,
            owner_id,
            existing.id,
        )
        return None

    impl_id = mint(db, Kind.IMPL)
    append_event(
        db,
        project_id,
        ev.NodeCreated(
            node_id=impl_id,
            tier="impl",
            kind=owner_kind,  # type: ignore[arg-type]
            parent_id=owner_id,
            name=f"{owner_name} impl",
            display_order=0,
            content="",
        ),
    )
    return impl_id


def _mint_fanin_shell(
    db,  # type: ignore[no-untyped-def]
    project_id: str,
    owner_comp_id: str,
    owner_name: str,
) -> str | None:
    """Mint an empty ``fanin_*`` shell under ``owner_comp_id``, or None if one exists.

    Idempotent: if a fan-in child already exists under this comp,
    logs and returns None. The shell's id is not returned because
    the caller uses the return value only to know whether a mint
    happened. Fan-in generation is NOT enqueued here — the first
    descendant impl approval triggers it via the
    ``on_impl_approved`` hook on ``IMPL_CONFIG``.

    Kind is always ``"domain"`` because fan-ins only exist for
    fanned-out domain comps — presentational comps don't get
    fan-ins. The caller gates on ``comp.kind == "domain"``
    before calling this helper.
    """
    from sqlalchemy import select

    existing = db.execute(
        select(Node).where(
            Node.project_id == project_id,
            Node.tier == "fanin",
            Node.parent_id == owner_comp_id,
        )
    ).scalar_one_or_none()
    if existing is not None:
        logger.info(
            "mint_comparch project=%s owner=%s fanin shell already exists (id=%s); skipping",
            project_id,
            owner_comp_id,
            existing.id,
        )
        return None

    fanin_id = mint(db, Kind.FANIN)
    append_event(
        db,
        project_id,
        ev.NodeCreated(
            node_id=fanin_id,
            tier="fanin",
            kind="domain",
            parent_id=owner_comp_id,
            name=f"{owner_name} fan-in",
            display_order=0,
            content="",
        ),
    )
    return fanin_id


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
