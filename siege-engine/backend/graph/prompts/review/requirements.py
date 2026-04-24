"""Review prompt for the requirements tier."""

from __future__ import annotations

from backend.graph.prompts.review._shared import (
    render_review_system_prompt,
    review_task_footer,
)
from backend.graph.review_context.requirements import RequirementsContext

_HANDLES_INTRO = """\
Requirements rotates user-facing features into atomic \
system-side responsibilities. Each ``<responsibility>`` is one \
concern, named by a short noun phrase. Sysarch clusters these \
atoms into components — that clustering is *not* this tier's \
job. The grammar is minimal: exactly ``<name>`` + ``<feats>``. \
The validator mechanically enforces name-dedup and \
feat-coverage (every feature appears in at least one atom's \
``<feats>``), so you can assume coverage is already satisfied \
and focus on the fuzzier axis the mechanical check can't catch: \
**atoms that are still compound groupings** rather than one \
concern, **atoms that read as user outcomes** instead of \
system-side concerns, and **feat tags that are wrong** (a feat \
tagged on an atom it doesn't actually implicate, or a feat that \
belongs on this atom but isn't tagged).
"""

_HANDLES = """\
- **Atomicity is the first thing to check.** Each atom should \
name one concrete system-side concern. Flag atoms whose names \
contain "and" or imply a grouping — "session lifecycle and \
token refresh" is two atoms; "billing state and invoice \
emission" is two atoms; "Authentication" is probably four or \
five atoms (session, password hash, rate limit, token refresh, \
permission check). Suggest the split and name the atoms the \
generator should have emitted.
- **Names should be system-side, not user-facing.** Flag atoms \
whose names restate a user outcome instead of a system concern. \
Good: "append-only event log", "session-state lifecycle", \
"per-request access decision". Bad: "users can sign in", \
"secure authentication", "reliable delivery" (vague), \
"Authentication" (grouping). Every atom name should be \
something sysarch could plausibly map to a module or data store.
- **Feat-tagging honesty.** The validator guarantees every \
feature appears on at least one atom, but it can't judge \
whether the tags are *correct*. Flag atoms whose ``<feats>`` \
includes a feature the atom doesn't actually implicate (wrong \
tag) and atoms that are missing a feature which clearly \
implicates them (missing tag). Many-to-many is normal — a \
login feature legitimately implicates session, rate limit, and \
password hash — but each tag should be defensible.
- **Names should distinguish this atom from its peers.** An \
atom name so vague it could apply to half the other atoms is \
too abstract. Flag names like "reliable delivery", "secure \
storage", "valid state" — those are universal claims, not \
specific concerns.
- Are ``<feat>`` references valid? Every ``feat_*`` id must \
exist in the feature set. (The validator catches this, but \
flag it if you see it — makes the critique complete.)
"""

_ARCHITECTURE_INTRO = """\
The rotation axis is the load-bearing decision here. If the \
atoms still read as user-facing outcomes or as groupings, \
requirements didn't rotate — sysarch will struggle to cluster \
them because they're still on the feature side of the axis or \
they already impose component boundaries. Look at the aggregate \
shape: does the set decompose the features into system-side \
concerns at the atom grain (good), or does it echo the feature \
list with renamed headers (bad)?
"""

_ARCHITECTURE = """\
- Is the axis right? Atoms should be system-side concerns, not \
user outcomes and not UI/backend splits. Flag atoms that still \
read as features ("Accept card payments") or as UI/backend \
sibling pairs ("payment mechanics" + "payment UI" — those are \
sysarch's concern, not this tier's).
- Is any atom doing too much? Flag atoms whose names pack \
multiple concerns together ("review routing, notification, \
and SLA") — these should have been split into separate atoms. \
There's no atom-count ceiling; a small total atom count \
relative to feature count is a signal the generator was \
clustering to conserve entries.
- Are system-emergent atoms named? Flag absences: an \
append-only event log, a pure reducer entrypoint, a per-project \
sandbox — these typically have no direct feature cause but \
belong in the atom list with ``<feats/>`` empty.
- **Are platform-NFR concerns atomized?** Rate limiting, audit \
logging, token/cost telemetry, circuit breakers and fuses on \
external calls, retry with backoff, encryption at rest, \
credential rotation, SLA enforcement, quota tracking, \
license/compliance obligations (AGPL, SOC2, GDPR). These govern \
how features behave and typically have empty ``<feats/>``. \
**Sysarch cannot recover these if reqs doesn't emit them** — a \
missing NFR atom here becomes a missing policy downstream. Flag \
specific absences by name: if the project processes payments, \
"audit every credential access" and "rate-limit outbound \
payment-provider calls" should be in the list; if the project \
calls LLMs, "token telemetry on every LLM call" and \
"rate-limit outbound LLM calls per provider" should be in the \
list. Don't flag generically — name the missing atom.
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
