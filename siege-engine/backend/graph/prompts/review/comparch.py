"""Review prompt for the comparch tier."""

from __future__ import annotations

from backend.graph.prompts.review._shared import (
    render_review_system_prompt,
    review_task_footer,
)
from backend.graph.review_context.comparch import ComparchContext

_HANDLES_INTRO = """\
Comparch is the last compression before impl. Subcomponent \
names, roles, api-intents, and the pubapi / privapi split are \
the handles impl (and sibling subcomponents) reason against. \
Vague handles here — "Manager", "Service", unsigned api-intent \
prose — let impl ship generic code that misses the specifics. \
The pubapi/privapi split matters: a bloated pubapi leaks \
internals across sibling boundaries.
"""

_HANDLES = """\
- Are subcomponent names distinctive and domain-specific? Flag \
anti-patterns (Manager / Helper / Utils / Service) and names \
that restate the parent comp.
- Are subcomponent roles specific about what each does, not \
what it IS? Flag category-speak.
- Are subcomponent api-intents (``<api-intent>``) specific \
enough for dependent subs to call without guessing signatures? \
Flag vague intents.
- Every pre-minted subresp must appear in exactly one \
subcomponent's ``<responsibilities>``. Flag orphans or doubles.
- ``<dependencies>`` and ``<sub-dependencies>`` reference only \
valid sibling or parent-sibling comp IDs. Flag unknown IDs.
- Policy ``<required>`` references must be in the \
parent-resp + subresp set for this component.
- ``<technical-specification>`` is paragraph-shaped (blank \
lines between concerns), specific about concurrency / \
persistence / testing / build — not a one-liner.
- ``<public-surface>`` names types, signatures, events — not \
just method names.
- ``<private-surface>`` is genuinely internal (helpers only \
the subs of this comp call), not re-exported public API.
- ``<failure-surface>`` names **concrete failure modes** \
(auth bypass, invariant violation, data loss, silent \
degradation, specific wrong-output shapes) rather than impact \
categories ("service becomes unreliable", "users affected"). \
Flag vague surfaces — the component-local failure surface is \
sharper than the sysarch one because comparch has the full \
techspec + pubapi in hand; if it reads the same as a sysarch \
sketch, it's under-specified.
"""

_ARCHITECTURE_INTRO = """\
Tech-stack drift across components makes the project \
inconsistent; foundation misuse (dumping ground) makes it \
un-navigable; axis misfit (subcomponents that don't slice \
along the component's real grain) makes every sub touch \
every concern. Flag any of these directly, naming the \
specific subcomponent and what should change.
"""

_ARCHITECTURE = """\
- Is the subcomponent decomposition axis right (task / data / \
workflow) for this component's work?
- Is the depth right — right-sized subs, not one giant sub or \
a thousand tiny ones?
- Are cross-cutting concerns bundled into a single sub (fine) \
or duplicated across siblings (not fine)?
- Does the component's tech stack choice match the project's \
broader architecture? Flag drift from the project techspec.
- Is the split between public and private surface principled \
— or is the public surface bloated with internal details?
- If the component is a foundation, is its decomposition \
exhaustive (no nested foundations)?
"""


def render_system_prompt() -> str:
    return render_review_system_prompt(
        artifact_label="``<comparch>`` block",
        scope_label="this component",
        handles_criteria=_HANDLES,
        architecture_criteria=_ARCHITECTURE,
        handles_intro=_HANDLES_INTRO,
        architecture_intro=_ARCHITECTURE_INTRO,
    )


def render_user_prompt(context: ComparchContext, generated_output: str) -> str:
    parts: list[str] = []
    parts.append(f"# Component under review: {context.component_name}")
    parts.append("")
    parts.append(f"Kind: **{context.component_kind}**")
    parts.append(f"Foundation: **{context.target_is_foundation}**")
    parts.append("")
    # Dump the regen-context bundle as key/value sections.
    for key, value in context.context_kwargs.items():
        if not isinstance(value, str) or not value.strip():
            continue
        parts.append(f"# {key}")
        parts.append("")
        parts.append(value.strip())
        parts.append("")
    parts.append("# Generated comparch (the artifact to review)")
    parts.append("")
    parts.append(generated_output.strip())
    parts.append("")
    parts.append("# Task")
    parts.append("")
    parts.append(review_task_footer())
    return "\n".join(parts).rstrip() + "\n"
