"""``compute_plan`` — the phasing projection.

A pure, read-only projection (same shape contract as
``review_summary.build_review_summary`` / ``structure.build_structure_summary``):
it takes a ``GitView`` and returns a JSON-ready dict. It reads the
phase registry + the comparch / subcomparch / requirements tiers and
derives, per phase, the impl nodes to build and their topological
order. It does NOT write — the ``mint-plan`` skill materializes
``state/plan.json`` and the per-node impl state files.

The model (see ``/root/.claude/plans/pure-crafting-marshmallow.md``):

- Arch tiers (feature_expansion … subcomparch) build whole and
  unphased. Phasing partitions only the impl tier.
- The phase registry (``state/phases/<id>.json``) assigns features to
  ordered phases — the user's release-planning intent.
- A component's *effective phase* = ``min(assigned phase, earliest
  phase of anything that requires it)``, propagated transitively
  backward along comparch dependency edges. A component pulled earlier
  than its assigned phase is recorded as a rearrangement; the registry
  is never mutated.
- A subcomponent gets one impl node per phase in which it picks up new
  feature obligations. Each node's *closure* — the responsibilities it
  implements — is cumulative (phase N ⊇ phase N-1).
"""

from __future__ import annotations

import json
import logging
from typing import Any

from siege_mcp.git_view import GitView
from siege_mcp.state import now_iso

logger = logging.getLogger(__name__)


def _load_phase_registry(view: GitView) -> list[dict[str, Any]]:
    """Load ``state/phases/<id>.json`` files, sorted by ``order``.

    Same direct-tree-read pattern as ``tools.list_batches`` — the
    registry isn't a tier, so it isn't in the ``GitView`` state index.
    """
    phases: list[dict[str, Any]] = []
    for path in view.clone.ls_tree(view.head_sha, "state/phases/"):
        if not path.endswith(".json"):
            continue
        try:
            raw = view.clone.show_blob(view.head_sha, path).decode("utf-8")
            data = json.loads(raw)
        except Exception as exc:  # noqa: BLE001 — skip malformed, keep going
            logger.warning("Skipping malformed phase registry file %s: %s", path, exc)
            continue
        phases.append(data)
    phases.sort(key=lambda p: p.get("order", 0))
    return phases


def _topo_order(
    nodes: list[tuple[str, str]], precedes: dict[tuple[str, str], set[tuple[str, str]]]
):
    """Kahn topological sort over (comp, sub) node ids.

    ``precedes[x]`` is the set of nodes that must come *after* x.
    Returns (ordered, leftover) — leftover is non-empty only on a
    dependency cycle, in which case those nodes are appended by the
    caller and a warning is raised.
    """
    indeg: dict[tuple[str, str], int] = {n: 0 for n in nodes}
    for x in nodes:
        for y in precedes.get(x, set()):
            if y in indeg:
                indeg[y] += 1
    ready = sorted(n for n in nodes if indeg[n] == 0)
    ordered: list[tuple[str, str]] = []
    while ready:
        x = ready.pop(0)
        ordered.append(x)
        for y in sorted(precedes.get(x, set())):
            if y in indeg:
                indeg[y] -= 1
                if indeg[y] == 0:
                    ready.append(y)
        ready.sort()
    leftover = [n for n in nodes if n not in ordered]
    return ordered, leftover


