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
read-only: names / role / api-intent / policies are the \
compressed form comparch thinks against. If names are generic \
("Service", "Manager", "Hub") or role prose is category-speak \
("manages X", "handles Y"), comparch reasons against empty \
handles and produces generic techspecs. Be strict here.
"""

_HANDLES = """\
- Are component names distinctive, domain-shaped, and free of \
anti-patterns (Workspace / Dashboard / Console / UI / Hub / \
Service)? Flag generic names.
- Are roles (``<role>``) specific about what the component \
does, not what it IS? A role should describe behavior, not \
category. Flag category-speak.
- Are api-intents specific enough for downstream pubapi \
shaping? Flag vague "coordinates X" / "manages Y" prose.
- Is every ``<failure-surface>`` a **concrete failure mode** \
(data loss, invariant violation, silent degradation, security \
breach, specific wrong-output shape) rather than an impact \
category? Flag surfaces that say "service becomes unreliable", \
"data issues", "users affected" — those describe consequences, \
not the specific thing that breaks. The failure-surface is the \
signal comparch / fanin readers use to pick invariants to \
check; a vague surface produces vague invariants.
- Does every top-level responsibility appear on exactly one \
``<decomposition>`` edge, mapping it to a single owning \
component? Flag orphaned resps, doubly-mapped resps, or \
cross-mapped IDs that don't resolve.
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
and techspec prose that's thin ("Python, React") rather than \
specific about persistence / concurrency / testing / \
deployment. Also audit policies: an AGPL-style universal policy \
shouldn't have a ``<required>`` responsibility; a policy that \
targets a specific capability should.
"""

_ARCHITECTURE = """\
- Is the component decomposition axis the right one (task / \
domain / workflow)? Flag forced / unnatural groupings.
- Do components have coherent responsibilities (one axis of \
work) or do they bundle unrelated concerns?
- Is the tech spec (``<techspec>``) specific about \
language/runtime, persistence, concurrency, testing, \
deployment — or thin ("Python, React")?
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
