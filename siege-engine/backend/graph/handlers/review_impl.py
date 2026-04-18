"""AI self-review handler for the impl tier."""

from __future__ import annotations

from backend.graph.handlers._tier_review import run_tier_review
from backend.graph.prompts.review.impl import (
    render_system_prompt,
    render_user_prompt,
)
from backend.graph.review_context.impl import gather_impl_context
from backend.pipeline import queue as pipeline_queue

REVIEW_IMPL_JOB_TYPE = "v2.review_impl"


async def review_impl(payload: dict) -> None:
    await run_tier_review(
        payload=payload,
        log_handler_name="review_impl",
        system_prompt=render_system_prompt(),
        render_user_prompt=render_user_prompt,
        build_context=gather_impl_context,
        expected_node_tier="impl",
        draft_required=True,
    )


def register() -> None:
    pipeline_queue.register_handler(REVIEW_IMPL_JOB_TYPE, review_impl)
