"""Review prompt for the comparch tier."""

from __future__ import annotations

from backend.graph.prompts.review._shared import (
    render_review_system_prompt,
    review_task_footer,
)
from backend.graph.review_context.comparch import ComparchContext

_HANDLES_INTRO = """\
Comparch is the last compression before impl. Subcomponent \
names, purposes, owned-invariants, primary-operations, and the \
pubapi / privapi split are the handles impl (and sibling \
subcomponents) reason against. Vague handles let impl ship \
generic code that misses the specifics. The pubapi/privapi \
split matters: a bloated pubapi leaks internals across sibling \
boundaries.

Two cross-cutting consistency checks are load-bearing here. The \
``<owns>`` block determines who is accountable for each parent \
resp + feat slice; the default is **one resp → one subcomponent** \
and multi-owner is reserved for two specific patterns (UI flow \
splits, read/write path splits) called out in the generator \
prompt. The other check is internal coherence: techspec claims, \
owned-invariants, and failure-surface scenarios must not \
contradict each other.
"""

_HANDLES = """\
- Are subcomponent names the right specificity for the \
responsibility? A domain-specific responsibility wants a \
domain-specific name; a generic infrastructure responsibility \
(``Registry``, ``Gateway``, ``Dispatcher``, ``Coordinator``) is \
correctly named structurally. The anti-pattern is wrapping \
domain logic in a generic shell — ``BillingManager`` for \
payment-reconciliation logic — not naming a registry \
``Registry``. Flag a generic name only when the subcomp's \
invariants and operations are actually domain-specific.
- Is each subcomponent's ``<purpose>`` a single specific \
sentence that names the subcomponent-distinctive *why*? Flag \
category-speak ("handles X", "manages Y").
- Does each ``<owned-invariants>`` list 2-4 concrete noun \
phrases (durable state, guarantees the sub enforces)? Flag \
impact-category padding ("must be reliable") or invariants \
that could belong to any subcomponent.
- Does each ``<primary-operations>`` list 3-6 concrete verb \
phrases? Flag category verbs ("handle", "manage", "coordinate") \
and operations invented beyond the subcomponent's claimed \
ownership.
- ``<owns>`` ownership is **one resp → one subcomponent by \
default**. Multi-owner is legal only in two named patterns: \
(a) UI flow split — the same resp owned by per-stage subcomps \
(input / validate / submit / error) on a presentational \
component; (b) read-path / write-path split — query subcomp + \
mutation subcomp co-owning the resp's feats with a clear \
data-direction seam. Outside those two patterns, treat any \
shared ``<resp id=…>`` across subcomps as a finding **unless** \
the subcomp's free-text ``<responsibilities>`` explicitly \
names the cooperation rationale (e.g., "co-owns resp_X with \
credential_writer; this sub handles the read path"). When a \
named pattern *is* claimed, validate it: do the feat slices \
divide coherently along that seam, or is one subcomp shadowing \
the other?
- When ``<subcomponents>`` decomposes, every parent resp in \
scope must be claimed by ≥1 subcomp and every feat tagged on \
a parent resp must be claimed by ≥1 subcomp claiming that \
resp; flag coverage gaps. **Empty ``<subcomponents>`` is \
legitimate** for un-fanned-out leaf components — a small \
LiveView page, a thin REST surface, a single-purpose helper \
with no internal seams worth surfacing. Do **not** flag empty \
``<subcomponents>`` by itself as a structural problem; only \
flag it when the techspec describes genuinely separable \
concerns the artifact has chosen not to surface as subs (e.g., \
distinct LiveView panes that own state independently, separate \
read / write code paths against different aggregates).
- ``<dependencies>`` and ``<sub-dependencies>`` reference only \
valid sibling or parent-sibling comp IDs. Flag unknown IDs.
- Policy ``<required>`` references must be in the parent-resp \
set for this component.
- ``<technical-specification>`` is paragraph-shaped (blank \
lines between concerns), specific about concurrency / \
persistence / testing / build — not a one-liner.
- ``<public-surface>`` names types, signatures, events — not \
just method names. Types referenced in the public surface must \
be defined there or come from a stable external dependency. \
``<private-surface>`` is genuinely internal (helpers only the \
subs of this comp call), not re-exported public API. Flag \
public-surface entries that don't actually need to cross a \
sibling boundary. (Private modules leaking into public-surface \
signatures are caught by the parser — focus on semantic \
leakage: types or events that *could* be private without \
breaking sibling consumers.)
- ``<failure-surface>`` names **concrete failure modes** \
(auth bypass, invariant violation, data loss, silent \
degradation, specific wrong-output shapes) rather than impact \
categories ("service becomes unreliable", "users affected"). \
Flag vague surfaces — the component-local failure surface is \
sharper than the sysarch one because comparch has the full \
techspec + pubapi in hand; if it reads the same as a sysarch \
sketch, it's under-specified.
- **Cross-section consistency is the highest-yield check.** \
Scan the artifact as a whole and flag direct contradictions: \
a techspec claim ("no partial writes", "all events are \
atomic") versus a failure-surface scenario describing exactly \
that failure mode; an owned-invariant versus a failure-surface \
scenario asserting the opposite; a public API return type \
that cannot express a failure the failure surface explicitly \
names; a primary-operation that has no public-surface \
entry-point and no private-surface helper to dispatch \
through; a public type that documents one shape while another \
section's prose documents a different one. These are the \
most common load-bearing findings — be specific about which \
two sections disagree and what the artifact would need to do \
to reconcile.

Things you do **not** need to flag (the parser already \
rejects them, so the artifact you're seeing has already \
passed these checks): declared sub-dependency cycles in \
``<sub-dependencies>``; private modules declared in \
``<private-surface>`` and referenced by full module name in \
``<public-surface>``; missing parent-resp coverage when \
``<subcomponents>`` is non-empty; per-resp feat coverage \
gaps. Spending review budget on these is wasted effort.
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
