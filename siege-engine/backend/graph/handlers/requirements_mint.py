"""Requirements-minting handler.

Registered on the pipeline job queue as
``v2.mint_requirements``. Triggered by the requirements approve
route after a ``DraftApproved`` event has committed the approved
requirements content to the reqs node. The handler parses that
content and mints one ``resp_*`` node per validated
``<responsibility>`` entry, in document order.

Flow parallels :mod:`backend.graph.handlers.feature_mint`:

1. Open a DB session. Look up the reqs node's current content
   (``DraftApproved`` just committed it).
2. **Idempotency check:** if any top-level ``resp_*`` nodes exist
   in this project (``parent_id=None``, since this mint produces
   top-level responsibilities), log and return. Note that
   subresponsibilities minted by future ``v2.mint_subreqs`` runs
   will have non-null ``parent_id`` and are not counted.
3. Parse + validate via :func:`validate_requirements`. Failure
   here is a bug state because generation already ran its own
   parse-validate loop.
4. Append one ``NodeCreated`` event per validated
   :class:`Responsibility` with ``tier="resp"``, ``parent_id=None``
   (top-level responsibilities are project-level siblings like
   features), ``display_order`` from the parse order, and
   ``content`` = the intent paragraph.
5. Commit.

The mint handler does **not** run an LLM call. It is deterministic
and idempotent.

See ``docs/architecture/v2-roadmap.md`` Phase 3.
"""

from __future__ import annotations

import logging

from backend.database import SessionLocal
from backend.graph import events as ev
from backend.graph.ids import Kind, mint
from backend.graph.parsers.validators import (
    ValidationError,
    validate_requirements,
)
from backend.graph.parsers.xml_sections import ParseError, extract_tag_tree
from backend.graph.reducer import append_event
from backend.graph.requirements import get_reqs_node
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
            responsibilities = validate_requirements(tree)
        except (ParseError, ValidationError) as exc:
            raise RequirementsMintHandlerError(
                f"mint_requirements project={project_id} could not parse "
                f"approved reqs content: {exc}"
            ) from exc

        minted_ids: list[str] = []
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
                    content=resp.intent,
                ),
            )
            minted_ids.append(resp_id)

        db.commit()
        logger.info(
            "mint_requirements project=%s minted %d resp_* nodes: %s",
            project_id,
            len(minted_ids),
            minted_ids,
        )
    finally:
        db.close()


def register() -> None:
    """Register the handler with the pipeline job queue."""
    pipeline_queue.register_handler(MINT_REQUIREMENTS_JOB_TYPE, mint_requirements)
