"""Artifact summary generation.

Generates concise summaries of artifacts focused on public API, types,
interfaces, and contracts. Summaries are used to fit pipeline prompts
within context budget limits.
"""

import logging

from sqlalchemy.orm import Session

from backend.cli.manager import cli_manager
from backend.config import settings
from backend.models import Artifact

logger = logging.getLogger(__name__)

SUMMARY_SYSTEM_PROMPT = """\
You are a technical documentation summarizer. Produce a concise summary of the \
provided document. Focus on:

- Public API: function/method signatures, endpoint definitions, command interfaces
- Type definitions: structs, classes, interfaces, enums, type aliases
- Key contracts: preconditions, postconditions, invariants, error handling behavior
- Component boundaries: what this component exposes to and expects from others

Preserve all function signatures, type definitions, and interface declarations \
verbatim — do not paraphrase them. Omit internal implementation details, \
rationale, and prose that does not define the component's external contract.

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


async def generate_summary(artifact_id: str, db: Session) -> str | None:
    """Generate and store a summary for the given artifact.

    Uses the pipeline semaphore via cli_manager.generate() to honor
    concurrency limits. Returns the summary text, or None on failure.
    """
    artifact = db.get(Artifact, artifact_id)
    if not artifact or not artifact.content:
        return None

    try:
        summary = await cli_manager.generate(
            prompt=artifact.content,
            system_prompt=SUMMARY_SYSTEM_PROMPT,
            model=None,  # use default
            tools='""',  # no tools needed
            timeout=settings.cli_timeout_summary,
        )
        artifact.summary = summary
        db.flush()
        logger.info(
            "Summary generated for artifact %s: %d chars -> %d chars",
            artifact_id,
            len(artifact.content),
            len(summary),
        )
        return summary
    except Exception:
        logger.warning("Summary generation failed for artifact %s", artifact_id, exc_info=True)
        return None


async def generate_hotpath_summary(
    content: str,
    stage_output_type: str,
    component_key: str | None,
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
            tools='""',
            timeout=settings.cli_timeout_summary,
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
