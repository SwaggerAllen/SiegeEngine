"""AI self-review handler for the feature-expansion tier."""

from __future__ import annotations

from backend.graph.handlers._tier_review import run_tier_review
from backend.graph.prompts.review.expansion import (
    render_system_prompt,
    render_user_prompt,
)
from backend.graph.review_context.expansion import gather_expansion_context
from backend.pipeline import queue as pipeline_queue

REVIEW_EXPANSION_JOB_TYPE = "v2.review_expansion"


async def review_expansion(payload: dict) -> None:
    await run_tier_review(
        payload=payload,
        log_handler_name="review_expansion",
        system_prompt=render_system_prompt(),
        render_user_prompt=render_user_prompt,
        build_context=gather_expansion_context,
        expected_node_tier="expansion",
        draft_required=True,
    )


def register() -> None:
    pipeline_queue.register_handler(REVIEW_EXPANSION_JOB_TYPE, review_expansion)
