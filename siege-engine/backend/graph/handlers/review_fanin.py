"""AI self-review handler for the fanin tier.

Fanin has no draft lifecycle — content lives on the Node row.
The review lands on ``Node.review_text`` via
``DraftReviewUpdated(draft_id=None, node_id=fanin_id)``.
"""

from __future__ import annotations

from backend.graph.handlers._tier_review import run_tier_review
from backend.graph.prompts.review.fanin import (
    render_system_prompt,
    render_user_prompt,
)
from backend.graph.review_context.fanin import gather_fanin_context
from backend.pipeline import queue as pipeline_queue

REVIEW_FANIN_JOB_TYPE = "v2.review_fanin"


async def review_fanin(payload: dict) -> None:
    await run_tier_review(
        payload=payload,
        log_handler_name="review_fanin",
        system_prompt=render_system_prompt(),
        render_user_prompt=render_user_prompt,
        build_context=gather_fanin_context,
        expected_node_tier="fanin",
        draft_required=False,
    )


def register() -> None:
    pipeline_queue.register_handler(REVIEW_FANIN_JOB_TYPE, review_fanin)
