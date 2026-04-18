"""Review prompt for the feature-expansion tier."""

from __future__ import annotations

from backend.graph.prompts.review._shared import (
    render_review_system_prompt,
    review_task_footer,
)
from backend.graph.review_context.expansion import ExpansionContext

_HANDLES = """\
- Are feature names crisp and distinct? Flag overly-broad names \
(e.g. "Dashboard") that don't name the slice of work, and \
excessively granular names that belong inside a larger feature.
- Are intent paragraphs specific enough to drive requirement \
derivation downstream? Flag vague intents ("Support users") and \
restated-name intents.
- Does the feature set cover the input doc's implied scope? \
Flag gaps — concerns the doc describes but the expansion missed.
- Are there duplicated / overlapping features?
- If grouped, do the groups make sense? Flag arbitrary or \
inconsistent grouping.
- Are implicit-flagged features genuinely implicit (inferred but \
necessary), or should they be explicit?
"""

_ARCHITECTURE = """\
- Is the granularity right-sized for this project? Expansion \
too-fine causes downstream fan-out; too-coarse loses detail \
requirements need.
- Is the feature axis the right decomposition of the product? \
If the input suggests a different natural axis (workflow, \
persona, data domain), name it.
"""


def render_system_prompt() -> str:
    return render_review_system_prompt(
        artifact_label="``<features>`` expansion",
        scope_label="this project",
        handles_criteria=_HANDLES,
        architecture_criteria=_ARCHITECTURE,
    )


def render_user_prompt(context: ExpansionContext, generated_output: str) -> str:
    parts: list[str] = []
    if context.input_doc.strip():
        parts.append("# Input document (what the generator was extracting from)")
        parts.append("")
        parts.append(context.input_doc.strip())
        parts.append("")
    parts.append("# Generated features (the artifact to review)")
    parts.append("")
    parts.append(generated_output.strip())
    parts.append("")
    parts.append("# Task")
    parts.append("")
    parts.append(review_task_footer())
    return "\n".join(parts).rstrip() + "\n"
