import asyncio
import json
import logging
import os
import tempfile
import time
from dataclasses import dataclass

from backend.config import settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GenerationResult:
    """Result of a generation call that captured token usage.

    Returned by :meth:`CLIManager.generate_with_usage`. The ``text``
    field is the model's response; the remaining fields are
    observability plumbing surfaced in the UI alongside the generated
    artifact (see ``docs/architecture/v2-rearchitecture.md``
    §Generation telemetry).

    All token / model fields are best-effort — if the CLI's JSON
    output omits them (older versions, a parse error), we log a
    warning and fall back to zeros + ``"unknown"`` so telemetry is
    never load-bearing on generation success.
    """

    text: str
    prompt_tokens: int
    completion_tokens: int
    model: str


class CliError(RuntimeError):
    """Base class for Claude CLI subprocess failures.

    Inherits :class:`RuntimeError` so existing ``except RuntimeError``
    sites continue to catch the whole family. The subclasses below
    carry one bit of semantics that matters to the retry wrapper:
    whether the error is worth retrying. Any ``CliError`` subclass
    that is *not* :class:`CliTransientError` must be treated as fatal
    — retrying either burns budget for no chance of success (budget,
    context window, content policy) or won't resolve without user
    action (auth, invalid argument).
    """


class CliTransientError(CliError):
    """CLI failed in a way that's worth retrying.

    Upstream 5xx / 529 overload, rate limits, connection resets,
    unexpected CLI process crashes — anything where waiting and
    retrying has a reasonable chance of success. The transient
    retry wrapper catches this class only.

    Default classification for any ``RuntimeError``-shaped CLI
    failure we don't recognize — "retry unless we're sure it's
    fatal" is the safer default for CLI bugs we haven't seen yet.
    """


class CliBudgetExceededError(CliError):
    """CLI aborted because it hit the ``--max-budget-usd`` limit.

    Fatal — every retry passes the same budget and fails the same
    way. User action: bump the project's ``cli_max_budget_usd``
    setting or split the generation into smaller pieces.
    """


class CliAuthError(CliError):
    """CLI rejected the request for auth reasons.

    Fatal — the credentials need rotating or the login needs
    refreshing. Retrying without user action changes nothing.
    """


class CliContextWindowError(CliError):
    """CLI reported the prompt exceeded the model's context window.

    Fatal — the same prompt will always be too long. User action:
    shrink the context budget or drop partitions that aren't
    pulling their weight.
    """


class CliContentPolicyError(CliError):
    """CLI / model declined to respond on content-policy grounds.

    Fatal — a refusal from the model is deterministic for the
    same prompt. Retrying wastes budget. User action: inspect
    and revise the upstream content that tripped the refusal.
    """


class CliInvalidArgumentError(CliError):
    """CLI rejected the invocation shape.

    Fatal — a bad flag, unsupported model, or invalid tool spec
    won't fix itself on retry. Usually a programming error in
    the pipeline, not a runtime condition.
    """


# Lowercase substring signals per fatal class. Order matters — first
# match wins, so put the more specific patterns ahead of generic ones.
# Detection runs against the combined stderr+stdout text from the
# failing subprocess and is deliberately loose: we'd rather classify
# a fatal error as transient (wasting a retry budget) than classify
# a transient error as fatal (stalling forever on a blip).
_FATAL_CLI_SIGNALS: tuple[tuple[tuple[str, ...], type[CliError]], ...] = (
    (
        ("max-budget", "budget exceeded", "budget limit", "max_budget_usd"),
        CliBudgetExceededError,
    ),
    (
        ("context length", "context window", "prompt is too long", "prompt_too_long"),
        CliContextWindowError,
    ),
    (
        ("content policy", "i cannot help", "i can't help", "unable to assist"),
        CliContentPolicyError,
    ),
    (
        (
            "unauthorized",
            "authentication failed",
            "invalid api key",
            "login expired",
            "401 unauthorized",
            "403 forbidden",
        ),
        CliAuthError,
    ),
    (
        (
            "unrecognized arguments",
            "invalid choice",
            "unknown flag",
            "unknown option",
            "no such option",
        ),
        CliInvalidArgumentError,
    ),
)


