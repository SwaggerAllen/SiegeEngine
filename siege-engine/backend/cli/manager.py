import asyncio
import logging
import os
import tempfile
import time

from backend.config import settings

logger = logging.getLogger(__name__)

_pipeline_semaphore: asyncio.Semaphore | None = None
_chat_semaphore: asyncio.Semaphore | None = None
_semaphore_loop: asyncio.AbstractEventLoop | None = None


def _get_semaphore(kind: str = "pipeline") -> asyncio.Semaphore:
    global _pipeline_semaphore, _chat_semaphore, _semaphore_loop
    loop = asyncio.get_running_loop()
    if _semaphore_loop is not loop:
        _pipeline_semaphore = asyncio.Semaphore(settings.max_concurrent_llm_calls)
        _chat_semaphore = asyncio.Semaphore(settings.max_concurrent_chat_calls)
        _semaphore_loop = loop
    if kind == "chat":
        return _chat_semaphore
    return _pipeline_semaphore


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

        # Write system prompt to a temp file to avoid ARG_MAX limits
        # (pinned artifacts can make the system prompt very large).
        sp_file = None
        if system_prompt:
            sp_file = tempfile.NamedTemporaryFile(
                mode="w", suffix=".txt", delete=False
            )
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

        if execution_id:
            self._running_procs[execution_id] = proc

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
            if execution_id:
                self._running_procs.pop(execution_id, None)
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
        Used for the chat interface. Gated by a separate chat semaphore
        so chat and pipeline never block each other.
        """
        sem = _get_semaphore("chat")
        await sem.acquire()
        try:
            async for line in self._stream_cli(
                prompt,
                system_prompt,
                working_dir,
                model,
                session_id,
                resume,
                tools,
            ):
                yield line
        finally:
            sem.release()

    async def _stream_cli(
        self,
        prompt: str,
        system_prompt: str | None,
        working_dir: str | None,
        model: str | None,
        session_id: str | None,
        resume: bool,
        tools: str | None,
    ):
        """Inner generator that actually runs the CLI subprocess."""
        args = ["claude"]

        if resume and session_id:
            args.extend(["--resume", session_id])

        # Pass prompt via stdin (not as a CLI arg) to avoid E2BIG when
        # the conversation history or pinned documents make it large.
        args.extend(["-p", "-", "--output-format", "stream-json", "--verbose"])

        # Write system prompt to a temp file to avoid ARG_MAX limits.
        sp_file = None
        if system_prompt:
            sp_file = tempfile.NamedTemporaryFile(
                mode="w", suffix=".txt", delete=False
            )
            sp_file.write(system_prompt)
            sp_file.close()
            args.extend(["--system-prompt-file", sp_file.name])
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
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=working_dir,
            env=env,
        )

        # Feed prompt via stdin so it's not constrained by ARG_MAX
        proc.stdin.write(prompt.encode("utf-8"))
        await proc.stdin.drain()
        proc.stdin.close()

        line_count = 0
        try:
            async for line in proc.stdout:
                decoded = line.decode("utf-8", errors="replace").strip()
                if decoded:
                    line_count += 1
                    if line_count <= 5:
                        logger.info("Chat CLI stdout line %d: %s", line_count, decoded[:300])
                    yield decoded
        finally:
            if proc.returncode is None:
                proc.kill()
            await proc.wait()

            # Log stderr for debugging
            if proc.stderr:
                stderr_data = await proc.stderr.read()
                stderr_text = stderr_data.decode("utf-8", errors="replace").strip()
                if stderr_text:
                    logger.warning(
                        "Chat CLI stderr (rc=%s): %s", proc.returncode, stderr_text[:2000]
                    )

            if sp_file:
                try:
                    os.unlink(sp_file.name)
                except OSError:
                    pass

            logger.info(
                "Chat CLI streaming done: %d lines yielded, rc=%s", line_count, proc.returncode
            )


cli_manager = CLIManager()
