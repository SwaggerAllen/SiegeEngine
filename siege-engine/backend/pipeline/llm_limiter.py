import asyncio
import logging

from anthropic import RateLimitError

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


async def rate_limited_invoke(model, messages):
    """Invoke an LLM model with concurrency limiting and retry on rate-limit errors."""
    sem = _get_semaphore()
    max_attempts = settings.llm_retry_max_attempts
    base_delay = settings.llm_retry_base_delay

    async with sem:
        for attempt in range(max_attempts):
            try:
                return await model.ainvoke(messages)
            except RateLimitError:
                if attempt == max_attempts - 1:
                    raise
                delay = base_delay * (2 ** attempt)
                logger.warning(
                    "Rate limited (attempt %d/%d), retrying in %.1fs",
                    attempt + 1, max_attempts, delay,
                )
                await asyncio.sleep(delay)