def _classify_cli_failure(returncode: int | None, detail: str) -> CliError:
    """Return the most specific :class:`CliError` for a non-zero CLI exit.

    Matches ``detail`` (lowercased stderr+stdout) against
    :data:`_FATAL_CLI_SIGNALS`. Unrecognized failures fall through
    to :class:`CliTransientError` so the retry wrapper gets a chance
    — the safer default when we don't recognize the error.
    """
    needle = detail.lower()
    for patterns, cls in _FATAL_CLI_SIGNALS:
        if any(p in needle for p in patterns):
            return cls(f"Claude CLI failed (exit {returncode}): {detail[:1000]}")
    return CliTransientError(f"Claude CLI failed (exit {returncode}): {detail[:1000]}")


_semaphore: asyncio.Semaphore | None = None
_semaphore_loop: asyncio.AbstractEventLoop | None = None


def _build_subprocess_env(thinking_effort: str | None) -> dict[str, str]:
    """Construct the env dict for a CLI subprocess invocation.

    Copies the parent process environment, strips SIEGE-specific
    secrets (``ANTHROPIC_API_KEY``, ``CLAUDECODE`` signal) the CLI
    must not inherit, and sets / clears ``CLAUDE_CODE_EFFORT_LEVEL``
    based on the per-call ``thinking_effort`` argument.

    Phase-11 followup B6: the three top-of-chain tiers (expansion,
    reqs, sysarch) pass ``thinking_effort="max"`` so their single
    calls run at max effort; propagation tiers leave it unset so
    their CLI budget isn't consumed by thinking tokens. Scoping
    via this per-call env (not the process env) means concurrent
    handler calls don't race each other's settings.
    """
    env = {**os.environ}
    env.pop("CLAUDECODE", None)
    env.pop("ANTHROPIC_API_KEY", None)
    if thinking_effort is not None:
        env["CLAUDE_CODE_EFFORT_LEVEL"] = thinking_effort
    else:
        env.pop("CLAUDE_CODE_EFFORT_LEVEL", None)
    return env


def _get_semaphore() -> asyncio.Semaphore:
    global _semaphore, _semaphore_loop
    loop = asyncio.get_running_loop()
    if _semaphore_loop is not loop:
        _semaphore = asyncio.Semaphore(settings.max_concurrent_llm_calls)
        _semaphore_loop = loop
    assert _semaphore is not None
    return _semaphore


