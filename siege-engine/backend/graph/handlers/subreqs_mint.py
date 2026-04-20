"""Subrequirements minting handler.

Registered on the pipeline job queue as ``v2.mint_subrequirements``.
Triggered by the subreqs approve route after ``DraftApproved``
commits the approved content to the component's subreqs node.

Flow:

1. Open a DB session. Look up the component's subreqs node and
   the set of top-level resps assigned to this component
   (``known_parent_resp_ids``).
2. **Idempotency check:** if any subresp ``resp_*`` nodes
   already exist with ``parent_id=component_id``, skip.
3. Parse + validate the approved content via
   :func:`validate_subrequirements`.
4. For each validated :class:`Subresponsibility`:
   - Mint a ``resp_*`` ID and emit ``NodeCreated`` with
     ``tier="resp"``, ``parent_id=component_id`` (subresps live
     structurally under their owning component),
     ``display_order`` from the parse order, ``content=intent``.
   - For each parent resp id in its ``derived_from`` list, emit
     an ``EdgeCreated`` with
     ``edge_type="decomposition"``, ``source_id=parent_resp_id``,
     ``target_id=subresp_id``. This is the resp → subresp edge
     (many-to-many within the component).
5. Commit.
6. **Phase 4 hook**: post-commit, enqueue
   ``v2.generate_comparch`` for this component. The comparch
   handler's precondition check reads the subreqs node's
   content to confirm approval happened before running.

See ``docs/architecture/v2-roadmap.md`` Phase 3 stage 3.
"""

from __future__ import annotations

import logging

from backend.database import SessionLocal
from backend.graph import events as ev
from backend.graph.broadcast import commit_and_publish
from backend.graph.ids import Kind, mint
from backend.graph.parsers.validators import (
    ValidationError,
    validate_subrequirements,
)
from backend.graph.parsers.xml_sections import ParseError, extract_tag_tree
from backend.graph.queries import (
    all_domain_parents_have_populated_fanin,
    top_level_resps_assigned_to,
)
from backend.graph.reducer import append_event
from backend.graph.subrequirements import get_subreqs_node
from backend.models.node import Node
from backend.pipeline import queue as pipeline_queue

logger = logging.getLogger(__name__)

MINT_SUBREQS_JOB_TYPE = "v2.mint_subrequirements"


class SubreqsMintHandlerError(RuntimeError):
    """Raised when the mint handler cannot proceed."""


