"""AI self-review handler for the sysarch tier."""

from __future__ import annotations

from backend.graph.handlers._tier_review import run_tier_review
from backend.graph.prompts.review.sysarch import (
    render_system_prompt,
    render_user_prompt,
)
from backend.graph.review_context.sysarch import gather_sysarch_context
from backend.pipeline import queue as pipeline_queue

REVIEW_SYSARCH_JOB_TYPE = "v2.review_sysarch"


async def review_sysarch(payload: dict) -> None:
    await run_tier_review(
        payload=payload,
        log_handler_name="review_sysarch",
        system_prompt=render_system_prompt(),
        render_user_prompt=render_user_prompt,
        build_context=gather_sysarch_context,
        expected_node_tier="sysarch",
        draft_required=True,
    )


def register() -> None:
    pipeline_queue.register_handler(REVIEW_SYSARCH_JOB_TYPE, review_sysarch)
