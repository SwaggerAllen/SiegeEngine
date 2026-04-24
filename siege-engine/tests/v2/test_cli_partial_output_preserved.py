"""Integration test: CliError partial output lands on ``Job._failed_raw_output``.

When the Claude CLI aborts (budget exceeded, max output tokens, etc)
after emitting some stdout, the manager attaches the bytes to the
raised ``CliError.partial_output``. ``run_parse_validate_loop``
catches ``CliError``, persists the partial text via
``_record_failed_raw_output``, then re-raises. The UI's raw-output
copy button then renders the partial draft for the user alongside
the human-readable error.
"""

from __future__ import annotations

import asyncio
import os

import pytest

os.environ.setdefault("SIEGE_DISABLE_WORKER_LOOP", "1")

try:
    import cryptography.hazmat.bindings._rust  # noqa: F401
except BaseException as _exc:  # pragma: no cover - env-dependent skip
    pytest.skip(
        f"cryptography/cffi environmental issue: {_exc!r}",
        allow_module_level=True,
    )

from backend.cli.config import CliInvocationConfig  # noqa: E402
from backend.cli.manager import (  # noqa: E402
    CliBudgetExceededError,
    CliTransientError,
)
from backend.graph.handlers import _bootstrap_generation  # noqa: E402


class _Boom(Exception):
    pass


class TestCliErrorPersistsPartialOutput:
    """``run_parse_validate_loop`` persists partial_output on CliError."""

    def _run(self, *, exc_to_raise):
        captured: list[str] = []

        async def fake_retry(**kwargs):
            raise exc_to_raise

        def fake_record(raw_output: str) -> None:
            captured.append(raw_output)

        async def _go():
            with pytest.raises(type(exc_to_raise)):
                await _bootstrap_generation.run_parse_validate_loop(
                    root_tag="anything",
                    system_prompt="sys",
                    cli_config=CliInvocationConfig(
                        timeout_seconds=60,
                        max_budget_usd=1.0,
                        max_output_tokens=1000,
                    ),
                    prior_pending=None,
                    render_prompt=lambda *, prior_pending, parse_error: "prompt",
                    validate=lambda tree, raw: None,
                    exhausted_exception_cls=_Boom,
                    log_handler_name="test_handler",
                )

        # ``_bootstrap_generation`` pulls ``_call_cli_with_transient_retry``
        # into its own namespace via ``from ... import ...``, so we patch
        # the rebound name on that module (not the source module) and the
        # in-loop call site picks up the stub.
        orig_retry = _bootstrap_generation._call_cli_with_transient_retry
        _bootstrap_generation._call_cli_with_transient_retry = fake_retry
        orig_record = _bootstrap_generation._record_failed_raw_output
        _bootstrap_generation._record_failed_raw_output = fake_record
        try:
            asyncio.run(_go())
        finally:
            _bootstrap_generation._call_cli_with_transient_retry = orig_retry
            _bootstrap_generation._record_failed_raw_output = orig_record

        return captured

    def test_fatal_budget_error_records_partial(self) -> None:
        partial = "<sysarch><techspec>truncated mid-paragraph</techspec>"
        exc = CliBudgetExceededError("budget hit", partial_output=partial)
        captured = self._run(exc_to_raise=exc)
        assert captured == [partial]

    def test_transient_exhaustion_records_partial(self) -> None:
        # Transient errors that have exhausted the retry wrapper land
        # in the parse-validate loop's CliError handler too.
        partial = "partial stream"
        exc = CliTransientError("500 upstream overload", partial_output=partial)
        captured = self._run(exc_to_raise=exc)
        assert captured == [partial]

    def test_empty_partial_skips_the_record_call(self) -> None:
        # No stdout came through before the abort — skip the record
        # call so we don't overwrite a prior attempt's raw output
        # with an empty string.
        exc = CliBudgetExceededError("budget hit", partial_output="")
        captured = self._run(exc_to_raise=exc)
        assert captured == []

    def test_whitespace_only_partial_is_treated_as_empty(self) -> None:
        exc = CliBudgetExceededError("budget hit", partial_output="   \n\n  ")
        captured = self._run(exc_to_raise=exc)
        assert captured == []
