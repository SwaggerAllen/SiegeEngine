"""Subreqs AI self-review handler.

Registered on the pipeline queue as ``v2.review_subreqs``.
Payload: ``{"project_id": str, "node_id": str, "draft_id": str}``.

Called once after every subreqs draft commits (by
``persist_draft``'s optional review-enqueue hook). Re-assembles
the same context the generator saw via
``gather_subreqs_context``, renders the review prompt, runs the
CLI, and emits ``DraftReviewUpdated`` via the shared
``run_review`` helper.

Failure model: transient CLI failures retry inside
``run_review``; permanent failures (retry budget exhausted, CLI
fatal, empty output) raise — the pipeline worker marks the job
``failed`` with ``error_message``, which surfaces on the tier
detail as ``review_status="failed"`` + ``review_last_error``.
The user clicks "Retry review" (new endpoint) to enqueue a
fresh job against the same draft.
"""

from __future__ import annotations

import logging

from backend.database import SessionLocal
from backend.graph.handlers._bootstrap_review import run_review
from backend.graph.prompts.review.subreqs import (
    render_system_prompt,
    render_user_prompt,
)
from backend.graph.review_context.subreqs import gather_subreqs_context
from backend.models import Project
from backend.models.node import Draft, Node
from backend.pipeline import queue as pipeline_queue
from backend.projects.settings import get_project_settings

logger = logging.getLogger(__name__)

REVIEW_SUBREQS_JOB_TYPE = "v2.review_subreqs"


class ReviewSubreqsError(RuntimeError):
    """Raised when the review handler cannot proceed."""


async def review_subreqs(payload: dict) -> None:
    project_id = payload.get("project_id")
    node_id = payload.get("node_id")
    draft_id = payload.get("draft_id")
    if not isinstance(project_id, str) or not project_id:
        raise ReviewSubreqsError("review_subreqs payload missing project_id")
    if not isinstance(node_id, str) or not node_id:
        raise ReviewSubreqsError("review_subreqs payload missing node_id")
    # ``draft_id`` is optional: present for the normal post-commit
    # review path, absent for retroactive review against approved
    # node content (pre-Phase-8 content, or a draft committed with
    # ``SIEGE_DISABLE_AI_REVIEW=1``).

    db = SessionLocal()
    try:
        subreqs_node = db.get(Node, node_id)
        if subreqs_node is None or subreqs_node.project_id != project_id:
            raise ReviewSubreqsError(
                f"Subreqs node {node_id!r} not found in project {project_id!r}"
            )
        if subreqs_node.tier != "subreqs":
            raise ReviewSubreqsError(
                f"Node {node_id!r} is not tier='subreqs' (got {subreqs_node.tier!r})"
            )
        comp_id = subreqs_node.parent_id
        if not comp_id:
            raise ReviewSubreqsError(
                f"Subreqs node {node_id!r} has no parent comp — can't gather context"
            )

        resolved_draft_id: str | None = None
        if isinstance(draft_id, str) and draft_id:
            draft = db.get(Draft, draft_id)
            if draft is None or draft.project_id != project_id:
                raise ReviewSubreqsError(f"Draft {draft_id!r} not found in project {project_id!r}")
            if draft.status != "pending":
                logger.info(
                    "review_subreqs project=%s draft=%s skipped (status=%s)",
                    project_id,
                    draft_id,
                    draft.status,
                )
                return
            generated_output = draft.content
            resolved_draft_id = draft.id
        else:
            # Retroactive path — review the approved node content
            # directly. Event lands on ``Node.review_text``.
            generated_output = subreqs_node.content or ""
            if not generated_output.strip():
                logger.info(
                    "review_subreqs project=%s node=%s skipped (empty content)",
                    project_id,
                    node_id,
                )
                return

        ctx = gather_subreqs_context(db, project_id, comp_id)
        user_prompt = render_user_prompt(ctx, generated_output)
        system_prompt = render_system_prompt()

        project_row = db.get(Project, project_id)
        assert project_row is not None
        settings = get_project_settings(project_row)
        cli_timeout_seconds = settings.generation_timeout_seconds
        cli_max_budget_usd = settings.cli_max_budget_usd
        cli_max_output_tokens = settings.cli_max_output_tokens
    finally:
        db.close()

    await run_review(
        project_id=project_id,
        node_id=node_id,
        draft_id=resolved_draft_id,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        cli_timeout_seconds=cli_timeout_seconds,
        cli_max_budget_usd=cli_max_budget_usd,
        cli_max_output_tokens=cli_max_output_tokens,
        log_handler_name="review_subreqs",
    )


def register() -> None:
    pipeline_queue.register_handler(REVIEW_SUBREQS_JOB_TYPE, review_subreqs)
