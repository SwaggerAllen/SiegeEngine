"""Unit tests for ``backend.cli.manager._classify_cli_failure``.

Covers the fatal-vs-transient split that drives whether
``_call_cli_with_transient_retry`` will loop on a given CLI failure.
Every signal in :data:`backend.cli.manager._FATAL_CLI_SIGNALS`
should land in its subclass; anything unrecognized should fall
through to :class:`CliTransientError` (retryable by default).
"""

from __future__ import annotations

import pytest

from backend.cli.manager import (
    CliAuthError,
    CliBudgetExceededError,
    CliContentPolicyError,
    CliContextWindowError,
    CliError,
    CliInvalidArgumentError,
    CliTransientError,
    _classify_cli_failure,
)


class TestFatalSignals:
    @pytest.mark.parametrize(
        "detail",
        [
            "Budget limit hit: $1.00 exceeded",
            "--max-budget-usd reached",
            "error: Budget exceeded",
            "max_budget_usd flag triggered",
        ],
    )
    def test_budget_phrases_classify_as_budget_exceeded(self, detail: str) -> None:
        exc = _classify_cli_failure(1, detail)
        assert isinstance(exc, CliBudgetExceededError)
        assert isinstance(exc, CliError)
        # Transient is a sibling, not a superclass — must be distinct.
        assert not isinstance(exc, CliTransientError)

    @pytest.mark.parametrize(
        "detail",
        [
            "Prompt exceeds context length",
            "Context window exceeded at 200000 tokens",
            "prompt_too_long: model limit",
            "the prompt is too long for this model",
        ],
    )
    def test_context_window_phrases(self, detail: str) -> None:
        exc = _classify_cli_failure(1, detail)
        assert isinstance(exc, CliContextWindowError)

    @pytest.mark.parametrize(
        "detail",
        [
            "Request blocked by content policy",
            "I cannot help with that request",
            "Sorry, I can't help with this",
            "unable to assist with that request",
        ],
    )
    def test_content_policy_phrases(self, detail: str) -> None:
        exc = _classify_cli_failure(1, detail)
        assert isinstance(exc, CliContentPolicyError)

    @pytest.mark.parametrize(
        "detail",
        [
            "401 Unauthorized",
            "403 Forbidden",
            "Authentication failed: token expired",
            "Invalid API key supplied",
            "Login expired; please re-authenticate",
        ],
    )
    def test_auth_phrases(self, detail: str) -> None:
        exc = _classify_cli_failure(1, detail)
        assert isinstance(exc, CliAuthError)

    @pytest.mark.parametrize(
        "detail",
        [
            "unrecognized arguments: --nope",
            "invalid choice: 'claude-9'",
            "unknown flag: --frobnicate",
            "unknown option: -z",
            "no such option: --magic",
        ],
    )
    def test_invalid_argument_phrases(self, detail: str) -> None:
        exc = _classify_cli_failure(1, detail)
        assert isinstance(exc, CliInvalidArgumentError)


class TestTransientFallback:
    @pytest.mark.parametrize(
        "detail",
        [
            "500 Internal Server Error",
            "529 Overloaded",
            "connection reset by peer",
            "DNS resolution failed",
            "Segmentation fault (core dumped)",
            "some totally unknown failure mode",
            "",
            "(no output)",
        ],
    )
    def test_unrecognized_falls_through_to_transient(self, detail: str) -> None:
        exc = _classify_cli_failure(1, detail)
        assert isinstance(exc, CliTransientError)
        assert isinstance(exc, CliError)

    def test_message_carries_exit_code_and_detail(self) -> None:
        exc = _classify_cli_failure(137, "killed by signal")
        assert "exit 137" in str(exc)
        assert "killed by signal" in str(exc)

    def test_detail_is_case_insensitive(self) -> None:
        # Detection matches on lowercased text so the CLI emitting
        # mixed-case errors (e.g. from an upstream JSON envelope)
        # still classifies correctly.
        exc = _classify_cli_failure(1, "BUDGET EXCEEDED: max-budget reached")
        assert isinstance(exc, CliBudgetExceededError)
