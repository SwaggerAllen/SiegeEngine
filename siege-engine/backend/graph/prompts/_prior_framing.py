"""Helpers for rendering prior-pending content + AI review into regen prompts.

Two regen-time problems live here:

1. **Stale ``<introduction>`` bleeding forward.** The three top tiers
   (feature expansion, requirements, sysarch) emit a short
   ``<introduction>`` block alongside their primary block (per Phase-11
   followup B4) so subsequent regens have the tier's own initial
   thinking available. The original wiring dumped ``prior_pending``
   into the prompt verbatim — including that introduction — under a
   "# Current version" header. The model then read its own prior
   commentary as if it were live framing for the new round, so each
   regen anchored on whatever feedback the *previous* round had been
   responding to (or the previous round's self-justification for not
   acting on that feedback) rather than the current critique. The
   result was regens that claimed to "address feedback X" while making
   only marginal moves, because the model was paraphrasing its own
   prior introduction back at itself.

   :func:`split_prior_introduction` separates the introduction from
   the rest of the prior content so the prompt can put the introduction
   under a "prior framing — superseded" label and the body under
   "current version". The model gets the prior thinking but knows it
   is historical commentary, not live instruction.

2. **AI self-review never reaching regen.** ``Draft.review_text`` (the
   AI critique committed by ``v2.review_<tier>``) is rendered on the
   draft panel but is not threaded into the next generation. On
   "Reject & Regenerate" the regen prompt sees the prior draft
   content + (any) user feedback — the review's recommendations stay
   trapped on the draft row.

   :func:`render_prior_review_section` is the prompt-side render for
   a review that the bootstrap-feedback callsite has captured into
   the regen payload before clearing it from the pending draft.

These helpers do nothing on their own — every prompt that uses
``prior_pending`` calls them, and the bootstrap-feedback callsite is
responsible for threading ``review_text`` into the regen payload.
"""

from __future__ import annotations

import re

# Tag boundaries are LLM-generated and may have whitespace around the
# inner text. We do not need to handle nested ``<introduction>`` tags
# (the validator rejects those upstream) so a non-greedy DOTALL match
# is enough.
_INTRODUCTION_RE = re.compile(
    r"<introduction>(.*?)</introduction>",
    flags=re.DOTALL,
)


def split_prior_introduction(prior_xml: str | None) -> tuple[str | None, str]:
    """Extract the ``<introduction>`` block from prior tier content.

    Returns ``(intro_inner_text, body_xml)``. ``intro_inner_text`` is
    the prose between the introduction tags with surrounding whitespace
    stripped, or ``None`` if the prior had no introduction. ``body_xml``
    is the prior content with the introduction block removed and outer
    whitespace cleaned.

    Tiers that don't emit ``<introduction>`` (every tier below the top
    three) get ``(None, prior_xml)`` and can render the body under the
    existing "current version" header without further changes.
    """
    if not prior_xml:
        return None, prior_xml or ""
    match = _INTRODUCTION_RE.search(prior_xml)
    if not match:
        return None, prior_xml
    intro = match.group(1).strip() or None
    body = (prior_xml[: match.start()] + prior_xml[match.end() :]).strip()
    return intro, body


def render_prior_framing_section(intro: str | None) -> list[str]:
    """Build the prompt section that quotes the prior introduction.

    Returns a list of lines ready to ``parts.extend(...)`` into a
    prompt builder. Empty list when ``intro`` is None or blank — the
    caller's ``parts`` stays unchanged in that case.

    The header explicitly tells the model the section is historical
    commentary that may already have been superseded, so it does not
    re-litigate prior justifications when fresh feedback or review
    contradicts them.
    """
    if not intro or not intro.strip():
        return []
    return [
        "# Prior framing (superseded — do not treat as live instruction)",
        "",
        (
            "The block below is your prior round's introduction — "
            "your previous justification for the version under "
            '"# Current version" later in this prompt. It may '
            "reference feedback that has already been addressed, or "
            "self-justifications that are no longer load-bearing now "
            'that fresh feedback (under "# User feedback") or AI '
            'review (under "# AI review of the prior draft") has '
            "landed. Treat it as historical context, not live "
            "instruction. Do not assume its framing still holds — "
            "weigh it against the current feedback and review and "
            "be willing to overturn its conclusions where they "
            "conflict with the fresher signal."
        ),
        "",
        intro.strip(),
        "",
    ]


def render_prior_review_section(prior_review: str | None) -> list[str]:
    """Build the prompt section quoting the AI review of the prior draft.

    Returns a list of lines for ``parts.extend(...)``. Empty when
    ``prior_review`` is None or blank.

    The review is framed as advisory — the user feedback above it in
    the prompt remains authoritative, so the model does not chase
    contradictory review recommendations over explicit user direction.
    Where the review surfaces real handle / boundary / decomposition
    issues that the user has not addressed, it should still influence
    the regen.
    """
    if not prior_review or not prior_review.strip():
        return []
    return [
        "# AI review of the prior draft (advisory)",
        "",
        (
            "An automated review pass critiqued the prior draft "
            "against the same context the generator saw. Use it as "
            "one signal among others. Where it identifies real "
            "handle / boundary / decomposition issues, address them "
            "in this regen. Where it overreaches or contradicts "
            'explicit user feedback under "# User feedback", '
            "prefer the user. The review is advisory; it never "
            "overrides direct user instruction."
        ),
        "",
        prior_review.strip(),
        "",
    ]
