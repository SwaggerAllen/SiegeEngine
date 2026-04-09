"""Artifact summary generation.

Generates concise summaries of artifacts focused on public API, types,
interfaces, and contracts. Summaries are used to fit pipeline prompts
within context budget limits.
"""

import logging

from backend.cli.manager import cli_manager
from backend.config import settings

logger = logging.getLogger(__name__)

SUMMARY_SYSTEM_PROMPT = """\
You are a technical documentation summarizer. Produce a contract summary \
of the provided component/sub-component architecture document.

Include ONLY:
- Public function/method signatures with parameter and return types
- Error codes or failure modes
- Side effects: events emitted, notifications dispatched, state mutations, \
  PubSub topics published or subscribed, queue names
- Data types that appear in public interfaces
- Key behavioral contracts that consumers must know about

Do NOT include:
- Internal module structure or implementation details
- Design rationale, trade-off discussions, or architectural narrative
- Data model details unless they appear in public interfaces
- Testing strategy or performance characteristics
- How the component works internally — only what it exposes

Preserve all function signatures and type definitions verbatim. \
Keep the summary under 20% of the original document length."""

HOTPATH_SYSTEM_PROMPT = """\
You are a technical documentation summarizer. Produce a concise, targeted \
summary of the provided document. The summary will be used as context for a \
pipeline stage that produces a specific output.

Focus on the aspects of this document most relevant to the consuming stage:
- Public API, function signatures, type definitions
- Interfaces and contracts with other components
- Key behavioral notes that affect downstream consumers

Preserve all function signatures and type definitions verbatim. Omit internal \
implementation details not relevant to the consuming stage.

Keep the summary under 20% of the original document length."""


async def generate_summary(
    content: str,
    timeout: int | None = None,
) -> str:
    """Generate a summary for the given content.

    Pure function: content in, summary string out.
    Raises RuntimeError on CLI failure or empty output.
    Raises TimeoutError on CLI timeout.
    Callers are responsible for persisting the result.
    """
    summary = await cli_manager.generate(
        prompt=content,
        system_prompt=SUMMARY_SYSTEM_PROMPT,
        model=None,
        tools="",
        timeout=timeout or settings.cli_timeout_summary,
    )
    if not summary.strip():
        raise RuntimeError("Summary generation returned empty output")
    logger.info(
        "Summary generated: %d chars -> %d chars",
        len(content),
        len(summary),
    )
    return summary


async def generate_hotpath_summary(
    content: str,
    stage_output_type: str,
    component_key: str | None,
    timeout: int | None = None,
) -> str | None:
    """Generate a targeted summary for budget-constrained direct inputs.

    This is called on the hot path when direct inputs exceed the context
    budget. The summary is stage-aware — tailored to what the consuming
    stage needs.

    Returns the summary text, or None on failure. The caller is
    responsible for persisting the result.
    """
    context_hint = f"Consuming stage output type: {stage_output_type}"
    if component_key:
        context_hint += f"\nTarget component: {component_key}"

    prompt = f"{context_hint}\n\n---\n\nDOCUMENT TO SUMMARIZE:\n\n{content}"

    try:
        summary = await cli_manager.generate(
            prompt=prompt,
            system_prompt=HOTPATH_SYSTEM_PROMPT,
            model=None,
            tools="",  # no tools needed
            timeout=timeout or settings.cli_timeout_summary,
        )
        logger.info(
            "Hot-path summary generated: %d chars -> %d chars",
            len(content),
            len(summary),
        )
        return summary
    except Exception:
        logger.warning("Hot-path summary generation failed", exc_info=True)
        return None
