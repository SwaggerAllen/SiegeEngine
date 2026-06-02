"""Shared parse-validate retry loop for bootstrap-node generation handlers.

Every bootstrap generation handler (``feature_expansion``,
``requirements_generation``, and the upcoming ``sysarch`` /
``subreqs`` handlers in Phase 3 stages 2 and 3) runs the same outer
shape: render a prompt with the current retry state, call the CLI
with transient-error retry, parse and validate the result, retry on
validation failure up to a budget, raise if exhausted.

This module owns that loop so each caller only has to bind its
per-tier variations — prompt arguments, parser root tag, validator
function plus kwargs, exhausted-exception class.

The transient CLI retry helper and retry budget constants stay in
:mod:`backend.graph.handlers.feature_expansion` as the source of
truth; we import them here rather than duplicate.

Example caller binding (feature-expansion):

    def _render(*, prior_pending, parse_error):
        return render_user_prompt(
            input_doc=input_doc,
            prior_approved=prior_approved,
            prior_pending=prior_pending,
            feedback=feedback,
            parse_error=parse_error,
        )

    def _validate(tree):
        validate_features(tree)

    validated_output, attempts = await run_parse_validate_loop(
        root_tag="features",
        system_prompt=SYSTEM_PROMPT,
        cli_config=cli_config,
        prior_pending=prior_pending,
        render_prompt=_render,
        validate=_validate,
        exhausted_exception_cls=FeatureExpansionParseRetryExhausted,
        log_handler_name="generate_feature_expansion",
    )
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Literal

from sqlalchemy.orm.attributes import flag_modified

from backend.cli.config import CliInvocationConfig
from backend.cli.manager import CliError, CliTransientError, GenerationResult, cli_manager
from backend.database import SessionLocal
from backend.graph.parsers.validators import ValidationError
from backend.graph.parsers.xml_sections import ParseError, TagNode, extract_tag_tree
from backend.models.job import Job
from backend.pipeline.queue import current_job_id_var

logger = logging.getLogger(__name__)

# Disable all CLI tools — refs (the lone surviving bootstrap tier)
# generates pure text, no file I/O.
CLI_TOOLS = '""'

# Parse-validate retry budget. The first attempt plus this many
# additional retries means up to MAX_PARSE_RETRIES + 1 total LLM
# calls per user-requested generation. Keep small so runaway
# broken output doesn't silently blow the token budget.
MAX_PARSE_RETRIES = 3

# Transient-CLI-error retry budget. Separate from the parse-validate
# loop: this retries when the CLI itself fails (upstream Anthropic
# 5xx, process crash, etc.) — i.e. we never got usable output.
CLI_MAX_TRANSIENT_RETRIES = 3
CLI_RETRY_BACKOFF_SECONDS: tuple[float, ...] = (2.0, 4.0, 8.0)


async def _call_cli_with_transient_retry(**kwargs):  # type: ignore[no-untyped-def]
    """Invoke ``cli_manager.generate_with_usage`` with retry on transient errors."""
    last_exc: CliTransientError | None = None
    for attempt_idx in range(CLI_MAX_TRANSIENT_RETRIES + 1):
        try:
            return await cli_manager.generate_with_usage(**kwargs)
        except CliTransientError as exc:
            last_exc = exc
            if attempt_idx >= CLI_MAX_TRANSIENT_RETRIES:
                break
            backoff = CLI_RETRY_BACKOFF_SECONDS[attempt_idx]
            logger.warning(
                "CLI call failed transiently on attempt %d/%d, retrying in %.1fs: %s",
                attempt_idx + 1,
                CLI_MAX_TRANSIENT_RETRIES + 1,
                backoff,
                str(exc)[:500],
            )
            await asyncio.sleep(backoff)
    assert last_exc is not None
    raise last_exc


def _resolve_draft_batch_id() -> str:
    """Return the batch_id this draft should carry.

    Reads the running Job's payload from the contextvar-set Job row
    and lifts ``payload["batch_id"]`` if present (placed there by
    ``pipeline_queue.enqueue`` when the originating route minted a
    batch). Falls back to a fresh per-draft mint when:

    - the contextvar is unset (called outside a handler task — eg.
      direct unit-test calls into ``persist_draft``);
    - the running Job has no batch_id (legacy queued rows from
      before the column landed, or system-side cascade jobs that
      didn't mint a batch).
    """
    import secrets as _secrets

    job_id = current_job_id_var.get()
    if job_id is not None:
        try:
            with SessionLocal() as db:
                job = db.get(Job, job_id)
                if job is not None:
                    payload_batch = (job.payload or {}).get("batch_id")
                    if isinstance(payload_batch, str) and payload_batch:
                        return payload_batch
        except Exception:
            logger.exception("Failed to read batch_id from running Job; falling back to fresh mint")
    return f"batch_{_secrets.token_hex(8)}"


def _record_attempt_progress(attempt_idx: int, max_attempts: int) -> None:
    """Stamp the running Job row with the current parse-validate attempt.

    Reads the handler's job id from ``current_job_id_var`` (set by the
    worker loop before dispatching the handler) and updates the Job's
    ``payload`` dict with ``_current_attempt`` / ``_max_attempts`` so
    :func:`backend.graph.queries.latest_generation_status` can surface
    retry progress to the UI while generation is still in flight.

    No-op outside a handler task (contextvar unset). Any DB error is
    logged and swallowed — progress visibility must not break generation.
    """
    job_id = current_job_id_var.get()
    if job_id is None:
        return
    try:
        with SessionLocal() as db:
            job = db.get(Job, job_id)
            if job is None:
                return
            payload = dict(job.payload or {})
            payload["_current_attempt"] = attempt_idx
            payload["_max_attempts"] = max_attempts
            job.payload = payload
            flag_modified(job, "payload")
            db.commit()
    except Exception:
        logger.exception("Failed to record parse-validate attempt progress")


def _record_failed_raw_output(raw_output: str) -> None:
    """Stash the last failed attempt's raw LLM text on the Job row.

    Called right before the parse-validate loop raises its
    exhaustion exception, so the UI can surface a copy-to-clipboard
    affordance for the raw output alongside the human-readable
    error. Stored in ``Job.payload["_failed_raw_output"]`` (same
    JSON column that carries ``_current_attempt`` — no migration).

    No-op outside a handler task. Swallows any DB error so progress
    visibility never blocks the real failure path.
    """
    job_id = current_job_id_var.get()
    if job_id is None:
        return
    try:
        with SessionLocal() as db:
            job = db.get(Job, job_id)
            if job is None:
                return
            payload = dict(job.payload or {})
            payload["_failed_raw_output"] = raw_output
            job.payload = payload
            flag_modified(job, "payload")
            db.commit()
    except Exception:
        logger.exception("Failed to record failed raw output on job row")


async def run_parse_validate_loop(
    *,
    root_tag: str,
    system_prompt: str,
    cli_config: "CliInvocationConfig",
    prior_pending: str | None,
    render_prompt: Callable[..., str],
    validate: Callable[[TagNode, str], None],
    exhausted_exception_cls: type[Exception],
    log_handler_name: str,
) -> tuple[GenerationResult, list[GenerationResult]]:
    """Run the parse-validate retry loop for a bootstrap generation handler.

    ``render_prompt`` is a keyword callable: ``render_prompt(*,
    prior_pending: str | None, parse_error: str | None) -> str``.
    Callers bind their tier-specific inputs (``input_doc``,
    ``features_summary``, etc.) into the closure before calling this
    helper. Each retry substitutes the previous raw LLM output for
    ``prior_pending`` so the model sees its own last attempt.

    ``validate`` takes a parsed ``TagNode`` and raises
    :class:`ParseError` or :class:`ValidationError` on failure.
    Callers bind the validator function plus its tier-specific
    kwargs (``known_feature_ids``, ``known_top_level_resp_ids``,
    etc.) into the closure.

    Returns ``(final_result, all_attempts_including_retries)``. The
    final result is guaranteed to parse + validate cleanly. Raises
    ``exhausted_exception_cls`` if every attempt fails, carrying
    the final parse/validation error as context.

    The shared transient CLI retry wrapper handles upstream 5xx /
    crash failures within each attempt — those retries happen
    underneath this loop and do not consume the parse-validate
    budget.
    """
    attempts: list[GenerationResult] = []
    parse_error: str | None = None

    # MAX_PARSE_RETRIES + 1 total attempts: one initial attempt
    # plus up to MAX_PARSE_RETRIES retries that feed the previous
    # parse/validation error back into the prompt.
    max_attempts = MAX_PARSE_RETRIES + 1
    for attempt_idx in range(max_attempts):
        # Record progress on the Job row before kicking off the LLM
        # call so a UI polling the bootstrap endpoint sees "attempt
        # N of M" for the duration of the call, not just after it.
        _record_attempt_progress(attempt_idx + 1, max_attempts)

        # On retries, use the *previous* attempt's raw text as the
        # "prior pending" so the LLM sees what it produced and can
        # correct it. First attempt uses the caller-supplied prior.
        effective_prior_pending = attempts[-1].text if attempt_idx > 0 else prior_pending

        user_prompt = render_prompt(
            prior_pending=effective_prior_pending,
            parse_error=parse_error,
        )
        try:
            result = await _call_cli_with_transient_retry(
                prompt=user_prompt,
                system_prompt=system_prompt,
                tools=CLI_TOOLS,
                config=cli_config,
            )
        except CliError as cli_exc:
            # Fatal CLI failures (budget / context-window / auth /
            # content-policy / invalid-arg) and exhausted transient
            # retries land here. If the subprocess managed to emit
            # any stdout before the abort, preserve it on the Job
            # row so the UI's raw-output copy button surfaces the
            # partial draft alongside the human-readable error.
            # Especially useful on CliBudgetExceededError /
            # max-output-tokens aborts where most of a valid draft
            # is sitting in stdout.
            partial = (cli_exc.partial_output or "").strip()
            if partial:
                logger.warning(
                    "%s CLI error carried %d chars of partial output; "
                    "persisting to Job._failed_raw_output",
                    log_handler_name,
                    len(partial),
                )
                _record_failed_raw_output(partial)
            raise
        attempts.append(result)

        try:
            tree = extract_tag_tree(result.text, root_tag)
            validate(tree, result.text)
        except (ParseError, ValidationError) as exc:
            parse_error = str(exc)
            logger.warning(
                "%s attempt %d/%d failed parse-validate: %s",
                log_handler_name,
                attempt_idx + 1,
                MAX_PARSE_RETRIES + 1,
                parse_error,
            )
            continue

        # Success.
        return result, attempts

    # Exhausted all attempts.
    if attempts:
        _record_failed_raw_output(attempts[-1].text)
    raise exhausted_exception_cls(
        f"{log_handler_name} failed parse-validate after "
        f"{MAX_PARSE_RETRIES + 1} attempts. Final error: {parse_error}"
    )


def persist_draft(
    project_id: str,
    node_id: str,
    section: str,
    validated_output: "GenerationResult",
    attempts: list["GenerationResult"],
    prior_pending_id: str | None,
    log_handler_name: str,
    review_job_type: str = "",
    *,
    prior_discard_reason: Literal["user_regen", "auto_revision"] = "user_regen",
    enqueue_async_review: bool = True,
) -> str:
    """Phase 3: persist the validated draft + telemetry in one transaction.

    Shared by all generation handlers — the only variation is the
    ``section`` tag for telemetry rows and the ``node_id`` /
    ``log_handler_name`` for logging.

    Phase 8: if ``review_job_type`` is provided, enqueue one review
    job after the commit. The review handler re-assembles context
    from the DB state, calls the CLI, and emits
    ``DraftReviewUpdated`` on success. Any prior-draft review job
    is cancelled when the prior draft is discarded so it can't
    race with the fresh draft's review.

    Phase 12 auto-revision: callers driving the inline revision
    loop override two knobs. ``prior_discard_reason`` tags the
    prior pending's discard event — ``"auto_revision"`` when this
    pass is itself an auto-revision intermediate (the prior was
    landed mid-loop and the user never saw it as baseline).
    ``enqueue_async_review=False`` suppresses the usual async
    review enqueue; the caller is handling review inline and will
    enqueue the async review for the *final* pass on its own.

    Returns the newly-persisted draft's id so callers driving the
    auto-revision loop can target the inline review against it
    without re-querying the DB.
    """
    import secrets

    from backend.database import SessionLocal
    from backend.graph import events as ev
    from backend.graph.parsers.change_summary import extract_change_summary
    from backend.graph.reducer import append_event
    from backend.models.telemetry import GenerationTelemetry
    from backend.pipeline import queue as pipeline_queue

    db = SessionLocal()
    try:
        if prior_pending_id is not None:
            append_event(
                db,
                project_id,
                ev.DraftDiscarded(
                    draft_id=prior_pending_id,
                    reason=prior_discard_reason,
                ),
            )
            # Cancel any in-flight review job for the discarded
            # draft so a late-arriving review can't land on the
            # wrong draft row.
            if review_job_type:
                pipeline_queue.cancel_jobs_by_type(
                    db,
                    review_job_type,
                    project_id=project_id,
                    draft_id=prior_pending_id,
                )

        new_draft_id = f"draft_{secrets.token_hex(8)}"
        # Phase 14 — when this draft is being generated as part of a
        # tier-op or per-node operation, the originating
        # ``Job.batch_id`` rides on the job's payload (placed there
        # by ``pipeline_queue.enqueue``). Read it from the running
        # Job row so multi-draft tier-ops collapse onto one
        # ``Draft.batch_id``. Fall back to a fresh per-draft mint
        # only when no payload-batch is present (legacy queued jobs
        # from before the column landed, or system-side cascade
        # enqueues that didn't mint a batch).
        new_batch_id = _resolve_draft_batch_id()
        # Phase 13 — lift the generator's ``<change-summary>`` body
        # into its own column and strip the tag from the stored draft
        # content so downstream readers (diff view, mint handler
        # re-parse, validators) see only document prose. Missing
        # / empty tags return ``("", unchanged)`` — fan-in drafts are
        # out of scope so they flow through without modification.
        change_summary, stored_content = extract_change_summary(validated_output.text)
        append_event(
            db,
            project_id,
            ev.DraftGenerated(
                draft_id=new_draft_id,
                target_type="node",
                target_id=node_id,
                content=stored_content,
                batch_id=new_batch_id,
                change_summary=change_summary,
            ),
        )
        for attempt in attempts:
            db.add(
                GenerationTelemetry(
                    project_id=project_id,
                    node_id=node_id,
                    section=section,
                    model=attempt.model,
                    prompt_tokens=attempt.prompt_tokens,
                    completion_tokens=attempt.completion_tokens,
                )
            )
        db.commit()
        logger.info(
            "%s project=%s draft_id=%s committed "
            "(attempts=%d final_prompt=%d final_completion=%d model=%s)",
            log_handler_name,
            project_id,
            new_draft_id,
            len(attempts),
            validated_output.prompt_tokens,
            validated_output.completion_tokens,
            validated_output.model,
        )
        # Phase 8: enqueue AI self-review against the newly-
        # committed draft. Review handler re-assembles tier
        # context and emits ``DraftReviewUpdated`` on success.
        # ``SIEGE_DISABLE_AI_REVIEW=1`` opts out project-wide —
        # used by the chain integration test to keep its stub
        # scope small.
        import os

        if (
            review_job_type
            and enqueue_async_review
            and os.environ.get("SIEGE_DISABLE_AI_REVIEW") != "1"
        ):
            pipeline_queue.enqueue(
                db,
                job_type=review_job_type,
                payload={
                    "project_id": project_id,
                    "node_id": node_id,
                    "draft_id": new_draft_id,
                },
                priority=pipeline_queue.REVIEW_JOB_PRIORITY,
            )
        return new_draft_id
    finally:
        db.close()
