"""Review prompt for the feature-expansion tier."""

from __future__ import annotations

from backend.graph.prompts.review._shared import (
    render_review_system_prompt,
    review_task_footer,
)
from backend.graph.review_context.expansion import ExpansionContext

_HANDLES_INTRO = """\
Expansion is the first layer of handles the generation chain \
builds on. Every downstream tier — requirements, sysarch, \
comparch, impl — reads what's here as a named set of workflows \
and persona stories. Sloppy handles here compound: a vague \
feature name like "User Management" gives requirements nothing \
specific to redistribute, and the miss propagates into \
generic responsibilities, generic components, and thin \
impls. Catch vague or restated-input-doc features now; they \
cost most to fix two tiers down.
"""

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
- Is the ``<vocabulary>`` block populated with genuinely \
project-specific terms? Flag vocab entries that are either \
generic tech vocabulary (HTTP, JSON) or so narrow they only \
appear in one feature's intent paragraph.
"""

_ARCHITECTURE_INTRO = """\
Features should be workflows and persona stories, not \
engineering categories. The decomposition axis decision is \
load-bearing: if the set reads like a sysarch layer diagram \
("storage service", "API gateway") or an implementation menu \
("use Postgres for sessions"), requirements won't have \
concrete user-visible capabilities to rotate from. Flag axis \
drift; name the correct axis if you see one. Granularity \
matters too — too-fine causes fan-out pain, too-coarse loses \
detail requirements need.
"""

_ARCHITECTURE = """\
- Is the granularity right-sized for this project? Expansion \
too-fine causes downstream fan-out; too-coarse loses detail \
requirements need.
- Is the feature axis the right decomposition of the product? \
If the input suggests a different natural axis (workflow, \
persona, data domain), name it.
- Are any features actually sysarch concerns ("storage layer", \
"API gateway") or implementation details ("use Redis") that \
should be rephrased as user-visible capabilities?
"""


def render_system_prompt() -> str:
    return render_review_system_prompt(
        artifact_label="``<features>`` expansion",
        scope_label="this project",
        handles_criteria=_HANDLES,
        architecture_criteria=_ARCHITECTURE,
        handles_intro=_HANDLES_INTRO,
        architecture_intro=_ARCHITECTURE_INTRO,
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
