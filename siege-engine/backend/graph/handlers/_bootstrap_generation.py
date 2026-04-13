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
        cli_timeout_seconds=cli_timeout_seconds,
        prior_pending=prior_pending,
        render_prompt=_render,
        validate=_validate,
        exhausted_exception_cls=FeatureExpansionParseRetryExhausted,
        log_handler_name="generate_feature_expansion",
    )
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from backend.cli.manager import GenerationResult
from backend.graph.handlers.feature_expansion import (
    CLI_MAX_BUDGET_USD,
    CLI_TOOLS,
    MAX_PARSE_RETRIES,
    _call_cli_with_transient_retry,
)
from backend.graph.parsers.validators import ValidationError
from backend.graph.parsers.xml_sections import ParseError, TagNode, extract_tag_tree

logger = logging.getLogger(__name__)


async def run_parse_validate_loop(
    *,
    root_tag: str,
    system_prompt: str,
    cli_timeout_seconds: int,
    prior_pending: str | None,
    render_prompt: Callable[..., str],
    validate: Callable[[TagNode], None],
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
    for attempt_idx in range(MAX_PARSE_RETRIES + 1):
        # On retries, use the *previous* attempt's raw text as the
        # "prior pending" so the LLM sees what it produced and can
        # correct it. First attempt uses the caller-supplied prior.
        effective_prior_pending = attempts[-1].text if attempt_idx > 0 else prior_pending

        user_prompt = render_prompt(
            prior_pending=effective_prior_pending,
            parse_error=parse_error,
        )
        result = await _call_cli_with_transient_retry(
            prompt=user_prompt,
            system_prompt=system_prompt,
            tools=CLI_TOOLS,
            timeout=cli_timeout_seconds,
            max_budget_usd=CLI_MAX_BUDGET_USD,
        )
        attempts.append(result)

        try:
            tree = extract_tag_tree(result.text, root_tag)
            validate(tree)
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
    raise exhausted_exception_cls(
        f"{log_handler_name} failed parse-validate after "
        f"{MAX_PARSE_RETRIES + 1} attempts. Final error: {parse_error}"
    )