async def mint_subreqs(payload: dict) -> None:
    """Job handler for ``v2.mint_subrequirements``.

    Payload shape: ``{"project_id": str, "component_id": str}``.
    """
    project_id = payload.get("project_id")
    component_id = payload.get("component_id")
    if not isinstance(project_id, str) or not project_id:
        raise SubreqsMintHandlerError("mint_subreqs payload missing project_id")
    if not isinstance(component_id, str) or not component_id:
        raise SubreqsMintHandlerError("mint_subreqs payload missing component_id")

    db = SessionLocal()
    try:
        comp_node = db.get(Node, component_id)
        if comp_node is None or comp_node.project_id != project_id:
            raise SubreqsMintHandlerError(
                f"Component {component_id!r} not found in project {project_id!r}"
            )

        subreqs_node = get_subreqs_node(db, project_id, component_id)
        if subreqs_node is None:
            raise SubreqsMintHandlerError(
                f"Component {component_id!r} has no subreqs node; "
                "was mint_subreqs enqueued before bootstrap?"
            )
        content = subreqs_node.content or ""
        if not content.strip():
            raise SubreqsMintHandlerError(
                f"Component {component_id!r} subreqs node has empty content; "
                "was mint_subreqs enqueued before DraftApproved?"
            )

        # Idempotency: skip if any subresps already exist under
        # this component. The reqs mint's idempotency check filters
        # on parent_id=None for top-level resps; this filters on
        # parent_id=component_id for subresps.
        existing_subresps = (
            db.query(Node)
            .filter(
                Node.project_id == project_id,
                Node.tier == "resp",
                Node.parent_id == component_id,
            )
            .count()
        )
        if existing_subresps > 0:
            logger.info(
                "mint_subreqs project=%s comp=%s skipped (already has %d subresps)",
                project_id,
                component_id,
                existing_subresps,
            )
            return

        # Gather known parent resps for the validator cross-check.
        parent_resp_rows = top_level_resps_assigned_to(db, component_id)
        known_parent_resp_ids: set[str] = {r.id for r in parent_resp_rows}

        try:
            tree = extract_tag_tree(content, "subrequirements")
            subresps = validate_subrequirements(tree, known_parent_resp_ids=known_parent_resp_ids)
        except (ParseError, ValidationError) as exc:
            raise SubreqsMintHandlerError(
                f"mint_subreqs project={project_id} comp={component_id} "
                f"could not parse approved subreqs content: {exc}"
            ) from exc

        minted_subresp_ids: list[str] = []
        minted_edge_ids: list[str] = []
        for index, subresp in enumerate(subresps):
            subresp_id = mint(db, Kind.RESP)
            append_event(
                db,
                project_id,
                ev.NodeCreated(
                    node_id=subresp_id,
                    tier="resp",
                    kind="domain",
                    parent_id=component_id,
                    name=subresp.name,
                    display_order=index,
                    content=subresp.intent,
                ),
            )
            minted_subresp_ids.append(subresp_id)

            # Emit one decomposition edge per parent resp this
            # subresp derives from. Direction is upstream →
            # downstream: parent resp is the source, subresp is
            # the target. Matches the feat→resp convention.
            for parent_resp_id in subresp.derived_from:
                edge_id = mint(db, Kind.EDGE)
                append_event(
                    db,
                    project_id,
                    ev.EdgeCreated(
                        edge_id=edge_id,
                        edge_type="decomposition",
                        source_id=parent_resp_id,
                        target_id=subresp_id,
                    ),
                )
                minted_edge_ids.append(edge_id)

        # commit_and_publish so the NodeCreated + EdgeCreated events
        # broadcast and the sidebar's subresp children show up under
        # their owning comp without a manual refresh (B1).
        commit_and_publish(db, project_id)

        # Phase 4 hook: now that subresps are minted, enqueue
        # comparch generation for this component. The comparch
        # handler's precondition check reads the subreqs node's
        # content to verify approval; writing the subresps in
        # the same commit as the approval makes the precondition
        # satisfiable by the time the enqueued job runs.
        #
        # Phase 6 ordering: domain_parent edges count as a
        # dependency in regen order. If this component is
        # presentational and any of its domain parents has not
        # yet had its fan-in synthesis land (i.e. the parent's
        # ``fanin_*`` child is missing or empty), defer the
        # comparch enqueue. Fan-in lands after the domain side's
        # impl set is fully approved (see ``on_impl_approved`` and
        # ``all_impls_populated_for``). When the last domain
        # parent's fan-in content commits, the
        # post-fan-in-commit hook in ``fanin_generation`` re-checks
        # presentational children and enqueues the ones that are
        # now ready. Domain comps and presentational comps with no
        # domain_parent edges are unaffected — the readiness
        # helper returns True for them.
        if all_domain_parents_have_populated_fanin(db, component_id):
            pipeline_queue.enqueue(
                db,
                job_type="v2.generate_comparch",
                payload={
                    "project_id": project_id,
                    "component_id": component_id,
                    "feedback": None,
                },
            )
            logger.info(
                "mint_subreqs project=%s comp=%s minted %d subresps and %d edges "
                "(comparch generation enqueued)",
                project_id,
                component_id,
                len(minted_subresp_ids),
                len(minted_edge_ids),
            )
        else:
            logger.info(
                "mint_subreqs project=%s comp=%s minted %d subresps and %d edges "
                "(comparch generation deferred — waiting on domain parents' fan-in)",
                project_id,
                component_id,
                len(minted_subresp_ids),
                len(minted_edge_ids),
            )
    finally:
        db.close()


def register() -> None:
    """Register the handler with the pipeline job queue."""
    pipeline_queue.register_handler(MINT_SUBREQS_JOB_TYPE, mint_subreqs)
