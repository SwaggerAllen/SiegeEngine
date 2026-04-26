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

_HANDLES_INTRO = """\
Subreqs is the **optional** atomic decomposition of a \
component's top-level responsibilities. A parent resp that \
fits cleanly inside a single subcomponent shouldn't be \
decomposed at all — it gets assigned wholesale at comparch \
time. So an empty subreqs doc, or one that covers only some \
parents, is a deliberate decision, not a coverage failure. \
The pass is local to one component, so cross-component leaks \
hurt; the most common quality problem is over-decomposition \
— a parent resp split into a single subresp that paraphrases \
it, adding tokens without adding signal.
"""

_HANDLES = """\
- Are subresp names distinctive enough for the comparch pass \
to draw clean subcomponent boundaries? Flag names that restate \
the parent resp ("Handle Payments" under "Payment Collection"), \
names too broad for a single subcomponent to own, or names \
that collide with sibling subresps (the validator catches \
exact dedup; flag soft collisions like "Token Cache" + \
"Token Caching").
- **Over-decomposition check.** Flag any parent resp that has \
exactly one subresp covering it where that subresp's feat-set \
mirrors the parent's and its name paraphrases the parent. \
That's not a decomposition — it's the parent in disguise. \
Either it should split into two-or-more genuinely-distinct \
atoms, or the parent should be left wholesale (no subresps for \
it at all). Cross-cutting subresps that derive from multiple \
parents are exempt — they earn their keep by spanning \
boundaries.
- **Under-decomposition check.** Conversely, flag any parent \
resp emitted with **no** subresps where the work plausibly \
splits across two-or-more subcomponents. Storage + retrieval, \
read + write, sync + async — these are typical signals that \
wholesale assignment will overload one subcomp.
- Is the feat clustering reasonable? Each atom should describe \
**what it does**, not **what it groups**. Cross-cutting concerns \
(retry scheduling, audit logging, idempotency) legitimately tag \
multiple feats; storage-of-record concerns usually tag one. \
Flag obvious mismatches.
- Are there cross-component leaks? Every id in derived-from or \
feats must be in the component's allowed sets. The validator \
will have rejected outright leaks, but flag soft hints — e.g. \
an atom whose name implies work assigned to a sibling \
dependency.
- For presentational components: is the UI-side rotation \
coherent? Subresps should articulate the user-facing / \
view-state / feedback-affordance dimensions of the parent \
resps, not duplicate the domain side's mechanism slicing.
"""

_ARCHITECTURE_INTRO = """\
The subresp decomposition axis must match the component's \
coherent axis of work. Two patterns fail here: atoms that \
slice orthogonally to the component's real grain (producing \
subcomponents that each touch every concern), and scope bleed \
(a subresp whose name + feats describe work that belongs in a \
sibling dependency's component). Flag both.
"""

_ARCHITECTURE = """\
- Is the decomposition axis the right one for this component? \
A component does one kind of work; its subresps should slice \
that work along the grain, not across arbitrary boundaries.
- Are there overlap / duplication issues between subresps that \
comparch will need to untangle? Two atoms tagging the same feat \
set with similar names usually indicates a missed merge.
- Is the set of subresps a complete decomposition of the \
component's scope? If there's implicit work the parent resps \
imply (e.g. lifecycle hooks, error paths) but no atom covers, \
name it. Component-emergent atoms with empty ``<feats/>`` are \
fine — but flag conspicuous absences.
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
        handles_intro=_HANDLES_INTRO,
        architecture_intro=_ARCHITECTURE_INTRO,
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

    parts.append("# Features in scope")
    parts.append("")
    parts.append(
        "Reference table for the ``<feats>`` blocks in the artifact "
        "below — these are the only feat IDs the generator was allowed "
        "to tag. Use this to evaluate feat-coverage and feat-clustering."
    )
    parts.append("")
    parts.append(context.in_scope_feats_summary.strip() or "(no in-scope features)")
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
