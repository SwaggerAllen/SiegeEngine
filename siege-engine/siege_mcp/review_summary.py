"""Per-tier review aggregations.

Mirrors ``backend/graph/review_summary.py`` but reads review bodies
from git via ``GitView`` instead of from the DB. Output shape matches
the existing frontend's ``TierReviewSummaryPanel`` consumer so
repointing the API later is a small change.
"""

from __future__ import annotations

import statistics
from typing import Any

from siege_mcp.git_view import GitView
from siege_mcp.parsers.review_xml import ReviewXMLError, parse_review
from siege_mcp.state import State, Tier

HIST_BANDS = (
    (0, 30),
    (31, 60),
    (61, 85),
    (86, 100),
)
BAND_LABELS = ("0-30", "31-60", "61-85", "86-100")


def _scope_id(state: State) -> str:
    """Display identifier for a scope.

    Phase-qualified for a phased impl/fanin node so two phased nodes
    for one subcomponent / comp don't collapse to one identifier in
    the aggregation or the worst-first summary text.
    """
    base = state.scope.comp_id or state.scope.sub_id or ""
    if state.scope.phase is not None:
        return f"{base}@p{state.scope.phase}"
    return base


def _histogram(scores: list[int]) -> dict[str, int]:
    out = {label: 0 for label in BAND_LABELS}
    for score in scores:
        for (lo, hi), label in zip(HIST_BANDS, BAND_LABELS, strict=False):
            if lo <= score <= hi:
                out[label] += 1
                break
    return out


def build_review_summary(view: GitView, tier: Tier) -> dict[str, Any]:
    """Aggregate parsed reviews across a tier on a ref."""
    scopes_payload: list[dict[str, Any]] = []
    scores: list[int] = []
    intros: list[tuple[int, str, str]] = []

    for state in view.list_tier(tier):
        review_block = state.review
        if not review_block:
            scopes_payload.append(
                {
                    "scope_id": _scope_id(state),
                    "parent_id": state.scope.parent_id,
                    "phase": state.scope.phase,
                    "score": None,
                    "status": state.status,
                    "intro": "",
                }
            )
            continue
        try:
            body = view.read_body_text(review_block.body_path)
            parsed = parse_review(body)
        except (ReviewXMLError, Exception):  # noqa: BLE001 — keep aggregation alive
            scopes_payload.append(
                {
                    "scope_id": _scope_id(state),
                    "parent_id": state.scope.parent_id,
                    "phase": state.scope.phase,
                    "score": review_block.score,
                    "status": state.status,
                    "intro": "",
                    "parse_error": True,
                }
            )
            continue
        scopes_payload.append(
            {
                "scope_id": _scope_id(state),
                "parent_id": state.scope.parent_id,
                "phase": state.scope.phase,
                "score": parsed.score,
                "status": state.status,
                "intro": parsed.intro,
            }
        )
        scores.append(parsed.score)
        intros.append((parsed.score, _scope_id(state), parsed.intro))

    intros.sort(key=lambda t: (t[0], t[1]))
    summary_text = "\n\n".join(
        f"### {scope_id} ({score})\n\n{intro}" for score, scope_id, intro in intros if intro
    )

    aggregates: dict[str, Any] = {}
    if scores:
        aggregates = {
            "min": min(scores),
            "max": max(scores),
            "mean": round(statistics.mean(scores), 1),
            "median": statistics.median(scores),
            "count": len(scores),
        }

    return {
        "tier": tier,
        "ref": view.ref,
        "ref_head_sha": view.head_sha,
        "histogram": _histogram(scores),
        "aggregates": aggregates,
        "scopes": scopes_payload,
        "summary_text": summary_text,
    }
