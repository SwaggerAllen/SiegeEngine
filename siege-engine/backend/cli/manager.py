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


_semaphore: asyncio.Semaphore | None = None
_semaphore_loop: asyncio.AbstractEventLoop | None = None


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
    ) -> GenerationResult:
        """Run claude CLI with ``--output-format json`` and return text + usage.

        Same semantics as :meth:`generate` but uses the CLI's JSON
        output mode so the returned ``GenerationResult`` carries
        prompt/completion token counts and the model name. Used by
        handlers that want to record telemetry for the UI
        (``docs/architecture/v2-rearchitecture.md`` §Generation
        telemetry).

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

        # Pass full env with CLAUDECODE stripped; CLI uses its own login credentials
        env = {**os.environ}
        env.pop("CLAUDECODE", None)
        env.pop("ANTHROPIC_API_KEY", None)
        # Pipeline generations are worth burning extra thinking budget
        # on — they run once and are cached as approved content. Force
        # max effort unconditionally so this can't be forgotten in a
        # deployment env. Parent-process overrides don't apply.
        env["CLAUDE_CODE_EFFORT_LEVEL"] = "max"

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
            raise RuntimeError(f"Claude CLI failed (exit {proc.returncode}): {detail[:1000]}")

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
