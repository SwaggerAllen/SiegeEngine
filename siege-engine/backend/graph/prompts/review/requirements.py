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
decides which component owns it. The grammar now splits feature \
coverage into ``<owns>`` (primary system-side owner — exactly \
one per feature) and ``<supports>`` (infrastructure or \
composition contributors — zero or more per feature). The \
validator enforces single-owner mechanically, so your job here \
is the fuzzier axis: overlapping *scope* between responsibilities \
that the mechanical check can't catch (two resps whose prose \
intent claims the same system-side work), and responsibilities \
that restate their source feature without rotating. Flag both \
aggressively.
"""

_HANDLES = """\
- **Scope overlap in prose, first.** The validator catches \
per-feature collisions in ``<owns>``. Your job is to spot scope \
overlap in prose: two resps' intent paragraphs claiming the \
same system-side capability even when they own different \
features. If both resps' intents would satisfy the same \
sysarch-level question ("who produces end-of-month \
statements?"), that's overlap — flag it by naming the shared \
capability.
- Is ``<supports>`` being used honestly? A responsibility that \
``<supports>`` most of the feature set is likely genuinely \
cross-cutting (observability, audit, job queue infrastructure); \
flag if a responsibility claims broad ``<supports>`` without its \
intent paragraph explaining what it actually contributes. \
Inversely, flag ``<supports>`` that should really be ``<owns>`` \
(the prose describes primary ownership, but the feature is \
listed under supports — a miscategorization).
- Is the ``<owns>`` assignment the right owner? A feature ends \
up owned by one responsibility; is that the responsibility \
whose system-side guarantee the feature actually depends on? \
Flag if the owner looks accidental (e.g. a cross-cutting \
infrastructure resp is owning a feature that should belong to \
its downstream consumer).
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
- Are ``<owns>`` / ``<supports>`` references valid? Every feat_* \
id must exist in the feature set.
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
