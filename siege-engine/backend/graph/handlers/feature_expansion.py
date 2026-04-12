"""Feature-expansion generation handler.

Registered on the pipeline job queue as
``v2.generate_feature_expansion``. The payload is
``{"project_id": str, "feedback": str | None}``.

Flow:

1. Open a DB session, load inputs (project doc, expansion node,
   current pending draft if any, feedback). Close the session **before**
   calling the LLM so we don't hold a connection across a potentially
   long-running subprocess.
2. Call ``cli_manager.generate`` with the rendered feature-expansion
   prompt. Any exception bubbles out of the handler — the job queue
   catches it, marks the job ``failed``, and records the error.
3. Open a fresh session. If a pending draft existed on entry, append
   ``DraftDiscarded`` to clear the partial-unique-index slot. Then
   append ``DraftGenerated`` with a freshly minted draft id and batch
   id. Commit.

The handler never touches ``Node.content`` directly — that is the
reducer's job on ``DraftApproved``.
"""

from __future__ import annotations

import logging
import secrets
import uuid

from backend.cli.manager import cli_manager
from backend.database import SessionLocal
from backend.graph import events as ev
from backend.graph.expansion import get_expansion_node, pending_expansion_draft
from backend.graph.prompts.feature_expansion import (
    SYSTEM_PROMPT,
    render_user_prompt,
)
from backend.graph.reducer import append_event
from backend.models.input_document import InputDocument
from backend.pipeline import queue as pipeline_queue

logger = logging.getLogger(__name__)

GENERATE_FEATURE_EXPANSION_JOB_TYPE = "v2.generate_feature_expansion"

CLI_TIMEOUT_SECONDS = 180
CLI_MAX_BUDGET_USD = 0.50
# Disable all CLI tools — this is pure text generation, no file I/O.
CLI_TOOLS = '""'


class FeatureExpansionHandlerError(RuntimeError):
    """Raised when the handler cannot proceed because of missing state."""


def _new_draft_id() -> str:
    return f"draft_{secrets.token_hex(8)}"


def _new_batch_id() -> str:
    return f"batch_{uuid.uuid4().hex[:16]}"


async def generate_feature_expansion(payload: dict) -> None:
    """Job handler for ``v2.generate_feature_expansion``.

    Payload shape: ``{"project_id": str, "feedback": str | None}``.
    """
    project_id = payload.get("project_id")
    if not isinstance(project_id, str) or not project_id:
        raise FeatureExpansionHandlerError("generate_feature_expansion payload missing project_id")
    feedback: str | None = payload.get("feedback")

    # ── Phase 1: gather inputs ──────────────────────────────────────
    db = SessionLocal()
    try:
        node = get_expansion_node(db, project_id)
        if node is None:
            raise FeatureExpansionHandlerError(
                f"Project {project_id!r} has no expansion node; "
                "was bootstrap_expansion_node called on creation?"
            )
        exp_node_id: str = node.id
        prior_approved: str | None = node.content or None

        pending = pending_expansion_draft(db, project_id)
        prior_pending: str | None = pending.content if pending else None
        prior_pending_id: str | None = pending.id if pending else None

        input_doc_row = (
            db.query(InputDocument)
            .filter(
                InputDocument.project_id == project_id,
                InputDocument.doc_type == "project_doc",
            )
            .order_by(InputDocument.created_at.desc())
            .first()
        )
        input_doc = input_doc_row.content if input_doc_row else ""
    finally:
        db.close()

    # ── Phase 2: LLM call (no DB session held) ──────────────────────
    user_prompt = render_user_prompt(
        input_doc=input_doc,
        prior_approved=prior_approved,
        prior_pending=prior_pending,
        feedback=feedback,
    )
    logger.info(
        "generate_feature_expansion project=%s prior_pending=%s feedback=%s",
        project_id,
        bool(prior_pending),
        bool(feedback),
    )
    output = await cli_manager.generate(
        prompt=user_prompt,
        system_prompt=SYSTEM_PROMPT,
        tools=CLI_TOOLS,
        timeout=CLI_TIMEOUT_SECONDS,
        max_budget_usd=CLI_MAX_BUDGET_USD,
    )

    # ── Phase 3: persist events ─────────────────────────────────────
    db = SessionLocal()
    try:
        if prior_pending_id is not None:
            # DraftDiscarded must land *before* DraftGenerated to clear
            # the partial unique index on (target_type, target_id)
            # where status='pending'.
            append_event(
                db,
                project_id,
                ev.DraftDiscarded(draft_id=prior_pending_id),
            )

        new_draft_id = _new_draft_id()
        new_batch_id = _new_batch_id()
        append_event(
            db,
            project_id,
            ev.DraftGenerated(
                draft_id=new_draft_id,
                target_type="node",
                target_id=exp_node_id,
                content=output,
                batch_id=new_batch_id,
            ),
        )
        db.commit()
        logger.info(
            "generate_feature_expansion project=%s draft_id=%s committed",
            project_id,
            new_draft_id,
        )
    finally:
        db.close()


def register() -> None:
    """Register the handler with the pipeline job queue.

    Called at import time from ``backend.graph.__init__`` so the
    pipeline worker always has a handler for the job type.
    """
    pipeline_queue.register_handler(
        GENERATE_FEATURE_EXPANSION_JOB_TYPE,
        generate_feature_expansion,
    )