class CLIManager:
    """Manages Claude CLI subprocess invocations."""

    async def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        working_dir: str | None = None,
        model: str | None = None,
        tools: str | None = None,
        timeout: int | None = None,
        max_budget_usd: float | None = None,
        thinking_effort: str | None = None,
    ) -> str:
        """
        Run claude CLI with a prompt and return the output text.

        Args:
            prompt: The user prompt to send.
            system_prompt: Optional system prompt.
            working_dir: Working directory for the CLI subprocess.
            model: Model override (e.g. "claude-sonnet-4-20250514").
            tools: Tool specification. Use '""' to disable all tools,
                   "default" for all tools, or specific tools like "Bash,Edit,Read".
                   None = CLI default (all tools).
            timeout: Timeout in seconds. Defaults to cli_timeout setting.
            max_budget_usd: Maximum dollar amount for API calls.
            thinking_effort: When set (e.g. ``"max"``), forwarded to
                the CLI subprocess as ``CLAUDE_CODE_EFFORT_LEVEL``.
                Scoped to the single call — doesn't affect other
                concurrent invocations or the parent process env.
                Used on the first three tiers (expansion, reqs,
                sysarch) where deep thinking materially improves
                downstream quality; deliberately unset on propagation
                tiers to keep their budgets from blowing up (see
                Phase-11 followup B6).
        """
        if timeout is None:
            timeout = settings.cli_timeout

        async with _get_semaphore():
            return await self._invoke(
                prompt,
                system_prompt,
                working_dir,
                model,
                tools,
                timeout,
                max_budget_usd,
                output_format="text",
                thinking_effort=thinking_effort,
            )

    async def generate_with_usage(
        self,
        prompt: str,
        system_prompt: str | None = None,
        working_dir: str | None = None,
        model: str | None = None,
        tools: str | None = None,
        timeout: int | None = None,
        max_budget_usd: float | None = None,
        thinking_effort: str | None = None,
    ) -> GenerationResult:
        """Run claude CLI with ``--output-format json`` and return text + usage.

        Same semantics as :meth:`generate` but uses the CLI's JSON
        output mode so the returned ``GenerationResult`` carries
        prompt/completion token counts and the model name. Used by
        handlers that want to record telemetry for the UI
        (``docs/architecture/v2-rearchitecture.md`` §Generation
        telemetry).

        ``thinking_effort`` — same semantics as :meth:`generate`.
        When set, forwarded to the CLI subprocess as
        ``CLAUDE_CODE_EFFORT_LEVEL``; scoped to the single call.

        Token-usage extraction is best-effort: if the CLI's JSON
        shape omits the usage fields or parse fails, we log a warning
        and return zeros + ``model="unknown"`` rather than fail the
        generation. Telemetry is observability, not correctness — a
        missing row should never block a draft from landing.
        """
        if timeout is None:
            timeout = settings.cli_timeout

        async with _get_semaphore():
            raw = await self._invoke(
                prompt,
                system_prompt,
                working_dir,
                model,
                tools,
                timeout,
                max_budget_usd,
                output_format="json",
                thinking_effort=thinking_effort,
            )
        return _parse_json_result(raw, fallback_model=model)

    async def _invoke(
        self,
        prompt: str,
        system_prompt: str | None,
        working_dir: str | None,
        model: str | None,
        tools: str | None,
        timeout: int,
        max_budget_usd: float | None,
        output_format: str = "text",
        thinking_effort: str | None = None,
    ) -> str:
        args = ["claude", "-p", "--output-format", output_format]

        # Write system prompt to a temp file to avoid ARG_MAX limits
        # (pinned artifacts can make the system prompt very large).
        sp_file = None
        if system_prompt:
            sp_file = tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False)
            sp_file.write(system_prompt)
            sp_file.close()
            args.extend(["--system-prompt-file", sp_file.name])
        if model:
            args.extend(["--model", model])
        if tools is not None:
            args.extend(["--tools", tools])
        if max_budget_usd is not None:
            args.extend(["--max-budget-usd", str(max_budget_usd)])

        # Skip permission prompts for automated server use
        args.append("--dangerously-skip-permissions")

        # Don't persist sessions for pipeline generation
        args.append("--no-session-persistence")

        env = _build_subprocess_env(thinking_effort)

        logger.info(
            "CLI invoke: model=%s, tools=%s, cwd=%s, timeout=%ds (using CLI login credentials)",
            model or "default",
            tools or "default",
            working_dir or ".",
            timeout,
        )

        proc = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=working_dir,
            env=env,
        )

        assert proc.stdin is not None
        assert proc.stdout is not None
        assert proc.stderr is not None

        t0 = time.monotonic()
        try:
            # Write prompt to stdin, then close it so the CLI can start
            proc.stdin.write(prompt.encode("utf-8"))
            await proc.stdin.drain()
            proc.stdin.close()

            # Wait for process to EXIT (not for pipes to close — child
            # processes may hold pipes open long after the CLI exits).
            try:
                await asyncio.wait_for(proc.wait(), timeout=timeout)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                raise TimeoutError(f"Claude CLI timed out after {timeout}s")

            t_exit = time.monotonic() - t0
            logger.info(
                "CLI process exited in %.1fs (rc=%s), reading pipes...",
                t_exit,
                proc.returncode,
            )

            # Process exited — read remaining pipe data with a short timeout
            # (child processes may still hold pipes open briefly).
            try:
                stdout = await asyncio.wait_for(proc.stdout.read(), timeout=10)
            except asyncio.TimeoutError:
                logger.warning(
                    "CLI stdout read timed out after process exit (child procs holding pipe?)"
                )
                stdout = b""
            try:
                stderr = await asyncio.wait_for(proc.stderr.read(), timeout=5)
            except asyncio.TimeoutError:
                stderr = b""

        except asyncio.CancelledError:
            proc.kill()
            await proc.wait()
            raise
        finally:
            if sp_file:
                try:
                    os.unlink(sp_file.name)
                except OSError:
                    pass

        t_total = time.monotonic() - t0
        output = stdout.decode("utf-8", errors="replace")
        err_output = stderr.decode("utf-8", errors="replace")

        if proc.returncode != 0:
            logger.error("CLI failed (rc=%d) stderr: %s", proc.returncode, err_output[:2000])
            logger.error("CLI failed (rc=%d) stdout: %s", proc.returncode, output[:2000])
            detail = err_output.strip() or output.strip() or "(no output)"
            # Classify into fatal vs transient so the retry wrapper
            # can skip futile retries (budget, context window, auth,
            # content policy, invalid arg) while still retrying real
            # blips (5xx, rate limits, network resets, crashes).
            raise _classify_cli_failure(proc.returncode, detail)

        if err_output:
            logger.debug("CLI stderr: %s", err_output[:500])

        logger.info(
            "CLI invoke complete: %d chars in %.1fs (exit at %.1fs)",
            len(output),
            t_total,
            t_exit,
        )
        return output


