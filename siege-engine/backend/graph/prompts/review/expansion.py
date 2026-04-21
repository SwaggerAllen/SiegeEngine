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
and persona stories.

**Expansion is extraction *and inference*, by design.** The \
generator is explicitly told to include features the input doc \
doesn't name but the project obviously needs — auth wherever \
there are accounts, password reset wherever there's login, \
onboarding wherever there's a new-user flow, notifications \
wherever there are asynchronous events. Those are marked \
``<implicit/>``. Do not treat the presence of features not in \
the spec as a defect. The spec is a starting point; the \
expansion's job is to fill in what the project will obviously \
need based on what it IS. Flag an implicit feature only when \
the inference is *wrong for this project* — e.g., a \
team-invitation workflow for a single-user CLI, or an admin \
console for a library with no hosted surface — not simply \
because the doc didn't mention it.

Sloppy handles here compound: a vague feature name like \
"User Management" gives requirements nothing specific to \
redistribute, and the miss propagates into generic \
responsibilities, generic components, and thin impls. Catch \
vague or restated-input-doc features now; they cost most to \
fix two tiers down.
"""

_HANDLES = """\
- Are feature names crisp and distinct? Flag overly-broad names \
(e.g. "Dashboard") that don't name the slice of work, and \
excessively granular names that belong inside a larger feature.
- Are intent paragraphs specific enough to drive requirement \
derivation downstream? Flag vague intents ("Support users") and \
restated-name intents.
- Does the feature set cover the input doc's implied scope? \
Flag gaps — concerns the doc describes but the expansion \
missed. (This is the coverage direction — the other direction, \
features *beyond* the doc, is expected and addressed by the \
implicit-feature rule below.)
- Are there duplicated / overlapping features?
- If grouped, do the groups make sense? Flag arbitrary or \
inconsistent grouping.
- **Implicit features — correctness, not presence.** Implicit \
features that fit the project's nature are the generator doing \
its job; don't flag them as speculative. Only flag an implicit \
feature when the inference contradicts what the project \
obviously IS: a multi-tenant workflow on a single-user tool, a \
hosted admin surface on a downloadable binary, team invitations \
on a project that gives no signal of multi-user collaboration. \
When flagging, name the contradiction — "the project is a \
single-user X, so Y isn't warranted" — rather than citing the \
spec's silence.
- Is any feature that *should* be implicit marked explicit or \
vice versa? (A spec-named feature shouldn't carry \
``<implicit/>``; a clearly-inferred-beyond-spec feature should.)
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
        parts.append("# Input document (starting point — not an exhaustive feature list)")
        parts.append("")
        parts.append(
            "Features in the output that *aren't* in this doc are expected "
            "when they're obvious inferences for a project of this kind "
            "(auth wherever there are accounts, password reset wherever "
            "there's login, notifications wherever there are async events, "
            "etc.). Judge each implicit feature by whether the inference "
            "fits the project's actual nature, not by whether the doc "
            "names it."
        )
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
