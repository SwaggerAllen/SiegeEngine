import asyncio
import logging
import os

from backend.config import settings

logger = logging.getLogger(__name__)

_semaphore: asyncio.Semaphore | None = None
_semaphore_loop: asyncio.AbstractEventLoop | None = None


def _get_semaphore() -> asyncio.Semaphore:
    global _semaphore, _semaphore_loop
    loop = asyncio.get_running_loop()
    if _semaphore is None or _semaphore_loop is not loop:
        _semaphore = asyncio.Semaphore(settings.max_concurrent_llm_calls)
        _semaphore_loop = loop
    return _semaphore


class CLIManager:
    """Manages Claude CLI subprocess invocations."""

    def __init__(self):
        # Track running processes by execution_id so force-restart can kill them
        self._running_procs: dict[str, asyncio.subprocess.Process] = {}

    async def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        working_dir: str | None = None,
        model: str | None = None,
        tools: str | None = None,
        timeout: int | None = None,
        max_budget_usd: float | None = None,
        execution_id: str | None = None,
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
            timeout: Timeout in seconds. Defaults to cli_timeout_document setting.
            max_budget_usd: Maximum dollar amount for API calls.
            execution_id: Optional execution ID for process tracking/cancellation.
        """
        if timeout is None:
            timeout = settings.cli_timeout_document

        sem = _get_semaphore()
        async with sem:
            return await self._invoke(
                prompt,
                system_prompt,
                working_dir,
                model,
                tools,
                timeout,
                max_budget_usd,
                execution_id,
            )

    def kill_process_for_execution(self, execution_id: str) -> bool:
        """Kill a running CLI process for the given execution. Returns True if killed."""
        proc = self._running_procs.get(execution_id)
        if proc and proc.returncode is None:
            logger.info("Killing CLI process for execution %s (pid=%s)", execution_id, proc.pid)
            proc.kill()
            return True
        return False

    async def _invoke(
        self,
        prompt: str,
        system_prompt: str | None,
        working_dir: str | None,
        model: str | None,
        tools: str | None,
        timeout: int,
        max_budget_usd: float | None,
        execution_id: str | None = None,
    ) -> str:
        args = ["claude", "-p", "--output-format", "text"]

        if system_prompt:
            args.extend(["--system-prompt", system_prompt])
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

        if execution_id:
            self._running_procs[execution_id] = proc

        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(input=prompt.encode("utf-8")),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise TimeoutError(f"Claude CLI timed out after {timeout}s")
        except asyncio.CancelledError:
            proc.kill()
            await proc.wait()
            raise
        finally:
            if execution_id:
                self._running_procs.pop(execution_id, None)

        output = stdout.decode("utf-8", errors="replace")
        err_output = stderr.decode("utf-8", errors="replace")

        if proc.returncode != 0:
            logger.error("CLI failed (rc=%d) stderr: %s", proc.returncode, err_output[:2000])
            logger.error("CLI failed (rc=%d) stdout: %s", proc.returncode, output[:2000])
            detail = err_output.strip() or output.strip() or "(no output)"
            raise RuntimeError(f"Claude CLI failed (exit {proc.returncode}): {detail[:1000]}")

        if err_output:
            logger.debug("CLI stderr: %s", err_output[:500])

        logger.info("CLI invoke complete: %d chars output", len(output))
        return output

    async def generate_streaming(
        self,
        prompt: str,
        system_prompt: str | None = None,
        working_dir: str | None = None,
        model: str | None = None,
        session_id: str | None = None,
        resume: bool = False,
        tools: str | None = None,
    ):
        """
        Run claude CLI and yield streaming JSON output lines.
        Used for the chat interface.
        """
        args = ["claude"]

        if resume and session_id:
            args.extend(["--resume", session_id])

        args.extend(["-p", prompt, "--output-format", "stream-json"])

        if system_prompt:
            args.extend(["--system-prompt", system_prompt])
        if model:
            args.extend(["--model", model])
        if tools is not None:
            args.extend(["--tools", tools])
        if session_id and not resume:
            args.extend(["--session-id", session_id])

        args.append("--dangerously-skip-permissions")

        env = {**os.environ}
        env.pop("CLAUDECODE", None)
        env.pop("ANTHROPIC_API_KEY", None)

        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=working_dir,
            env=env,
        )

        try:
            async for line in proc.stdout:
                decoded = line.decode("utf-8", errors="replace").strip()
                if decoded:
                    yield decoded
        finally:
            if proc.returncode is None:
                proc.kill()
                await proc.wait()


cli_manager = CLIManager()
