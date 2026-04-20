"""Review prompt for the requirements tier."""

from __future__ import annotations

from backend.graph.prompts.review._shared import (
    render_review_system_prompt,
    review_task_footer,
)
from backend.graph.review_context.requirements import RequirementsContext

_HANDLES_INTRO = """\
Requirements rotates user-facing features into system-level \
responsibilities. Sysarch then reads each responsibility and \
decides which component owns it. Two failure modes hurt most: \
overlapping responsibilities (two resps both claim ownership of \
the same system capability, making component boundaries \
ambiguous), and responsibilities that restate their source \
feature (no rotation happened — sysarch can't distinguish user \
intent from system obligation). Flag both aggressively.
"""

_HANDLES = """\
- **Overlap first.** Are any two responsibilities claiming \
ownership of the same system capability? Multiple features can \
share a resp; two resps owning the same scope is a bug. Flag \
overlaps by naming the specific capability both claim.
- Are responsibility names distinctive and specific to the \
system-level work? Flag names that restate a feature, names \
too abstract for sysarch to map to a component, or names that \
collide with siblings.
- Are intents specific about the system-side work (mechanism / \
data / guarantee) rather than user-facing behavior the \
features already describe? Flag intents that just paraphrase a \
feature.
- Does each intent name what the resp explicitly does *not* \
cover, so sysarch knows where boundaries lie?
- Does the responsibility set cover the feature set? Every \
feature's system-side needs should map to at least one \
responsibility (possibly shared across features). Flag missing \
coverage.
- Are ``<covers>`` references valid? Every feat_* id must exist \
in the feature set.
"""

_ARCHITECTURE_INTRO = """\
The rotation axis is the load-bearing decision here. If \
responsibilities still read as user-facing outcomes, \
requirements didn't rotate — sysarch will struggle to map them \
to components because they're still on the feature side of the \
axis. Cross-cutting concerns (auth, audit, observability) \
deserve their own resps so sysarch can consolidate them, \
rather than feature-by-feature duplicates.
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
        handles_intro=_HANDLES_INTRO,
        architecture_intro=_ARCHITECTURE_INTRO,
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
