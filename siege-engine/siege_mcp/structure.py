"""Per-tier structure summary.

Per-scope metrics + tier-level aggregates. Mirrors
``backend/graph/tier_structure.py`` but reads from ``GitView``. Output
shape matches the existing ``TierStructureSummaryPanel`` consumer.

The metric set per tier is intentionally minimal — counts, ratios,
kind distributions. Per-tier readers can extend by adding entries to
``_TIER_METRICS``.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from siege_mcp.git_view import GitView
from siege_mcp.state import State, Tier


def _comparch_per_node(state: State) -> dict[str, Any]:
    return {
        "scope_id": state.scope.comp_id,
        "name": state.meta.get("name", ""),
        "kind": state.meta.get("kind", ""),
        "is_foundation": state.is_foundation,
        "resp_count": len(state.meta.get("parent_resps", [])),
        "dep_count": len(state.edges.get("dependencies", [])),
        "inbound_dep_count": 0,  # populated in aggregate pass
        "has_body": bool(state.draft),
        "status": state.status,
        "score": state.review.score if state.review else None,
    }


def _subcomparch_per_node(state: State) -> dict[str, Any]:
    return {
        "scope_id": state.scope.sub_id,
        "parent_id": state.scope.parent_id,
        "name": state.meta.get("name", ""),
        "resp_count": len(state.meta.get("parent_resps", [])),
        "dep_count": len(state.edges.get("dependencies", [])),
        "has_body": bool(state.draft),
        "status": state.status,
        "score": state.review.score if state.review else None,
    }


def _generic_per_node(state: State) -> dict[str, Any]:
    return {
        "scope_id": state.scope.comp_id or state.scope.sub_id,
        "parent_id": state.scope.parent_id,
        "name": state.meta.get("name", ""),
        "has_body": bool(state.draft),
        "status": state.status,
        "score": state.review.score if state.review else None,
    }


_PER_NODE: dict[Tier, Any] = {
    "comparch": _comparch_per_node,
    "subcomparch": _subcomparch_per_node,
    "feature_expansion": _generic_per_node,
    "requirements": _generic_per_node,
    "sysarch": _generic_per_node,
    "impl": _subcomparch_per_node,
    "fanin": _generic_per_node,
}


def build_structure_summary(view: GitView, tier: Tier) -> dict[str, Any]:
    states = view.list_tier(tier)
    per_node = [_PER_NODE.get(tier, _generic_per_node)(s) for s in states]

    if tier == "comparch":
        inbound: Counter[str] = Counter()
        for s in states:
            for dep in s.edges.get("dependencies", []):
                inbound[dep] += 1
        for row in per_node:
            row["inbound_dep_count"] = inbound.get(row["scope_id"], 0)

    aggregate: dict[str, Any] = {
        "count": len(states),
        "with_body": sum(1 for r in per_node if r["has_body"]),
        "approved": sum(1 for r in per_node if r["status"] == "approved"),
        "reviewed": sum(1 for r in per_node if r["status"] == "reviewed"),
        "drafted": sum(1 for r in per_node if r["status"] == "drafted"),
    }
    if tier == "comparch":
        aggregate["foundation_count"] = sum(1 for r in per_node if r.get("is_foundation"))
        kinds = Counter(r.get("kind") for r in per_node if r.get("kind"))
        aggregate["kind_distribution"] = dict(kinds)
        aggregate["dep_count_distribution"] = dict(Counter(r["dep_count"] for r in per_node))

    return {
        "tier": tier,
        "ref": view.ref,
        "ref_head_sha": view.head_sha,
        "per_node": per_node,
        "aggregate": aggregate,
    }