def compute_plan(view: GitView) -> dict[str, Any]:
    """Compute the phasing plan for a project ref. Pure projection."""
    errors: list[str] = []
    warnings: list[str] = []

    # ---- 1. phase registry → feature→phase map ----
    registry = _load_phase_registry(view)
    if not registry:
        errors.append("no phase registry found at state/phases/ — nothing to plan")
    feature_phase: dict[str, int] = {}
    for phase in registry:
        order = phase.get("order", 0)
        for feat_id in phase.get("feature_ids", []):
            feature_phase[feat_id] = order
    max_order = max((p.get("order", 0) for p in registry), default=1)

    # ---- 2. tier reads ----
    comps = {s.scope.comp_id: s for s in view.list_tier("comparch") if s.scope.comp_id}
    subcomps = view.list_tier("subcomparch")
    # A requirement scope is keyed by comp_id == resp_id; meta.feature_id
    # is the feature it derives from (the walk _base.related_features_summary uses).
    resp_to_feat: dict[str, str] = {}
    for s in view.list_tier("requirements"):
        if s.scope.comp_id and s.meta.get("feature_id"):
            resp_to_feat[s.scope.comp_id] = s.meta["feature_id"]

    # Every feature must be assigned to a phase — hard error otherwise.
    for s in view.list_tier("feature_expansion"):
        fid = s.scope.comp_id
        if fid and fid not in feature_phase:
            errors.append(f"feature {fid} is not assigned to any phase")

    # ---- 3. comp → served features → assigned phase ----
    def comp_features(comp_state) -> set[str]:  # type: ignore[no-untyped-def]
        feats: set[str] = set()
        for resp in comp_state.meta.get("parent_resps", []):
            f = resp_to_feat.get(resp)
            if f:
                feats.add(f)
        return feats

    assigned: dict[str, int] = {}
    for cid, cstate in comps.items():
        phs = [feature_phase[f] for f in comp_features(cstate) if f in feature_phase]
        if phs:
            assigned[cid] = min(phs)
        else:
            assigned[cid] = max_order
            warnings.append(
                f"comp {cid} is unreachable from any phased feature; "
                f"scheduled in the final phase (order {max_order})"
            )

    # ---- 4. effective-phase fixpoint (backward over comparch deps) ----
    # `A depends on B` ⇒ B must be ready when A builds ⇒ effective[B] ≤ effective[A].
    effective: dict[str, int] = dict(assigned)
    changed = True
    while changed:
        changed = False
        for cid, cstate in comps.items():
            for dep in cstate.edges.get("dependencies", []):
                if dep in effective and effective[dep] > effective[cid]:
                    effective[dep] = effective[cid]
                    changed = True

    # pull_floor[C] = earliest phase a *dependent* of C requires C —
    # excludes C's own features. A dependent forces C's whole API
    # (every resp) earlier, since comparch dep edges are comp-granular
    # (we can't tell which resp the dependent needs). But C's own
    # later-phase responsibilities are NOT pulled by this — that's why
    # pull_floor is separate from `assigned`. No dependent → no floor.
    no_pull = max_order + 1
    pull_floor: dict[str, int] = {}
    for cid in comps:
        dependents = [did for did, ds in comps.items() if cid in ds.edges.get("dependencies", [])]
        pull_floor[cid] = min((effective[d] for d in dependents), default=no_pull)

    # ---- 5. impl-node minting (per subcomp, per phase) ----
    existing_impl = {
        (s.scope.parent_id, s.scope.sub_id, s.scope.phase): s for s in view.list_tier("impl")
    }
    impl_nodes: list[dict[str, Any]] = []
    for sstate in subcomps:
        pcid = sstate.scope.parent_id
        psub = sstate.scope.sub_id
        if pcid is None or psub is None:
            warnings.append(
                f"subcomparch scope {sstate.scope.key()} is missing parent_id/sub_id; skipped"
            )
            continue
        if pcid not in effective:
            warnings.append(
                f"subcomp {psub} has no comparch parent {pcid!r}; skipped from the plan"
            )
            continue
        comp_eff = effective[pcid]
        floor = pull_floor[pcid]

        # resp → effective resp phase. Natural phase = the phase of the
        # feature the resp serves (or the comp's assigned phase if the
        # resp traces to no phased feature — owned work). A dependent's
        # pull (`floor`) caps it earlier; the comp's own other resps
        # never do.
        resp_phase: dict[str, int] = {}
        for resp in sstate.meta.get("parent_resps", []):
            f = resp_to_feat.get(resp)
            fp = feature_phase.get(f) if f else None
            natural = fp if fp is not None else assigned[pcid]
            resp_phase[resp] = min(natural, floor)

        # One impl node per distinct resp phase — that's where new work
        # appears for this subcomponent.
        node_phases = set(resp_phase.values())
        if not node_phases:
            node_phases = {comp_eff}
            warnings.append(
                f"subcomp {psub} owns no responsibilities; one impl node minted at phase {comp_eff}"
            )

        for n in sorted(node_phases):
            # cumulative closure: every resp whose effective phase ≤ N.
            closure = sorted(r for r, rp in resp_phase.items() if rp <= n)
            reason = "assigned" if assigned[pcid] == comp_eff else "pulled-earlier"
            node = {
                "parent_id": pcid,
                "sub_id": psub,
                "phase": n,
                "closure_resp_ids": closure,
                "effective_reason": reason,
            }
            # Closure-changed-after-draft guard: if an impl node already
            # exists at drafted+ and its recorded closure no longer
            # matches, the registry was edited under a built node.
            prior = existing_impl.get((pcid, psub, n))
            if prior is not None and prior.status in ("drafted", "reviewed", "approved"):
                prior_closure = sorted(prior.meta.get("parent_resps", []))
                if prior_closure != closure:
                    errors.append(
                        f"impl node {pcid}/{psub}@p{n} is already {prior.status} but its "
                        f"responsibility closure changed — regen required before re-planning"
                    )
            impl_nodes.append(node)

    # ---- 6. within-phase topological build order ----
    phases_out: list[dict[str, Any]] = []
    for phase in registry:
        order = phase.get("order", 0)
        phase_nodes = [n for n in impl_nodes if n["phase"] == order]
        node_ids = [(n["parent_id"], n["sub_id"]) for n in phase_nodes]
        # comparch dep edges restricted to comps present in this phase.
        comps_here = {pid for pid, _ in node_ids}
        precedes: dict[tuple[str, str], set[tuple[str, str]]] = {}
        for nid in node_ids:
            nid_comp = comps.get(nid[0])
            deps = nid_comp.edges.get("dependencies", []) if nid_comp else []
            # dep comp C1 must precede every node of comp cid in this phase
            for dep in deps:
                if dep not in comps_here:
                    continue
                for dep_node in (m for m in node_ids if m[0] == dep):
                    precedes.setdefault(dep_node, set()).add(nid)
        ordered, leftover = _topo_order(node_ids, precedes)
        if leftover:
            warnings.append(
                f"phase order {order}: dependency cycle among comps "
                f"{sorted({c for c, _ in leftover})}; cycle members appended unordered"
            )
        ordered_all = ordered + leftover
        build_order = [{"parent_id": c, "sub_id": s, "phase": order} for c, s in ordered_all]
        phases_out.append(
            {
                "phase_id": phase.get("phase_id", f"order_{order}"),
                "order": order,
                "name": phase.get("name", ""),
                "impl_nodes": sorted(phase_nodes, key=lambda n: (n["parent_id"], n["sub_id"])),
                "build_order": build_order,
            }
        )

    # ---- 7. rearrangements ----
    rearrangements: list[dict[str, Any]] = []
    for cid in sorted(comps):
        if effective[cid] >= assigned[cid]:
            continue
        # the dependent that pulled cid earliest
        puller = None
        for did, dstate in comps.items():
            if cid in dstate.edges.get("dependencies", []) and effective[did] == effective[cid]:
                puller = did
                break
        cname = comps[cid].meta.get("name", cid)
        pname = comps[puller].meta.get("name", puller) if puller else "(unknown)"
        rearrangements.append(
            {
                "comp_id": cid,
                "requested_phase": assigned[cid],
                "scheduled_phase": effective[cid],
                "required_by": puller,
                "line": (
                    f"comp {cid} ({cname}): requested phase {assigned[cid]}, "
                    f"scheduled phase {effective[cid]} — required by {puller} ({pname})"
                    f"@{effective[cid]}"
                ),
            }
        )

    return {
        "schema_version": 2,
        "ref": view.ref,
        "ref_head_sha": view.head_sha,
        "computed_at": now_iso(),
        "phases": phases_out,
        "rearrangements": rearrangements,
        "errors": errors,
        "warnings": warnings,
        "aggregates": {
            "phase_count": len(registry),
            "impl_node_count": len(impl_nodes),
            "rearrangement_count": len(rearrangements),
            "error_count": len(errors),
        },
    }
