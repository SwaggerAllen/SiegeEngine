"""Review prompt for the sysarch tier."""

from __future__ import annotations

from backend.graph.prompts.review._shared import (
    render_review_system_prompt,
    review_task_footer,
)
from backend.graph.review_context.sysarch import SysarchContext

_HANDLES_INTRO = """\
Sysarch is the compression pass — it collapses responsibilities \
into components, fixes component boundaries, and picks the \
tech stack. Every downstream tier reads these handles as \
read-only: names / purpose / owned-invariants / primary-\
operations / policies are the compressed form comparch thinks \
against. If names are generic ("Service", "Manager", "Hub") or \
purpose prose is category-speak ("manages X", "handles Y"), \
comparch reasons against empty handles and produces generic \
techspecs. Be strict here.
"""

_HANDLES = """\
- Are component names distinctive, domain-shaped, and free of \
anti-patterns (Workspace / Dashboard / Console / UI / Hub / \
Service)? Flag generic names.
- Is each ``<purpose>`` a single specific sentence that names \
the component-distinctive *why*, not the category it sits in? \
Flag category-speak ("handles X", "manages Y").
- Does each ``<owned-invariants>`` list 2-4 concrete noun \
phrases (durable state, guarantees)? Flag impact-category \
padding ("must be reliable") or invariants that could belong \
to any component.
- Does each ``<primary-operations>`` list 3-6 concrete verb \
phrases callers actually invoke? Flag category verbs ("handle", \
"manage", "coordinate") and invented operations that don't \
match the responsibilities.
- **Resp-ID mirroring on presentational components is the \
intended pattern, not a flaw.** Every responsibility a \
presentational component surfaces to the user **should** appear \
in *both* its owning domain component's ``<responsibilities>`` \
block AND the presentational's. The reqs tier emits one \
responsibility per system-side concern (no UI/backend split), \
and it is the sysarch layer's job to mirror those into the \
presentational that exposes them — without the mirror, the \
subreqs pass for the presentational has nothing to rotate to \
UI articulation. **Do not flag a resp ID appearing in one \
domain component AND one presentational component as \
"doubly-mapped" — that is correct.** The thing that IS broken: \
a resp ID appearing in two *domain* components, or in a \
presentational whose ``<domain-parent>`` edge does not point at \
the resp's owning domain. Those are the genuine assignment \
errors to flag.
- **For presentational components specifically:** do the \
``<owned-invariants>`` and ``<primary-operations>`` *content* \
describe rendering / interaction / UI-local state, or do they \
parrot the domain parent's business invariants and operations \
back word-for-word? A presentational whose invariants/operations \
read identically to its domain parent's is under-specified — \
flag it. The presentational owns display rules, gesture wiring, \
navigation, and UI-state; the domain owns business state. Note \
this check is about the prose content of those two micro-field \
blocks, NOT about resp-ID assignment (see the previous bullet — \
mirroring resp IDs is correct).
- Does every top-level responsibility appear on **at least one** \
domain component's ``<responsibilities>`` block (coverage), and \
on **at most one** domain component (no domain double-ownership)? \
Flag orphans (resp not in any domain component) and \
domain-domain double-ownership. Resp IDs additionally appearing \
in a presentational with the right domain-parent edge are \
correct, not a coverage error.
- Are dependencies a DAG? Flag cycles.
- For presentational components: are their domain_parent edges \
pointing at the right domain comps? Does each presentational \
name the user-facing slice, not the mechanism?
- Is the 1-2 domain-parent cap per presentational respected?
- Are policies' ``<required>`` references valid top-level \
resp ids?
"""

_ARCHITECTURE_INTRO = """\
Component boundaries and tech-stack choices land here and are \
expensive to undo — comparch, subcomparch, and impl all inherit \
them. Watch for components that bundle unrelated work (no \
coherent axis), foundation components used as a dumping ground, \
and techspec blocks that are thin ("Python, React" in \
``<technologies>`` but nothing specific in the narrative \
blocks). Also audit policies: an AGPL-style universal policy \
shouldn't have a ``<required>`` responsibility; a policy that \
targets a specific capability should.
"""

_ARCHITECTURE = """\
- Is the component decomposition axis the right one (task / \
domain / workflow)? Flag forced / unnatural groupings.
- Do components have coherent responsibilities (one axis of \
work) or do they bundle unrelated concerns?
- Are the labeled techspec blocks (``<runtime>``, \
``<persistence>``, ``<write-path>``, ``<concurrency>``, \
``<testing>``, ``<deploy>``) each specific enough that a \
downstream tier can act on them? Flag thin or filler blocks.
- Does ``<technologies>`` faithfully record the concrete \
framework / library / service choices named in the input? Flag \
invented technologies or missing ones.
- Are cross-cutting concerns handled as policies / foundation \
components rather than duplicated?
- Is the foundation component (if any) genuinely foundational, \
or a dumping ground?
- Is the domain/presentational split meaningful for this \
project, or would it be cleaner as pure domain?
"""


def render_system_prompt() -> str:
    return render_review_system_prompt(
        artifact_label="``<sysarch>`` block",
        scope_label="this project",
        handles_criteria=_HANDLES,
        architecture_criteria=_ARCHITECTURE,
        handles_intro=_HANDLES_INTRO,
        architecture_intro=_ARCHITECTURE_INTRO,
    )


def render_user_prompt(context: SysarchContext, generated_output: str) -> str:
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
    parts.append("# Features (user-facing framing)")
    parts.append("")
    parts.append(context.features_summary.strip() or "(no features)")
    parts.append("")
    parts.append("# Top-level responsibilities (to be decomposed into components)")
    parts.append("")
    parts.append(context.reqs_summary.strip() or "(no responsibilities)")
    parts.append("")
    parts.append("# Generated sysarch (the artifact to review)")
    parts.append("")
    parts.append(generated_output.strip())
    parts.append("")
    parts.append("# Task")
    parts.append("")
    parts.append(review_task_footer())
    return "\n".join(parts).rstrip() + "\n"
