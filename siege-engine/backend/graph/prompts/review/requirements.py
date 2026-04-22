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
decides which component owns it. The grammar is structured: \
each responsibility has ``<scope>`` (short noun phrases naming \
system-side concerns it owns), ``<does-not-own>`` (explicit \
deferrals to peers), a one-sentence ``<failure-surface>``, \
``<owns>`` (primary feature ownership — exactly one per feature \
doc-wide), and ``<supports>`` (composition / infrastructure). \
The validator mechanically enforces single-owner on features, \
scope-phrase uniqueness across responsibilities, and \
cross-reference resolution on ``<defers to=...>``. Your job is \
the fuzzier axis the mechanical check can't catch: **scope \
phrases that are near-duplicates** (different wording, same \
concern), **scope phrases that aren't actually system-side**, \
**weak or vague phrases** that fail to distinguish one \
responsibility from its peer, and **failure surfaces that \
describe impact-categories instead of concrete failure modes**.
"""

_HANDLES = """\
- **Near-duplicate scope phrases are the first thing to look \
for.** The validator rejects literal duplicates across \
responsibilities. You should flag *semantic* duplicates: two \
resps whose scope entries read differently but name the same \
system-side concept ("session state lifecycle" vs "session \
storage and invalidation"). Name the shared concept and \
suggest which responsibility should own it outright.
- **Scope phrases should be system-side, not user-facing.** \
Flag scope items that restate a user outcome instead of a \
system concern. Good: "append-only event log", "session-state \
lifecycle". Bad: "users can sign in", "secure authentication". \
Every scope item should be something sysarch could plausibly \
map to a module or data store.
- **Scope phrases should distinguish this responsibility from \
its peers.** A scope item that applies equally to half the \
other responsibilities is too vague. Flag phrases like \
"reliable delivery", "secure storage", "valid state" — those \
are universal concerns, not specific claims.
- **The ``<does-not-own>`` block is doing real work.** Every \
``<defers to="X">phrase</defers>`` should name a peer \
responsibility that genuinely owns the scope being deferred. \
Flag ``<defers>`` entries that read as boilerplate disclaimers \
(deferring to something obviously unrelated) or that defer to \
a responsibility whose own scope doesn't actually include the \
deferred phrase.
- **``<failure-surface>`` should name concrete failure modes, \
not impact categories.** Good: "Reducer drift is a platform-\
integrity incident; a non-reducer write is an invariant \
violation." Bad: "Loss of service; data integrity issues." \
Flag failure surfaces that wave at impact without naming the \
specific thing that breaks.
- Is the ``<owns>`` assignment the right owner? A feature ends \
up owned by one responsibility; is that the responsibility \
whose system-side guarantee the feature actually depends on? \
Flag if the owner looks accidental (e.g. a cross-cutting \
infrastructure resp is owning a feature that should belong to \
its downstream consumer).
- Is ``<supports>`` being used honestly? A responsibility that \
supports most of the feature set is likely genuinely \
cross-cutting (observability, audit, job queue infrastructure). \
Flag large supports lists whose scope doesn't explain what the \
responsibility actually contributes, and flag ``<supports>`` \
entries that should really be ``<owns>``.
- Are responsibility names distinctive and specific to the \
system-level work? Flag names that restate a feature, names \
too abstract for sysarch to map to a component, or names that \
collide with siblings.
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
rather than feature-by-feature duplicates. Look at the \
aggregate shape of the scope phrases across the whole doc: \
does the set hang together, or does it look like the feature \
list with renamed headers?
"""

_ARCHITECTURE = """\
- Is the axis right? Requirements should rotate user-facing \
feature intents into system-level responsibilities. Flag resps \
whose scope phrases still read as user outcomes (feature-axis) \
rather than system concerns (system-axis).
- Is the decomposition the right level for sysarch? Too-fine \
creates a component explosion (flag resps whose scope has only \
1–2 items unless they're genuinely narrow platform-level \
concerns); too-coarse collapses distinct failure modes into a \
single responsibility (flag resps whose scope spans \
unrelated-seeming concerns — they probably need splitting).
- Are cross-cutting concerns (auth, audit, observability) \
handled as their own resps rather than duplicated across \
feature-specific resps?
- Does the aggregate responsibility list cover what the project \
actually needs, or are there implicit system concerns (logging, \
rate limiting, secrets handling, background scheduling) that \
nobody is naming?
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
