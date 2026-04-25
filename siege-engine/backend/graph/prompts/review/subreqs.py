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
Subreqs is the scope-bounded atomic decomposition of one \
component's top-level responsibilities. Each subresp is an \
**atom** — one component-territory concern, named by its scope \
phrase, tagged with the in-scope feats it implicates and the \
parent resps it derives from. The pass is local to one \
component, so cross-component leaks (a derived-from or feats \
reference to an id the validator wouldn't have allowed) and \
non-atomic atoms (one subresp grouping several concerns under \
a paraphrased parent name) hurt the most. Comparch reads these \
to draw subcomponent boundaries; if the subresps don't slice \
along a coherent axis or under-cover the in-scope feats, \
comparch can't cluster cleanly.
"""

_HANDLES = """\
- Are subresp names distinctive enough for the comparch pass \
to draw clean subcomponent boundaries? Flag names that restate \
the parent resp ("Handle Payments" under "Payment Collection"), \
names too broad for a single subcomponent to own, or names \
that collide with sibling subresps (the validator catches \
exact dedup; flag soft collisions like "Token Cache" + \
"Token Caching").
- Are the atoms truly atomic? Flag any subresp tagged with the \
same feat-set as its only parent resp (a paraphrase of the \
parent), or tagged with so many feats that it's clearly \
grouping (more than three feats on one atom often means \
clustering — comparch's job, not subreqs').
- Is the feat clustering reasonable? Each atom should describe \
**what it does**, not **what it groups**. Cross-cutting concerns \
(retry scheduling, audit logging, idempotency) legitimately tag \
multiple feats; storage-of-record concerns usually tag one. \
Flag obvious mismatches.
- Is ``<derived-from>`` coverage complete? Every assigned \
parent resp must appear in at least one subresp's \
derived-from. Flag missing coverage.
- Is ``<feats>`` coverage complete? Every in-scope feat (from \
the "# Features in scope" reference table) must appear in at \
least one subresp's feats. Flag any feat with no covering atom.
- Are there cross-component leaks? Every id in derived-from or \
feats must be in the component's allowed sets. The validator \
will have rejected outright leaks, but flag soft hints — e.g. \
an atom whose name implies work assigned to a sibling \
dependency.
- For presentational components: is the UI-side rotation \
coherent? Subresps should articulate the user-facing / \
view-state / feedback-affordance dimensions of the parent \
resps, not duplicate the domain side's mechanism slicing. The \
feat tags should reflect that rotation — both sides tag the \
same feats from a different angle.
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
