"""Feature-minting handler.

Registered on the pipeline job queue as ``v2.mint_features``.
Triggered by the expansion approve route after a ``DraftApproved``
event has committed the approved expansion content to the
expansion node. The handler parses that content, validates it,
and mints one ``feat_*`` ``Node`` per validated ``<feature>`` entry
in document order.

Flow:

1. Open a DB session. Look up the expansion node's current content
   (which ``DraftApproved`` has just committed to ``node.content``).
2. **Idempotency check:** if any ``feat_*`` nodes already exist in
   this project, log a warning and return without doing anything.
   This handles crash-recovery replays and the "user somehow
   re-approved" edge case.
3. Parse the content via :func:`extract_tag_tree` and validate it
   via :func:`validate_features`. Both should succeed because
   ``generate_feature_expansion`` already ran its parse-validate
   loop before the user ever saw the draft. A failure here is a
   bug state — the handler raises and the job queue marks it
   failed.
4. For each validated :class:`Feature`, append a ``NodeCreated``
   event with tier=``feat``, ``parent_id=None`` (features are
   top-level siblings in the project), ``name`` from the
   ``<name>`` tag, ``display_order`` from the parse order, and
   ``content`` = the ``<intent>`` paragraph. The reducer sets
   ``Node.content`` on the mint, so each ``feat_*`` starts life
   with the intent already populated.
5. Commit.

The mint handler does **not** run an LLM call. Parse-validate
retries live in the generation handler, not here. This keeps
the mint deterministic, fast, and idempotent — a retry never
changes what the user approved.

See ``docs/architecture/v2-roadmap.md`` Phase 2.
"""

from __future__ import annotations

import logging

from backend.database import SessionLocal
from backend.graph import events as ev
from backend.graph.expansion import get_expansion_node
from backend.graph.ids import Kind, mint
from backend.graph.parsers.validators import (
    ValidationError,
    validate_features,
)
from backend.graph.parsers.xml_sections import ParseError, extract_tag_tree
from backend.graph.reducer import append_event
from backend.graph.requirements import bootstrap_reqs_node, get_reqs_node
from backend.models.node import Node
from backend.pipeline import queue as pipeline_queue

logger = logging.getLogger(__name__)

MINT_FEATURES_JOB_TYPE = "v2.mint_features"


class FeatureMintHandlerError(RuntimeError):
    """Raised when the mint handler cannot proceed.

    Separate from the expansion handler's error type so job-queue
    failure rows are distinguishable by phase.
    """


async def mint_features(payload: dict) -> None:
    """Job handler for ``v2.mint_features``.

    Payload shape: ``{"project_id": str}``. The expansion node is
    looked up by project; the handler reads its current (already-
    approved) content.
    """
    project_id = payload.get("project_id")
    if not isinstance(project_id, str) or not project_id:
        raise FeatureMintHandlerError("mint_features payload missing project_id")

    db = SessionLocal()
    try:
        node = get_expansion_node(db, project_id)
        if node is None:
            raise FeatureMintHandlerError(
                f"Project {project_id!r} has no expansion node; "
                "was mint_features enqueued before bootstrap?"
            )
        content = node.content or ""
        if not content.strip():
            raise FeatureMintHandlerError(
                f"Project {project_id!r} expansion node has empty content; "
                "was mint_features enqueued before DraftApproved?"
            )

        # Idempotency: skip if any feat_* already exist in this
        # project. Handles crash-recovery replays and the
        # hypothetical re-approval case. Uses Node.project_id for
        # scoping since feat_* nodes have parent_id=None.
        existing_count = (
            db.query(Node).filter(Node.project_id == project_id, Node.tier == "feat").count()
        )
        if existing_count > 0:
            logger.info(
                "mint_features project=%s skipped (already has %d feat_* nodes)",
                project_id,
                existing_count,
            )
            return

        # Parse + validate the approved content. Should always
        # succeed because generate_feature_expansion ran its own
        # parse-validate loop before the user approved. A failure
        # here is a bug state — raise and let the job queue record
        # it.
        try:
            tree = extract_tag_tree(content, "features")
            features = validate_features(tree)
        except (ParseError, ValidationError) as exc:
            raise FeatureMintHandlerError(
                f"mint_features project={project_id} could not parse "
                f"approved expansion content: {exc}"
            ) from exc

        # Mint one feat_* per validated feature, preserving the
        # parse order via display_order. Each feat_* carries its
        # intent paragraph as content, its group label (if the
        # feature was inside a <group> block), and its implicit
        # flag — all via NodeCreated's optional fields. The
        # reducer writes them at creation time so rebuild-from-log
        # replays back to equivalent state.
        minted_ids: list[str] = []
        for index, feature in enumerate(features):
            feat_id = mint(db, Kind.FEAT)
            append_event(
                db,
                project_id,
                ev.NodeCreated(
                    node_id=feat_id,
                    tier="feat",
                    kind="domain",
                    parent_id=None,
                    name=feature.name,
                    display_order=index,
                    content=feature.intent,
                    group_label=feature.group_label,
                    is_implicit=feature.is_implicit,
                ),
            )
            minted_ids.append(feat_id)

        # Bootstrap the requirements node in the same transaction
        # as the feature mints so either both land or neither does.
        # Skip bootstrap if a reqs node already exists — handles the
        # "mint_features is being replayed" crash-recovery case.
        should_enqueue_reqs_generation = get_reqs_node(db, project_id) is None
        if should_enqueue_reqs_generation:
            bootstrap_reqs_node(db, project_id)

        db.commit()

        # Enqueue the initial requirements generation after the
        # commit so a transient enqueue failure doesn't roll back
        # the successful feat mints. The enqueue has its own commit;
        # the worst case is a bootstrap node without a job, which
        # the GET /requirements route lazy-bootstrap path handles.
        if should_enqueue_reqs_generation:
            pipeline_queue.enqueue(
                db,
                job_type="v2.generate_requirements",
                payload={"project_id": project_id, "feedback": None},
            )

        logger.info(
            "mint_features project=%s minted %d feat_* nodes: %s",
            project_id,
            len(minted_ids),
            minted_ids,
        )
    finally:
        db.close()


def register() -> None:
    """Register the handler with the pipeline job queue.

    Called at import time from ``backend.graph.__init__`` so the
    pipeline worker always has a handler for the job type.
    """
    pipeline_queue.register_handler(MINT_FEATURES_JOB_TYPE, mint_features)
