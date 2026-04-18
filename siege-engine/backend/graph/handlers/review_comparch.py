"""AI self-review handler for the comparch tier."""

from __future__ import annotations

from backend.graph.handlers._tier_review import run_tier_review
from backend.graph.prompts.review.comparch import (
    render_system_prompt,
    render_user_prompt,
)
from backend.graph.review_context.comparch import gather_comparch_context
from backend.pipeline import queue as pipeline_queue

REVIEW_COMPARCH_JOB_TYPE = "v2.review_comparch"


async def review_comparch(payload: dict) -> None:
    await run_tier_review(
        payload=payload,
        log_handler_name="review_comparch",
        system_prompt=render_system_prompt(),
        render_user_prompt=render_user_prompt,
        build_context=gather_comparch_context,
        expected_node_tier="comp",
        draft_required=True,
    )


def register() -> None:
    pipeline_queue.register_handler(REVIEW_COMPARCH_JOB_TYPE, review_comparch)
