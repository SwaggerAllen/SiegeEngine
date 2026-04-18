"""AI self-review handler for the subcomparch tier."""

from __future__ import annotations

from backend.graph.handlers._tier_review import run_tier_review
from backend.graph.prompts.review.subcomparch import (
    render_system_prompt,
    render_user_prompt,
)
from backend.graph.review_context.subcomparch import gather_subcomparch_context
from backend.pipeline import queue as pipeline_queue

REVIEW_SUBCOMPARCH_JOB_TYPE = "v2.review_subcomparch"


async def review_subcomparch(payload: dict) -> None:
    await run_tier_review(
        payload=payload,
        log_handler_name="review_subcomparch",
        system_prompt=render_system_prompt(),
        render_user_prompt=render_user_prompt,
        build_context=gather_subcomparch_context,
        expected_node_tier="comp",  # subs live on the comp tier
        draft_required=True,
    )


def register() -> None:
    pipeline_queue.register_handler(REVIEW_SUBCOMPARCH_JOB_TYPE, review_subcomparch)
