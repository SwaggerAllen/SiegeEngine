"""AI self-review handler for the requirements tier."""

from __future__ import annotations

from backend.graph.handlers._tier_review import run_tier_review
from backend.graph.prompts.review.requirements import (
    render_system_prompt,
    render_user_prompt,
)
from backend.graph.review_context.requirements import gather_requirements_context
from backend.pipeline import queue as pipeline_queue

REVIEW_REQUIREMENTS_JOB_TYPE = "v2.review_requirements"


async def review_requirements(payload: dict) -> None:
    await run_tier_review(
        payload=payload,
        log_handler_name="review_requirements",
        system_prompt=render_system_prompt(),
        render_user_prompt=render_user_prompt,
        build_context=gather_requirements_context,
        expected_node_tier="reqs",
        draft_required=True,
    )


def register() -> None:
    pipeline_queue.register_handler(REVIEW_REQUIREMENTS_JOB_TYPE, review_requirements)
