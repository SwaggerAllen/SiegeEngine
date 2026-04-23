"""Requirements-minting handler.

Registered on the pipeline job queue as
``v2.mint_requirements``. Triggered by the requirements approve
route after a ``DraftApproved`` event has committed the approved
requirements content to the reqs node. The handler parses that
content, mints one ``resp_*`` node per validated
``<responsibility>`` entry, **and** emits ``decomposition``
edges (``feat_* → resp_*``) for every feature each responsibility
covers, in one transaction.

Flow parallels :mod:`backend.graph.handlers.feature_mint`:

1. Open a DB session. Look up the reqs node's current content
   (``DraftApproved`` just committed it) and the set of known
   ``feat_*`` IDs in the project (the validator's reference set).
2. **Idempotency check:** if any top-level ``resp_*`` nodes exist
   in this project (``parent_id=None``, since this mint produces
   top-level responsibilities), log and return. Note that
   subresponsibilities minted by future ``v2.mint_subreqs`` runs
   will have non-null ``parent_id`` and are not counted.
3. Parse + validate via :func:`validate_requirements`, passing
   the known feature IDs. Failure here is a bug state because
   generation already ran its own parse-validate loop with the
   same check.
4. Append one ``NodeCreated`` event per validated
   :class:`Responsibility`, then one ``EdgeCreated`` event per
   ``(feat_id, resp_id)`` pair in its ``covers`` list. All
   events land in the same transaction.
5. Commit.

The mint handler does **not** run an LLM call. It is deterministic
and idempotent.

See ``docs/architecture/v2-roadmap.md`` Phase 3 and
``docs/architecture/v2-rearchitecture.md`` §Feature → Responsibility → Component.
"""

from __future__ import annotations

import logging

from backend.database import SessionLocal
from backend.graph import events as ev
from backend.graph.broadcast import commit_and_publish
from backend.graph.ids import Kind, mint
from backend.graph.parsers.validators import (
    Responsibility,
    ValidationError,
    validate_requirements,
)
from backend.graph.parsers.xml_sections import ParseError, extract_tag_tree
from backend.graph.reducer import append_event
from backend.graph.requirements import get_reqs_node
from backend.graph.sysarch import bootstrap_sysarch_node, get_sysarch_node
from backend.models.node import Node
from backend.pipeline import queue as pipeline_queue

logger = logging.getLogger(__name__)

MINT_REQUIREMENTS_JOB_TYPE = "v2.mint_requirements"


class RequirementsMintHandlerError(RuntimeError):
    """Raised when the mint handler cannot proceed."""


async def mint_requirements(payload: dict) -> None:
    """Job handler for ``v2.mint_requirements``.

    Payload shape: ``{"project_id": str}``. The reqs node is
    looked up by project; the handler reads its current (already-
    approved) content.
    """
    project_id = payload.get("project_id")
    if not isinstance(project_id, str) or not project_id:
        raise RequirementsMintHandlerError("mint_requirements payload missing project_id")

    db = SessionLocal()
    try:
        node = get_reqs_node(db, project_id)
        if node is None:
            raise RequirementsMintHandlerError(
                f"Project {project_id!r} has no reqs node; "
                "was mint_requirements enqueued before bootstrap?"
            )
        content = node.content or ""
        if not content.strip():
            raise RequirementsMintHandlerError(
                f"Project {project_id!r} reqs node has empty content; "
                "was mint_requirements enqueued before DraftApproved?"
            )

        # Collect the set of known feature IDs for validator checks.
        # The generation handler ran the same check against the same
        # set of features, so in the happy path this should be a
        # re-run of a parse that already passed. If features were
        # added between generation and approval, the validator
        # catches the resulting missing-coverage case here.
        feature_ids: set[str] = {
            fid
            for (fid,) in db.query(Node.id)
            .filter(Node.project_id == project_id, Node.tier == "feat")
            .all()
        }

        # Idempotency: skip if any top-level resp_* already exist
        # in this project. Subresp nodes (minted later by subreqs)
        # have parent_id != None, so filtering on parent_id is how
        # we distinguish "top-level responsibilities minted by this
        # handler" from "subresponsibilities minted by subreqs
        # handlers".
        existing_top_level = (
            db.query(Node)
            .filter(
                Node.project_id == project_id,
                Node.tier == "resp",
                Node.parent_id.is_(None),
            )
            .count()
        )
        if existing_top_level > 0:
            logger.info(
                "mint_requirements project=%s skipped (already has %d top-level resp_* nodes)",
                project_id,
                existing_top_level,
            )
            return

        try:
            tree = extract_tag_tree(content, "requirements")
            responsibilities = validate_requirements(tree, known_feature_ids=feature_ids)
        except (ParseError, ValidationError) as exc:
            raise RequirementsMintHandlerError(
                f"mint_requirements project={project_id} could not parse "
                f"approved reqs content: {exc}"
            ) from exc

        minted_resp_ids: list[str] = []
        minted_edge_ids: list[str] = []
        for index, resp in enumerate(responsibilities):
            resp_id = mint(db, Kind.RESP)
            append_event(
                db,
                project_id,
                ev.NodeCreated(
                    node_id=resp_id,
                    tier="resp",
                    kind="domain",
                    parent_id=None,
                    name=resp.name,
                    display_order=index,
                    content=_render_responsibility_content(resp),
                ),
            )
            minted_resp_ids.append(resp_id)

            # Emit one decomposition edge per tagged feature.
            # Direction is upstream → downstream: feature is
            # the source, responsibility is the target, matching
            # the "feat decomposes INTO resp" reading.
            for feat_id in resp.feats:
                edge_id = mint(db, Kind.EDGE)
                append_event(
                    db,
                    project_id,
                    ev.EdgeCreated(
                        edge_id=edge_id,
                        edge_type="decomposition",
                        source_id=feat_id,
                        target_id=resp_id,
                    ),
                )
                minted_edge_ids.append(edge_id)

        # Bootstrap the sysarch node in the same transaction as
        # the resp mints so either both land or neither does.
        # Skip if a sysarch node already exists (replay safety).
        should_enqueue_sysarch_generation = get_sysarch_node(db, project_id) is None
        if should_enqueue_sysarch_generation:
            bootstrap_sysarch_node(db, project_id)

        # commit_and_publish so the NodeCreated events broadcast and
        # the Sysarch tab appears without a manual refresh (B1).
        commit_and_publish(db, project_id)

        # Enqueue sysarch generation after the commit. Transient
        # enqueue failure leaves a sysarch bootstrap node without
        # a job, which the GET /sysarch lazy-bootstrap path heals.
        if should_enqueue_sysarch_generation:
            pipeline_queue.enqueue(
                db,
                job_type="v2.generate_sysarch",
                payload={"project_id": project_id, "feedback": None},
            )

        logger.info(
            "mint_requirements project=%s minted %d resp_* nodes and %d decomposition edges",
            project_id,
            len(minted_resp_ids),
            len(minted_edge_ids),
        )
    finally:
        db.close()


def _render_responsibility_content(resp: Responsibility) -> str:
    """Synthesize the resp node's ``content`` from the atom.

    Under the atomic grammar, an atom's name is the scope phrase
    verbatim — so the content downstream readers see is just the
    name.
    """
    return resp.name


def register() -> None:
    """Register the handler with the pipeline job queue."""
    pipeline_queue.register_handler(MINT_REQUIREMENTS_JOB_TYPE, mint_requirements)
