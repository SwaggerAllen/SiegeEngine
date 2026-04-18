"""AI self-review prompt for the subreqs tier.

Consumes the same ``SubreqsContext`` bundle the generator saw
plus the just-generated ``<subrequirements>`` XML. Asks the
reviewer for a single markdown response with two top-level
sections — handles/structure (debug-focused) + architectural
decisions (decomposition-axis for subreqs). The frontend renders
the response as one collapsible "AI Review" block.
"""

from __future__ import annotations

from backend.graph.prompts.review._shared import (
    render_review_system_prompt,
    review_task_footer,
)
from backend.graph.review_context.subreqs import SubreqsContext

_HANDLES = """\
- Are subresp names distinctive enough for the comparch pass \
to draw clean subcomponent boundaries? Flag names that restate \
the parent resp ("Handle Payments" under "Payment Collection"), \
names too broad for a single subcomponent to own, names that \
collide with sibling subresps.
- Are intents specific? Each intent paragraph should name the \
data, operations, and failure modes this subresp covers, at a \
finer granularity than its parent. Flag vague / restated / \
placeholder intents.
- Is ``<derived-from>`` coverage complete? Every parent resp \
in the input list must appear in at least one subresp's \
derived-from. Flag missing coverage.
- Are there cross-component leaks? Every id in a derived-from \
must be in the component's assigned top-level resp set. Any \
other id is a bug.
- Is the decomposition right-sized? Flag both too-fine \
(per-method subresps) and too-coarse (one subresp covering \
multiple concerns). Name what should split or merge.
- For presentational components: is the UI-side rotation \
coherent? Subresps should articulate the user-facing / \
view-state / feedback-affordance dimensions of the parent \
resps, not duplicate the domain side's mechanism slicing.
"""

_ARCHITECTURE = """\
- Is the decomposition axis the right one for this component? \
A component does one kind of work; its subresps should slice \
that work along the grain, not across arbitrary boundaries.
- Are there overlap / duplication issues between subresps that \
comparch will need to untangle?
- Is the set of subresps a complete decomposition of the \
component's scope? If there's implicit work the parent resps \
imply but no subresp covers, name it.
- Are there subresps that belong in a different component — \
work that semantically fits a sibling dependency's scope \
rather than this one's?
"""


def render_system_prompt() -> str:
    return render_review_system_prompt(
        artifact_label="``<subrequirements>`` block",
        scope_label="a single component in a larger system",
        handles_criteria=_HANDLES,
        architecture_criteria=_ARCHITECTURE,
    )


def render_user_prompt(context: SubreqsContext, generated_output: str) -> str:
    """Build the review user prompt from the shared context + the draft."""
    parts: list[str] = []

    if context.vocab_summary and context.vocab_summary.strip():
        parts.append(context.vocab_summary.strip())
        parts.append("")
    if (
        context.referenced_content_summary
        and context.referenced_content_summary.strip()
        and context.referenced_content_summary.strip() != "(no external references)"
    ):
        parts.append(context.referenced_content_summary.strip())
        parts.append("")

    parts.append("# Component under review")
    parts.append("")
    parts.append(context.component_summary.strip() or "(component details missing)")
    parts.append("")
    parts.append(f"Kind: **{context.component_kind}**")
    parts.append("")

    parts.append("# Top-level responsibilities assigned to this component")
    parts.append("")
    parts.append(context.parent_resps_summary.strip() or "(no responsibilities assigned)")
    parts.append("")

    if context.sibling_dep_context and context.sibling_dep_context.strip():
        parts.append("# Sibling dependency context (already available)")
        parts.append("")
        parts.append(context.sibling_dep_context.strip())
        parts.append("")

    if context.domain_parent_context and context.domain_parent_context.strip():
        parts.append("# Domain-parent context (presentational rotation reference)")
        parts.append("")
        parts.append(context.domain_parent_context.strip())
        parts.append("")

    parts.append("# Generated subrequirements (the artifact to review)")
    parts.append("")
    parts.append(generated_output.strip())
    parts.append("")
    parts.append("# Task")
    parts.append("")
    parts.append(review_task_footer())
    return "\n".join(parts).rstrip() + "\n"
