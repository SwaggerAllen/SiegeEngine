"""Thin wrapper for per-tier review handlers.

Every tier's review handler follows the same shape: unpack
``(project_id, node_id, draft_id)`` from the payload, open a
session, gather context via the tier's builder, render the
review prompt, then hand off to :func:`run_review`. This module
factors out that boilerplate so each tier's
``handlers/review_<tier>.py`` is ~20 lines of tier-specific
wiring.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from backend.database import SessionLocal
from backend.graph.handlers._bootstrap_review import run_review
from backend.models import Project
from backend.models.node import Draft, Node
from backend.projects.settings import get_project_settings

logger = logging.getLogger(__name__)


class TierReviewError(RuntimeError):
    """Raised when the review handler cannot proceed."""


async def run_tier_review(
    *,
    payload: dict[str, Any],
    log_handler_name: str,
    system_prompt: str,
    render_user_prompt: Callable[[Any, str], str],
    build_context: Callable[[Any, str, str], Any],
    expected_node_tier: str,
    draft_required: bool,
) -> None:
    """Execute the per-tier review job.

    ``build_context(db, project_id, node_id_or_scope)`` returns
    the tier's context dataclass. ``render_user_prompt(ctx,
    generated_output)`` builds the prompt.
    ``expected_node_tier`` guards against typo'd payloads (review
    job fires against the wrong tier). ``draft_required`` is
    ``True`` for every tier with a draft lifecycle and ``False``
    for fanin (Node-backed content).
    """
    project_id = payload.get("project_id")
    node_id = payload.get("node_id")
    draft_id = payload.get("draft_id")
    if not isinstance(project_id, str) or not project_id:
        raise TierReviewError(f"{log_handler_name} payload missing project_id")
    if not isinstance(node_id, str) or not node_id:
        raise TierReviewError(f"{log_handler_name} payload missing node_id")
    if draft_required:
        if not isinstance(draft_id, str) or not draft_id:
            raise TierReviewError(f"{log_handler_name} payload missing draft_id")

    db = SessionLocal()
    try:
        node = db.get(Node, node_id)
        if node is None or node.project_id != project_id:
            raise TierReviewError(
                f"{log_handler_name}: node {node_id!r} not found in project {project_id!r}"
            )
        if node.tier != expected_node_tier:
            raise TierReviewError(
                f"{log_handler_name}: node {node_id!r} tier is {node.tier!r}, "
                f"expected {expected_node_tier!r}"
            )

        if draft_required:
            draft = db.get(Draft, draft_id)
            if draft is None or draft.project_id != project_id:
                raise TierReviewError(
                    f"{log_handler_name}: draft {draft_id!r} not found in project {project_id!r}"
                )
            if draft.status != "pending":
                logger.info(
                    "%s project=%s draft=%s skipped (status=%s)",
                    log_handler_name,
                    project_id,
                    draft_id,
                    draft.status,
                )
                return
            generated_output = draft.content
        else:
            # Fanin — content lives on the Node row.
            generated_output = node.content or ""
            if not generated_output.strip():
                logger.info(
                    "%s project=%s node=%s skipped (empty content)",
                    log_handler_name,
                    project_id,
                    node_id,
                )
                return

        ctx = build_context(db, project_id, node_id)
        user_prompt = render_user_prompt(ctx, generated_output)

        project_row = db.get(Project, project_id)
        assert project_row is not None
        settings = get_project_settings(project_row)
        cli_timeout_seconds = settings.generation_timeout_seconds
        cli_max_budget_usd = settings.cli_max_budget_usd
    finally:
        db.close()

    await run_review(
        project_id=project_id,
        node_id=node_id,
        draft_id=draft_id if draft_required else None,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        cli_timeout_seconds=cli_timeout_seconds,
        cli_max_budget_usd=cli_max_budget_usd,
        log_handler_name=log_handler_name,
    )
