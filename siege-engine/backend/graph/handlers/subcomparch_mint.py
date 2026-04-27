"""Subcomponent architecture (subcomparch) mint handler.

Registered on the pipeline job queue as ``v2.mint_subcomparch``.
Triggered by the subcomparch approve route after ``DraftApproved``
commits the approved arch doc content to the subcomponent
``comp_*`` node.

Smaller than :mod:`backend.graph.handlers.comparch_mint`:

1. ``FragmentUpdated`` × 4 — one per fragment section, written
   to the **subcomparch layer** kinds (``subcomparchtechspec``,
   ``subcomparchpubapi``, ``subcomparchprivapi``,
   ``subcomparchdeps``). The legacy unprefixed slots
   (``techspec`` / ``pubapi``) keep the skeletal seeds
   comparch_mint wrote at subcomponent mint time so a
   subcomparch reset can clear the rich layer without losing
   the comparch-mint fall-back. ``privapi`` / ``deps`` stay
   empty in the legacy slot — they're new at this tier.
2. ``EdgeCreated(edge_type='dependency')`` per entry in
   ``<dependencies>``. Every target is already a real
   ``comp_*`` ID — same-parent siblings were minted by the
   parent's comparch_mint before this subcomparch gen ran,
   and parent-sibling top-levels existed from sysarch_mint.
   No alias layer is needed; the mint handler uses the target
   IDs directly.

No subcomponent minting (subs can't decompose further —
reducer enforces the two-level depth cap). No policy minting
(no policies at the subcomparch tier). No post-commit fan-out
— subcomparch is the leaf of the component-tier chain. Phase 6
will pick up the next layer (impl nodes hanging off each
subcomponent).

Idempotency: skip (return without work) if the subcomponent
already has a non-empty ``subcomparchdeps`` fragment.
``subcomparchdeps`` is unique to this tier — neither
sysarch_mint nor comparch_mint writes it — so its non-empty
presence is a reliable "subcomparch has already been minted"
marker. The reducer's fragment write is idempotent
on its own (it records a new FragmentUpdated event whose
content replaces the prior version), but skipping early avoids
unnecessary event-log churn on crash-recovery replays.

See ``docs/architecture/v2-roadmap.md`` Phase 5.
"""

from __future__ import annotations

import logging
from typing import Any

from backend.database import SessionLocal
from backend.graph import events as ev
from backend.graph.broadcast import commit_and_publish
from backend.graph.fragments import FragmentKind, fragment_id
from backend.graph.ids import Kind, mint
from backend.graph.parsers.validators import (
    SubArchDoc,
    ValidationError,
    validate_sub_arch_doc,
)
from backend.graph.parsers.xml_sections import ParseError, extract_tag_tree
from backend.graph.queries import (
    list_subcomponents_of,
    list_top_level_components,
)
from backend.graph.reducer import append_event
from backend.models.node import Fragment, Node
from backend.pipeline import queue as pipeline_queue

logger = logging.getLogger(__name__)

MINT_SUBCOMPARCH_JOB_TYPE = "v2.mint_subcomparch"


class SubcomparchMintHandlerError(RuntimeError):
    """Raised when the subcomparch mint handler cannot proceed."""


