"""Tolerant JSON extraction from LLM text output."""
from __future__ import annotations

import json
import re

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def extract_json(text: str | None) -> dict | list | None:
    if not text:
        return None
    candidate = text.strip()
    fence = _FENCE_RE.search(candidate)
    if fence:
        candidate = fence.group(1).strip()
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass
    # Fall back to the outermost {...} or [...] span, preferring whichever bracket
    # type appears first (so an embedded JSON array isn't mis-parsed as the inner
    # object).
    spans = []
    for opener, closer in (("{", "}"), ("[", "]")):
        start = candidate.find(opener)
        end = candidate.rfind(closer)
        if start != -1 and end != -1 and end > start:
            spans.append((start, candidate[start : end + 1]))
    for _, span in sorted(spans):
        try:
            return json.loads(span)
        except json.JSONDecodeError:
            continue
    return None