def _parse_json_result(raw: str, fallback_model: str | None) -> GenerationResult:
    """Parse the ``--output-format json`` single-result payload.

    The claude CLI emits a JSON object whose exact shape varies
    between versions — we look for the common fields and fall back
    gracefully when any are absent. The fields we look for:

    * ``result`` or ``text`` — the generated content
    * ``usage.input_tokens`` / ``usage.output_tokens`` —
      or, as older CLIs used, ``usage.prompt_tokens`` /
      ``usage.completion_tokens``
    * ``model`` at the top level — else the caller-supplied override,
      else ``"unknown"``

    Any parse error is logged and swallowed; we return a best-effort
    ``GenerationResult`` rather than fail the generation. Telemetry
    is observability, not correctness.
    """
    try:
        doc = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.warning(
            "CLI JSON output failed to parse (%s); returning raw text with zeroed usage",
            exc,
        )
        return GenerationResult(
            text=raw,
            prompt_tokens=0,
            completion_tokens=0,
            model=fallback_model or "unknown",
        )

    text = ""
    if isinstance(doc, dict):
        text = str(doc.get("result") or doc.get("text") or "")

    usage = doc.get("usage") if isinstance(doc, dict) else None
    prompt_tokens = 0
    completion_tokens = 0
    if isinstance(usage, dict):
        prompt_tokens = int(usage.get("input_tokens") or usage.get("prompt_tokens") or 0)
        completion_tokens = int(usage.get("output_tokens") or usage.get("completion_tokens") or 0)

    model_name = str(
        (doc.get("model") if isinstance(doc, dict) else None) or fallback_model or "unknown"
    )

    if not text:
        logger.warning("CLI JSON output had no 'result' or 'text' field; returning empty")
    if usage is None:
        logger.debug("CLI JSON output had no 'usage' field; tokens recorded as 0")

    return GenerationResult(
        text=text,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        model=model_name,
    )


cli_manager = CLIManager()
