"""Review prompt for the requirements tier."""

from __future__ import annotations

from backend.graph.prompts.review._shared import (
    render_review_system_prompt,
    review_task_footer,
)
from backend.graph.review_context.requirements import RequirementsContext

_HANDLES = """\
- Are responsibility names distinctive and specific to the \
system-level work? Flag names that restate a feature, names \
too abstract for sysarch to map to a component, or names that \
collide with siblings.
- Are intents specific about the system-side work (mechanism / \
data / guarantee) rather than user-facing behavior the \
features already describe? Flag intents that just paraphrase a \
feature.
- Does the responsibility set cover the feature set? Every \
feature's system-side needs should map to at least one \
responsibility (possibly shared across features). Flag missing \
coverage.
- Are ``<covers>`` references valid? Every feat_* id must exist \
in the feature set.
- Are there responsibilities that duplicate or overlap?
"""

_ARCHITECTURE = """\
- Is the axis right? Requirements should rotate user-facing \
feature intents into system-level responsibilities. Flag resps \
still framed in user-outcome terms.
- Is the decomposition the right level for sysarch? Too-fine \
creates a component explosion; too-coarse collapses distinct \
concerns.
- Are cross-cutting concerns (auth, audit, observability) \
handled as their own resps rather than duplicated across \
feature-specific resps?
"""


def render_system_prompt() -> str:
    return render_review_system_prompt(
        artifact_label="``<requirements>`` block",
        scope_label="this project",
        handles_criteria=_HANDLES,
        architecture_criteria=_ARCHITECTURE,
    )


def render_user_prompt(context: RequirementsContext, generated_output: str) -> str:
    parts: list[str] = []
    if context.vocab_summary.strip():
        parts.append(context.vocab_summary.strip())
        parts.append("")
    if (
        context.referenced_content_summary.strip()
        and context.referenced_content_summary.strip() != "(no external references)"
    ):
        parts.append(context.referenced_content_summary.strip())
        parts.append("")
    if context.input_doc.strip():
        parts.append("# Input document")
        parts.append("")
        parts.append(context.input_doc.strip())
        parts.append("")
    parts.append("# Approved features (the basis for decomposition)")
    parts.append("")
    parts.append(context.features_summary.strip() or "(no features)")
    parts.append("")
    parts.append("# Generated requirements (the artifact to review)")
    parts.append("")
    parts.append(generated_output.strip())
    parts.append("")
    parts.append("# Task")
    parts.append("")
    parts.append(review_task_footer())
    return "\n".join(parts).rstrip() + "\n"
