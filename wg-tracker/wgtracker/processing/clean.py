"""Strip quoted text and signature blocks before summarization.

Conservative on purpose: we'd rather keep a borderline line than delete real
content, because the cleaned body is what the LLM summarizes.
"""
from __future__ import annotations

import re

# "On <date>, <person> wrote:" attribution lines that precede a quote block.
_ATTRIBUTION_RE = re.compile(
    r"^\s*(on\b.*\bwrote\s*:|.*\bwrote\s*:|.*\b(a|à)\s+écrit\s*:|.*schrieb\s*:|"
    r"-{2,}\s*original message\s*-{2,}|from:\s.*)\s*$",
    re.IGNORECASE,
)
_QUOTE_LINE_RE = re.compile(r"^\s*>+")
# Signature delimiter: a line that is exactly "-- " (RFC 3676), tolerating trailing ws.
_SIG_DELIM_RE = re.compile(r"^--\s*$")
# Common signature-block openers when the strict delimiter is absent.
_SIG_OPENER_RE = re.compile(
    r"^\s*(--+|__+|sent from my\b|best regards\b|kind regards\b|cheers\b,?\s*$|"
    r"thanks\b,?\s*$|regards\b,?\s*$|—\s*$)",
    re.IGNORECASE,
)


def strip_quotes(text: str) -> str:
    """Remove quoted lines (leading '>') and the attribution line introducing them."""
    lines = text.splitlines()
    out: list[str] = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        if _QUOTE_LINE_RE.match(line):
            # Drop this quote line; also retroactively drop a trailing attribution
            # line we just emitted (e.g. "On Mon, X wrote:").
            if out and _ATTRIBUTION_RE.match(out[-1]):
                out.pop()
            i += 1
            continue
        out.append(line)
        i += 1
    return "\n".join(out)


def strip_signature(text: str) -> str:
    """Remove a trailing signature block.

    Prefer the RFC 3676 '-- ' delimiter (cut everything after it). If absent,
    cut at a recognizable sign-off opener that sits in the last third of the body.
    """
    lines = text.splitlines()
    for idx, line in enumerate(lines):
        if _SIG_DELIM_RE.match(line):
            return "\n".join(lines[:idx]).rstrip()
    # Heuristic fallback: only trim within the tail of the message.
    if lines:
        tail_start = max(0, int(len(lines) * 0.66))
        for idx in range(tail_start, len(lines)):
            if _SIG_OPENER_RE.match(lines[idx]) and idx > 0:
                return "\n".join(lines[:idx]).rstrip()
    return text.rstrip()


def collapse_blank_lines(text: str) -> str:
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def clean_body(body: str) -> str:
    """Full cleaning pipeline: de-quote, de-sign, collapse whitespace."""
    if not body:
        return ""
    stripped = strip_quotes(body)
    stripped = strip_signature(stripped)
    return collapse_blank_lines(stripped)
