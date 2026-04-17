"""Shared review runner for Phase 8 AI self-review jobs.

Every per-tier review handler renders its prompt from the same
context the generator saw, then calls this helper to run the
CLI, emit ``DraftReviewUpdated`` on success, and stamp attempt
progress on the Job row for the spinner UI.

Failure model: transient CLI errors retry via the same wrapper
generation uses (:func:`backend.graph.handlers.feature_expansion._call_cli_with_transient_retry`).
Permanent failures (transient budget exhausted, fatal CLI
error, empty output) raise — the pipeline worker marks the Job
``failed`` with ``error_message``, which the tier detail
surfaces as ``review_status="failed"`` + ``review_last_error``.

Commit path goes through ``commit_and_publish`` so SSE fires
when the review text lands — a draft that's committed but
still being reviewed won't refresh on the frontend otherwise,
since polling is gated on the in-flight state.
"""

from __future__ import annotations

import logging

from backend.database import SessionLocal
from backend.graph import events as ev
from backend.graph.broadcast import commit_and_publish
from backend.graph.handlers._bootstrap_generation import _record_attempt_progress
from backend.graph.handlers.feature_expansion import (
    CLI_MAX_TRANSIENT_RETRIES,
    _call_cli_with_transient_retry,
)
from backend.graph.reducer import append_event
from backend.models.telemetry import GenerationTelemetry

logger = logging.getLogger(__name__)


class ReviewError(RuntimeError):
    """Raised when the review CLI returns unusable output."""


async def run_review(
    *,
    project_id: str,
    node_id: str,
    draft_id: str | None,
    system_prompt: str,
    user_prompt: str,
    cli_timeout_seconds: int,
    cli_max_budget_usd: float,
    log_handler_name: str,
) -> None:
    """Run one review CLI call, commit ``DraftReviewUpdated`` on success.

    ``draft_id`` is the Draft row being reviewed, or ``None`` for
    fanin (no draft lifecycle — review targets the Node row).
    ``node_id`` is always populated and names the tier node whose
    detail query should refresh on SSE.
    """
    total_attempts = CLI_MAX_TRANSIENT_RETRIES + 1
    # Stamp attempt progress on the Job row so the frontend
    # spinner can show "Reviewing… attempt N / M" during the
    # transient-retry window. Same mechanism the generator uses.
    _record_attempt_progress(1, total_attempts)

    result = await _call_cli_with_transient_retry(
        prompt=user_prompt,
        system_prompt=system_prompt,
        timeout=cli_timeout_seconds,
        max_budget_usd=cli_max_budget_usd,
    )

    review_text = (result.text or "").strip()
    if not review_text:
        raise ReviewError("Review CLI returned empty output")

    db = SessionLocal()
    try:
        append_event(
            db,
            project_id,
            ev.DraftReviewUpdated(
                draft_id=draft_id,
                node_id=node_id,
                review_text=review_text,
            ),
        )
        db.add(
            GenerationTelemetry(
                project_id=project_id,
                node_id=node_id,
                section="review",
                model=result.model,
                prompt_tokens=result.prompt_tokens,
                completion_tokens=result.completion_tokens,
            )
        )
        commit_and_publish(db, project_id)
        logger.info(
            "%s project=%s node=%s committed review (prompt=%d completion=%d model=%s)",
            log_handler_name,
            project_id,
            node_id,
            result.prompt_tokens,
            result.completion_tokens,
            result.model,
        )
    finally:
        db.close()
