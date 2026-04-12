import asyncio
import logging
import os
import tempfile
import time

from backend.config import settings

logger = logging.getLogger(__name__)

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
            )

    async def _invoke(
        self,
        prompt: str,
        system_prompt: str | None,
        working_dir: str | None,
        model: str | None,
        tools: str | None,
        timeout: int,
        max_budget_usd: float | None,
    ) -> str:
        args = ["claude", "-p", "--output-format", "text"]

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


cli_manager = CLIManager()
