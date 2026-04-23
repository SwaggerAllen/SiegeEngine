"""Phase 13 — lift-and-strip helper for ``<change-summary>``.

The generator emits ``<change-summary>`` as a sibling to
``<introduction>`` and the tier's main section. At
:func:`backend.graph.handlers._bootstrap_generation.persist_draft`
time we lift the tag body out and store it on
``Draft.change_summary``; the ``<change-summary>`` tag itself is
stripped from the stored draft content so downstream readers
(the diff view, the mint handler re-parse, every validator) see
only document prose.

Lenient by construction — a missing or empty tag is not an
error; fan-in drafts never emit one and pre-Phase-13 drafts are
replayable without this helper changing their content.
"""

from __future__ import annotations

import re

_CHANGE_SUMMARY_RE = re.compile(
    r"<change-summary\b[^>]*>(.*?)</change-summary>",
    re.DOTALL | re.IGNORECASE,
)


def extract_change_summary(raw: str) -> tuple[str, str]:
    """Return ``(summary_text, raw_with_summary_stripped)``.

    * Finds the first ``<change-summary>...</change-summary>`` in
      ``raw`` and returns its body (whitespace-stripped).
    * Returns ``raw`` with every ``<change-summary>`` occurrence
      removed and surrounding whitespace collapsed down to at most
      one blank line, so the stored draft content reads cleanly.
    * If no tag is present, returns ``("", raw)`` unchanged.
    * If the tag is present but empty, returns ``("", stripped)``.

    Tolerant of attributes on the opening tag (``<change-summary
    foo="bar">``) — attributes are discarded. Case-insensitive on
    the tag name to match the lenient-extractor behavior the rest
    of the parsers use.
    """
    if not raw:
        return "", raw

    match = _CHANGE_SUMMARY_RE.search(raw)
    summary = match.group(1).strip() if match is not None else ""
    stripped = _CHANGE_SUMMARY_RE.sub("", raw)
    # Collapse any run of 3+ newlines (introduced by pulling the
    # tag out from between paragraphs) back down to one blank line.
    stripped = re.sub(r"\n{3,}", "\n\n", stripped)
    return summary, stripped.strip()
