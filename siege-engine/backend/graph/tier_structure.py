"""Per-tier structure summaries for the tier-ops dashboard.

Read-side aggregation that walks each tier's projection state and
returns per-node metrics + tier-level aggregates. The frontend
:class:`TierStructureSummaryPanel` renders the result as a sortable
table + aggregate stats so the user can see distribution shape
before picking a sample / cohort to act against.

Eight tiers covered: ``expansion``, ``requirements``, ``sysarch``,
``comparch``, ``subcomparch``, ``impl``, ``fanin``, ``references``.
The first six match the tier-ops registry; ``fanin`` and
``references`` deliberately don't have Reset / Review-sweep ops
(see ``backend.graph.tier_ops_routes`` module docstring) but
benefit from the same metadata visibility, so they live here in a
parallel registry that doesn't depend on ``BootstrapTierConfig``.

Read-only by design — never mutates anything.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models.node import Edge, Node

# ── Output shape ───────────────────────────────────────────────────


@dataclass(frozen=True)
class NodeRow:
    """One row in the per-node table.

    ``metrics`` is an open-ended dict so each tier can carry its own
    columns. The frontend reads keys from the first row to derive
    the table's column set.
    """

    id: str
    name: str
    metrics: dict[str, Any]


@dataclass(frozen=True)
class StructureSummary:
    tier: str
    tier_name: str
    per_node: tuple[NodeRow, ...]
    aggregate: dict[str, Any]


# ── Shared helpers ─────────────────────────────────────────────────


def distribution_stats(values: list[int] | list[float]) -> dict[str, Any]:
    """Return min / median / mean / p90 / max for a list of numbers.

    Empty input returns a dict with ``count=0`` and the rest ``None``.
    """
    if not values:
        return {
            "count": 0,
            "min": None,
            "median": None,
            "mean": None,
            "p90": None,
            "max": None,
        }
    sorted_v = sorted(values)
    n = len(sorted_v)
    p90_idx = max(0, min(n - 1, int(round(0.9 * (n - 1)))))
    return {
        "count": n,
        "min": sorted_v[0],
        "median": statistics.median(sorted_v),
        "mean": statistics.fmean(sorted_v),
        "p90": sorted_v[p90_idx],
        "max": sorted_v[-1],
    }


def count_by(items: list[Any], key_fn: Callable[[Any], str]) -> dict[str, int]:
    """Group ``items`` by the result of ``key_fn`` and return counts."""
    counts: dict[str, int] = defaultdict(int)
    for item in items:
        counts[key_fn(item)] += 1
    return dict(counts)


# ── Edge / fragment helpers ────────────────────────────────────────


def _edges_by_kind(edges: list[Edge], kind: str) -> list[Edge]:
    return [e for e in edges if e.edge_type == kind]


def _has_content(node: Node) -> bool:
    return bool((node.content or "").strip())


# ── Per-tier extractors ────────────────────────────────────────────


def extract_expansion_structure(session: Session, project_id: str) -> StructureSummary:
    """Expansion tier — one expansion node + the feat_* nodes it minted."""
    nodes = list(session.execute(select(Node).where(Node.project_id == project_id)).scalars())
    expansion_nodes = [n for n in nodes if n.tier == "expansion"]
    feats = [n for n in nodes if n.tier == "feat"]

    per_node: list[NodeRow] = []
    for n in expansion_nodes:
        per_node.append(
            NodeRow(
                id=n.id,
                name=n.name or n.id,
                metrics={
                    "has_content": _has_content(n),
                    "feat_count": len(feats),
                    "implicit_feat_count": sum(1 for f in feats if f.is_implicit),
                    "deferred_feat_count": sum(1 for f in feats if f.is_deferred),
                },
            )
        )

    group_count = len({f.group_label for f in feats if f.group_label})
    aggregate = {
        "feat_count": len(feats),
        "implicit_feat_count": sum(1 for f in feats if f.is_implicit),
        "deferred_feat_count": sum(1 for f in feats if f.is_deferred),
        "group_count": group_count,
    }
    return StructureSummary(
        tier="expansion",
        tier_name="Feature expansion",
        per_node=tuple(per_node),
        aggregate=aggregate,
    )


def extract_requirements_structure(session: Session, project_id: str) -> StructureSummary:
    """Requirements tier — one reqs node + the resp / feat / policy structure."""
    nodes = list(session.execute(select(Node).where(Node.project_id == project_id)).scalars())
    edges = list(session.execute(select(Edge).where(Edge.project_id == project_id)).scalars())

    reqs_nodes = [n for n in nodes if n.tier == "reqs"]
    top_resps = [n for n in nodes if n.tier == "resp" and n.parent_id is None]
    feats = [n for n in nodes if n.tier == "feat" and not n.is_deferred]
    policies = [n for n in nodes if n.tier == "policy" and n.parent_id is None]

    decomp_edges = _edges_by_kind(edges, "decomposition")
    feat_ids = {f.id for f in feats}
    resp_ids = {r.id for r in top_resps}
    # resp → feat decomposition: source is resp, target is feat. Count
    # per resp.
    feats_per_resp: dict[str, int] = defaultdict(int)
    for e in decomp_edges:
        if e.source_id in resp_ids and e.target_id in feat_ids:
            feats_per_resp[e.source_id] += 1

    per_node: list[NodeRow] = []
    for n in reqs_nodes:
        per_node.append(
            NodeRow(
                id=n.id,
                name=n.name or n.id,
                metrics={
                    "has_content": _has_content(n),
                    "top_resp_count": len(top_resps),
                    "feat_count": len(feats),
                    "policy_count": len(policies),
                },
            )
        )

    aggregate = {
        "top_resp_count": len(top_resps),
        "feat_count": len(feats),
        "policy_count": len(policies),
        "feats_per_resp": distribution_stats(list(feats_per_resp.values())),
    }
    return StructureSummary(
        tier="requirements",
        tier_name="Requirements",
        per_node=tuple(per_node),
        aggregate=aggregate,
    )


def extract_sysarch_structure(session: Session, project_id: str) -> StructureSummary:
    """Sysarch tier — one sysarch node + the top-level comp landscape."""
    nodes = list(session.execute(select(Node).where(Node.project_id == project_id)).scalars())
    edges = list(session.execute(select(Edge).where(Edge.project_id == project_id)).scalars())

    sysarch_nodes = [n for n in nodes if n.tier == "sysarch"]
    top_comps = [n for n in nodes if n.tier == "comp" and n.parent_id is None]
    top_policies = [n for n in nodes if n.tier == "policy" and n.parent_id is None]

    top_comp_ids = {c.id for c in top_comps}
    dep_edges = [
        e
        for e in _edges_by_kind(edges, "dependency")
        if e.source_id in top_comp_ids and e.target_id in top_comp_ids
    ]
    domain_parent_edges = [
        e
        for e in _edges_by_kind(edges, "domain_parent")
        if e.source_id in top_comp_ids and e.target_id in top_comp_ids
    ]

    domain_count = sum(1 for c in top_comps if c.kind == "domain")
    presentational_count = sum(1 for c in top_comps if c.kind == "presentational")
    foundation_count = sum(1 for c in top_comps if c.is_foundation)

    per_node: list[NodeRow] = []
    for n in sysarch_nodes:
        per_node.append(
            NodeRow(
                id=n.id,
                name=n.name or n.id,
                metrics={
                    "has_content": _has_content(n),
                    "top_comp_count": len(top_comps),
                    "domain_count": domain_count,
                    "presentational_count": presentational_count,
                    "foundation_count": foundation_count,
                    "top_dep_count": len(dep_edges),
                    "domain_parent_count": len(domain_parent_edges),
                    "top_policy_count": len(top_policies),
                },
            )
        )

    aggregate = {
        "top_comp_count": len(top_comps),
        "domain_count": domain_count,
        "presentational_count": presentational_count,
        "foundation_count": foundation_count,
        "top_dep_count": len(dep_edges),
        "domain_parent_count": len(domain_parent_edges),
        "top_policy_count": len(top_policies),
    }
    return StructureSummary(
        tier="sysarch",
        tier_name="Sysarch",
        per_node=tuple(per_node),
        aggregate=aggregate,
    )


def extract_comparch_structure(session: Session, project_id: str) -> StructureSummary:
    """Comparch tier — per top-level comp.

    Most load-bearing extractor: drives canonical-cohort selection
    for the subcomp campaign. Surfaces the axes the sampler stratifies
    against (kind, foundation, sub count, resp/feat/dep counts,
    multi-owner prevalence).
    """
    nodes = list(session.execute(select(Node).where(Node.project_id == project_id)).scalars())
    edges = list(session.execute(select(Edge).where(Edge.project_id == project_id)).scalars())

    top_comps = [n for n in nodes if n.tier == "comp" and n.parent_id is None]
    all_comps = [n for n in nodes if n.tier == "comp"]
    comp_ids = {c.id for c in all_comps}

    # subs grouped by parent
    subs_by_parent: dict[str, list[Node]] = defaultdict(list)
    for n in all_comps:
        if n.parent_id is not None:
            subs_by_parent[n.parent_id].append(n)

    decomp = _edges_by_kind(edges, "decomposition")
    deps = _edges_by_kind(edges, "dependency")

    per_node: list[NodeRow] = []
    for c in top_comps:
        subs = subs_by_parent.get(c.id, [])
        sub_ids = {s.id for s in subs}
        # Top-level resps + feats assigned to this comp via decomp
        # edges (resp → comp / feat → comp).
        resp_targets = {
            e.source_id for e in decomp if e.target_id == c.id and e.source_id.startswith("resp_")
        }
        feat_targets = {
            e.source_id for e in decomp if e.target_id == c.id and e.source_id.startswith("feat_")
        }
        # Outbound deps from this top-level comp.
        out_deps = [e for e in deps if e.source_id == c.id and e.target_id in comp_ids]
        # Sub-deps: dependency edges between this comp's own subs.
        sub_deps = [e for e in deps if e.source_id in sub_ids and e.target_id in sub_ids]
        # Multi-owner resps within this comp: resps with decomposition
        # edges to >1 of this comp's subs.
        sub_owners_per_resp: dict[str, set[str]] = defaultdict(set)
        for e in decomp:
            if e.target_id in sub_ids and e.source_id.startswith("resp_"):
                sub_owners_per_resp[e.source_id].add(e.target_id)
        multi_owner_resps = sum(1 for owners in sub_owners_per_resp.values() if len(owners) > 1)

        per_node.append(
            NodeRow(
                id=c.id,
                name=c.name or c.id,
                metrics={
                    "kind": c.kind,
                    "is_foundation": c.is_foundation,
                    "has_content": _has_content(c),
                    "sub_count": len(subs),
                    "resp_count": len(resp_targets),
                    "feat_count": len(feat_targets),
                    "dep_count": len(out_deps),
                    "sub_dep_count": len(sub_deps),
                    "multi_owner_resp_count": multi_owner_resps,
                    "empty_subcomponents": len(subs) == 0,
                },
            )
        )

    sub_counts = [int(r.metrics["sub_count"]) for r in per_node]
    resp_counts = [int(r.metrics["resp_count"]) for r in per_node]
    feat_counts = [int(r.metrics["feat_count"]) for r in per_node]
    dep_counts = [int(r.metrics["dep_count"]) for r in per_node]
    multi_owner_counts = [int(r.metrics["multi_owner_resp_count"]) for r in per_node]

    aggregate = {
        "top_comp_count": len(top_comps),
        "domain_count": sum(1 for c in top_comps if c.kind == "domain"),
        "presentational_count": sum(1 for c in top_comps if c.kind == "presentational"),
        "foundation_count": sum(1 for c in top_comps if c.is_foundation),
        "with_content_count": sum(1 for r in per_node if r.metrics["has_content"]),
        "empty_subs_count": sum(1 for r in per_node if r.metrics["empty_subcomponents"]),
        "any_multi_owner_count": sum(1 for v in multi_owner_counts if v > 0),
        "sub_count_dist": distribution_stats(sub_counts),
        "resp_count_dist": distribution_stats(resp_counts),
        "feat_count_dist": distribution_stats(feat_counts),
        "dep_count_dist": distribution_stats(dep_counts),
        "multi_owner_dist": distribution_stats(multi_owner_counts),
    }
    return StructureSummary(
        tier="comparch",
        tier_name="Comparch",
        per_node=tuple(per_node),
        aggregate=aggregate,
    )


def extract_subcomparch_structure(session: Session, project_id: str) -> StructureSummary:
    """Subcomparch tier — per subcomponent.

    Same axes as comparch but narrowed to the leaf level: which
    parent, which kind it inherits, what it owns, what it depends on.
    """
    nodes = list(session.execute(select(Node).where(Node.project_id == project_id)).scalars())
    edges = list(session.execute(select(Edge).where(Edge.project_id == project_id)).scalars())

    all_comps = [n for n in nodes if n.tier == "comp"]
    comps_by_id = {c.id: c for c in all_comps}
    subs = [c for c in all_comps if c.parent_id is not None]
    sub_ids = {s.id for s in subs}
    top_comp_ids = {c.id for c in all_comps if c.parent_id is None}

    decomp = _edges_by_kind(edges, "decomposition")
    deps = _edges_by_kind(edges, "dependency")

    # Multi-owner detection at parent scope: which (parent_id, resp_id)
    # pairs have >1 sub claiming.
    sub_owners_per_resp_per_parent: dict[tuple[str, str], set[str]] = defaultdict(set)
    for e in decomp:
        if e.target_id in sub_ids and e.source_id.startswith("resp_"):
            sub = comps_by_id.get(e.target_id)
            if sub and sub.parent_id is not None:
                sub_owners_per_resp_per_parent[(sub.parent_id, e.source_id)].add(e.target_id)

    per_node: list[NodeRow] = []
    for s in subs:
        # ``subs`` is filtered to nodes with non-None parent_id;
        # narrow explicitly so mypy can use ``parent_id`` as a
        # ``str`` in the dict lookups below.
        parent_id = s.parent_id
        assert parent_id is not None
        owns_resps = {
            e.source_id for e in decomp if e.target_id == s.id and e.source_id.startswith("resp_")
        }
        owns_feats = {
            e.source_id for e in decomp if e.target_id == s.id and e.source_id.startswith("feat_")
        }
        # Outbound deps from this sub. Targets can be same-parent
        # siblings or parent-sibling top-level comps.
        out_deps = [e for e in deps if e.source_id == s.id]
        same_parent_dep_count = 0
        parent_sibling_dep_count = 0
        for e in out_deps:
            target = comps_by_id.get(e.target_id)
            if target is None:
                continue
            if target.parent_id == parent_id:
                same_parent_dep_count += 1
            elif target.id in top_comp_ids:
                parent_sibling_dep_count += 1
        # Co-ownership: this sub claims a resp that another sub of
        # the same parent also claims.
        co_owned = sum(
            1
            for r in owns_resps
            if len(sub_owners_per_resp_per_parent.get((parent_id, r), set())) > 1
        )
        parent = comps_by_id.get(parent_id)
        per_node.append(
            NodeRow(
                id=s.id,
                name=s.name or s.id,
                metrics={
                    "parent_id": parent_id,
                    "parent_name": (parent.name if parent else None) or parent_id,
                    "parent_kind": parent.kind if parent else None,
                    "has_content": _has_content(s),
                    "owns_resp_count": len(owns_resps),
                    "owns_feat_count": len(owns_feats),
                    "dep_count": len(out_deps),
                    "same_parent_dep_count": same_parent_dep_count,
                    "parent_sibling_dep_count": parent_sibling_dep_count,
                    "co_owned_resp_count": co_owned,
                },
            )
        )

    subs_per_parent: dict[str, int] = defaultdict(int)
    for s in subs:
        if s.parent_id is not None:
            subs_per_parent[s.parent_id] += 1

    dep_counts = [int(r.metrics["dep_count"]) for r in per_node]
    owns_resp_counts = [int(r.metrics["owns_resp_count"]) for r in per_node]
    co_owned_counts = [int(r.metrics["co_owned_resp_count"]) for r in per_node]

    aggregate = {
        "sub_count": len(subs),
        "with_content_count": sum(1 for r in per_node if r.metrics["has_content"]),
        "any_co_owned_count": sum(1 for v in co_owned_counts if v > 0),
        "subs_per_parent_dist": distribution_stats(list(subs_per_parent.values())),
        "dep_count_dist": distribution_stats(dep_counts),
        "owns_resp_count_dist": distribution_stats(owns_resp_counts),
    }
    return StructureSummary(
        tier="subcomparch",
        tier_name="Subcomparch",
        per_node=tuple(per_node),
        aggregate=aggregate,
    )


def extract_impl_structure(session: Session, project_id: str) -> StructureSummary:
    """Impl tier — per impl_* node.

    Impl nodes hang off either a foundation top-level comp or a
    subcomp; ``parent_id`` resolves the owner. Line count is a rough
    rendered-content size proxy (number of newlines in
    ``Node.content``).
    """
    nodes = list(session.execute(select(Node).where(Node.project_id == project_id)).scalars())
    impls = [n for n in nodes if n.tier == "impl"]
    comps_by_id = {n.id: n for n in nodes if n.tier == "comp"}

    per_node: list[NodeRow] = []
    line_counts: list[int] = []
    for n in impls:
        owner = comps_by_id.get(n.parent_id) if n.parent_id else None
        # If owner is a sub, walk up one to find the top-level.
        top_owner: Node | None = None
        if owner is not None:
            top_owner = owner if owner.parent_id is None else comps_by_id.get(owner.parent_id)
        line_count = (n.content or "").count("\n") + (1 if (n.content or "").strip() else 0)
        line_counts.append(line_count)
        per_node.append(
            NodeRow(
                id=n.id,
                name=n.name or n.id,
                metrics={
                    "owner_id": n.parent_id,
                    "owner_name": (owner.name if owner else None) or n.parent_id,
                    "top_level_id": top_owner.id if top_owner else None,
                    "top_level_name": top_owner.name if top_owner else None,
                    "has_content": _has_content(n),
                    "line_count": line_count,
                },
            )
        )

    aggregate = {
        "impl_count": len(impls),
        "with_content_count": sum(1 for r in per_node if r.metrics["has_content"]),
        "line_count_dist": distribution_stats(line_counts),
    }
    return StructureSummary(
        tier="impl",
        tier_name="Impl",
        per_node=tuple(per_node),
        aggregate=aggregate,
    )


def extract_fanin_structure(session: Session, project_id: str) -> StructureSummary:
    """Fan-in tier — per fanin_* node.

    Each fanin lives under a domain top-level comp; surfaces
    contributing-impl count by walking the comp's impl descendants.
    """
    nodes = list(session.execute(select(Node).where(Node.project_id == project_id)).scalars())
    fanins = [n for n in nodes if n.tier == "fanin"]
    comps_by_id = {n.id: n for n in nodes if n.tier == "comp"}
    impls = [n for n in nodes if n.tier == "impl"]

    # Group impls by their top-level comp owner.
    impls_by_top: dict[str, list[Node]] = defaultdict(list)
    for impl in impls:
        owner = comps_by_id.get(impl.parent_id) if impl.parent_id else None
        if owner is None:
            continue
        top_id = owner.id if owner.parent_id is None else owner.parent_id
        if top_id is not None:
            impls_by_top[top_id].append(impl)

    per_node: list[NodeRow] = []
    contributing_counts: list[int] = []
    for n in fanins:
        owner = comps_by_id.get(n.parent_id) if n.parent_id else None
        contributing = impls_by_top.get(n.parent_id or "", []) if n.parent_id else []
        contributing_with_content = sum(1 for i in contributing if _has_content(i))
        contributing_counts.append(len(contributing))
        per_node.append(
            NodeRow(
                id=n.id,
                name=n.name or n.id,
                metrics={
                    "owner_id": n.parent_id,
                    "owner_name": (owner.name if owner else None) or n.parent_id,
                    "owner_kind": owner.kind if owner else None,
                    "has_content": _has_content(n),
                    "contributing_impl_count": len(contributing),
                    "contributing_impls_with_content": contributing_with_content,
                },
            )
        )

    aggregate = {
        "fanin_count": len(fanins),
        "with_content_count": sum(1 for r in per_node if r.metrics["has_content"]),
        "contributing_impl_dist": distribution_stats(contributing_counts),
    }
    return StructureSummary(
        tier="fanin",
        tier_name="Fan-in",
        per_node=tuple(per_node),
        aggregate=aggregate,
    )


def extract_references_structure(session: Session, project_id: str) -> StructureSummary:
    """References tier — per ref_* node."""
    nodes = list(session.execute(select(Node).where(Node.project_id == project_id)).scalars())
    refs = [n for n in nodes if n.tier == "ref"]

    per_node: list[NodeRow] = []
    content_lengths: list[int] = []
    for n in refs:
        content_len = len(n.content or "")
        content_lengths.append(content_len)
        per_node.append(
            NodeRow(
                id=n.id,
                name=n.name or n.id,
                metrics={
                    "has_content": _has_content(n),
                    "content_length": content_len,
                },
            )
        )

    aggregate = {
        "ref_count": len(refs),
        "with_content_count": sum(1 for r in per_node if r.metrics["has_content"]),
        "content_length_dist": distribution_stats(content_lengths),
    }
    return StructureSummary(
        tier="references",
        tier_name="References",
        per_node=tuple(per_node),
        aggregate=aggregate,
    )


# ── Registry ───────────────────────────────────────────────────────


_Extractor = Callable[[Session, str], StructureSummary]

TIER_STRUCTURE_EXTRACTORS: dict[str, _Extractor] = {
    "expansion": extract_expansion_structure,
    "requirements": extract_requirements_structure,
    "sysarch": extract_sysarch_structure,
    "comparch": extract_comparch_structure,
    "subcomparch": extract_subcomparch_structure,
    "impl": extract_impl_structure,
    "fanin": extract_fanin_structure,
    "references": extract_references_structure,
}


def gather_tier_structure_summary(
    session: Session,
    project_id: str,
    tier: str,
) -> StructureSummary:
    """Top-level entry — dispatches to the per-tier extractor.

    Raises ``KeyError`` when ``tier`` is not registered; caller
    translates into a 404.
    """
    if tier not in TIER_STRUCTURE_EXTRACTORS:
        raise KeyError(tier)
    return TIER_STRUCTURE_EXTRACTORS[tier](session, project_id)


def serialize_summary(summary: StructureSummary) -> dict[str, Any]:
    """Convert a :class:`StructureSummary` into JSON-friendly dicts.

    Used by the route layer to build the response body.
    """
    return {
        "tier": summary.tier,
        "tier_name": summary.tier_name,
        "per_node": [{"id": r.id, "name": r.name, "metrics": r.metrics} for r in summary.per_node],
        "aggregate": summary.aggregate,
    }