async def mint_subcomparch(payload: dict) -> None:
    """Job handler for ``v2.mint_subcomparch``.

    Payload: ``{"project_id": str, "component_id": str}``.
    """
    project_id = payload.get("project_id")
    component_id = payload.get("component_id")
    if not isinstance(project_id, str) or not project_id:
        raise SubcomparchMintHandlerError("mint_subcomparch payload missing project_id")
    if not isinstance(component_id, str) or not component_id:
        raise SubcomparchMintHandlerError("mint_subcomparch payload missing component_id")

    db = SessionLocal()
    try:
        sub_node = db.get(Node, component_id)
        if sub_node is None or sub_node.project_id != project_id:
            raise SubcomparchMintHandlerError(
                f"Component {component_id!r} not found in project {project_id!r}"
            )
        if sub_node.tier != "comp":
            raise SubcomparchMintHandlerError(
                f"Node {component_id!r} is not a comp_* node (tier={sub_node.tier!r})"
            )
        if sub_node.parent_id is None:
            raise SubcomparchMintHandlerError(
                f"Component {component_id!r} is a top-level component; "
                "mint_subcomparch only runs on subcomponents."
            )

        parent_node = db.get(Node, sub_node.parent_id)
        if parent_node is None or parent_node.tier != "comp":
            raise SubcomparchMintHandlerError(
                f"Subcomponent {component_id!r} has parent_id "
                f"{sub_node.parent_id!r} which is not a comp_* node"
            )

        content = sub_node.content or ""
        if not content.strip():
            raise SubcomparchMintHandlerError(
                f"Subcomponent {component_id!r} has empty content; "
                "was mint_subcomparch enqueued before DraftApproved?"
            )

        # Idempotency: a non-empty ``subcomparchdeps`` fragment
        # is the unique marker for "subcomparch already minted" —
        # only this handler writes that slot.
        existing_deps_frag = db.get(
            Fragment, fragment_id(component_id, FragmentKind.SUBCOMPARCH_DEPS)
        )
        if existing_deps_frag is not None and (existing_deps_frag.content or "").strip():
            logger.info(
                "mint_subcomparch project=%s sub=%s skipped (deps fragment already populated)",
                project_id,
                component_id,
            )
            return

        # Rebuild the known-ID sets the validator needs. Same
        # pattern as comparch_mint: read fresh from the DB to
        # catch any drift between generation and approval.
        all_siblings = list_subcomponents_of(db, parent_node.id)
        known_sibling_sub_ids: set[str] = {s.id for s in all_siblings if s.id != component_id}

        top_level_comps = list_top_level_components(db, project_id)
        known_parent_sibling_comp_ids: set[str] = {
            c.id for c in top_level_comps if c.id != parent_node.id
        }

        try:
            tree = extract_tag_tree(content, "subcomparch")
            doc = validate_sub_arch_doc(
                tree,
                known_sibling_sub_ids=known_sibling_sub_ids,
                known_parent_sibling_comp_ids=known_parent_sibling_comp_ids,
            )
        except (ParseError, ValidationError) as exc:
            raise SubcomparchMintHandlerError(
                f"mint_subcomparch project={project_id} sub={component_id} "
                f"could not parse approved arch doc: {exc}"
            ) from exc

        # ── Phase 1: fragment projection ────────────────────────
        # Writes target the **subcomparch layer** kinds so the
        # rich content sits one tier above the comparch-mint
        # skeletal seeds (``techspec`` / ``pubapi``) on the sub.
        # Subcomparch reset clears just these prefixed slots; the
        # comparch seed underneath survives. See
        # ``backend/graph/fragments.py`` for layered-reader
        # semantics.
        _emit_fragment(
            db, project_id, component_id, FragmentKind.SUBCOMPARCH_TECHSPEC, doc.techspec
        )
        _emit_fragment(db, project_id, component_id, FragmentKind.SUBCOMPARCH_PUBAPI, doc.pubapi)
        _emit_fragment(db, project_id, component_id, FragmentKind.SUBCOMPARCH_PRIVAPI, doc.privapi)
        deps_body = _serialize_deps_fragment(doc)
        _emit_fragment(db, project_id, component_id, FragmentKind.SUBCOMPARCH_DEPS, deps_body)

        # ── Phase 2: dependency edge emission ───────────────────
        # Every dep target is already a real comp_* ID at this
        # point — the validator rejects anything else — so there's
        # no alias resolution step.
        for dep in doc.deps:
            edge_id = mint(db, Kind.EDGE)
            append_event(
                db,
                project_id,
                ev.EdgeCreated(
                    edge_id=edge_id,
                    edge_type="dependency",
                    source_id=component_id,
                    target_id=dep.target,
                ),
            )

        # commit_and_publish so the subcomp's NodeCreated +
        # FragmentUpdated + EdgeCreated events broadcast and the
        # impl node appears in the sidebar without a manual refresh
        # (B1).
        commit_and_publish(db, project_id)

        # ── Phase 8: post-commit impl generation enqueue ────────
        # The subcomponent's arch doc just committed (its
        # Node.content is now non-empty). That satisfies the
        # impl-generation handler's precondition, so enqueue now.
        # comparch_mint already minted the impl shell at
        # subcomponent-mint time; we're just kicking off
        # generation to fill it.
        pipeline_queue.enqueue(
            db,
            job_type="v2.generate_impl",
            payload={
                "project_id": project_id,
                "owner_id": component_id,
                "feedback": None,
            },
        )

        logger.info(
            "mint_subcomparch project=%s sub=%s parent=%s committed (4 fragments, %d dep edges)",
            project_id,
            component_id,
            parent_node.id,
            len(doc.deps),
        )
    finally:
        db.close()


def _emit_fragment(
    db: Any,
    project_id: str,
    owner_id: str,
    kind: FragmentKind,
    content: str,
) -> None:
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


def _serialize_deps_fragment(doc: SubArchDoc) -> str:
    """Render a ``SubArchDoc``'s deps tuple back to a ``<dependencies>`` blob.

    Round-trippable format so downstream readers (e.g. Phase 6
    impl generation) can re-parse the fragment directly without
    walking the edge table. Every target is a real ``comp_*`` ID.
    """
    if not doc.deps:
        return "<dependencies></dependencies>"
    inner = "".join(f'<dep to="{d.target}"/>' for d in doc.deps)
    return f"<dependencies>{inner}</dependencies>"


def register() -> None:
    """Register the handler with the pipeline job queue."""
    pipeline_queue.register_handler(MINT_SUBCOMPARCH_JOB_TYPE, mint_subcomparch)
