"""Whole-project graph projection — the ``{nodes, edges}`` feed the DAG views.

``build_project_graph`` walks every identity ledger plus the sysarch
body and emits one cross-tier node + edge graph. Per the v3 spec §2
(Core layer), the graph is *projected*: nodes are the rehydrated
identity-ledger records, edges are parsed from bodies and resolved
against those ledgers. Nothing here is stored as truth.

Nodes — feature / responsibility / component (top-level) /
subcomponent, one per identity-ledger record. A node carries the
status + score of the substrate it is the *root* of (a component → its
comparch, a subcomponent → its subcomparch); feature / responsibility
nodes have no deeper substrate, so they carry the status of the
substrate that *declares* them (feature_expansion / requirements).

Edges:

- ``decomposition`` feature → responsibility, from each
  responsibility's feat set;
- ``dependency`` and ``domain_parent`` between top-level components,
  parsed from the sysarch body and alias-resolved via the sysarch
  identity ledger.

Deferred (see the v3 spec's projection-layer notes): subcomponent-level
dependency edges and the comparch ``<owns>`` ownership projection.
"""

from __future__ import annotations

import re
from typing import Any

from siege.git_view import GitView
from siege.state import Scope, State

# Sysarch declares its edges with attribute pairs on self-closing tags:
#   <dependencies><dep from="billing" to="auth"/></dependencies>
#   <domain-parent><parent from="ui_billing" to="billing"/></domain-parent>
# The `from` / `to` are component *aliases* — resolved to ids below.
_DEP_TAG = re.compile(r"<dep\b([^>]*)>")
_PARENT_TAG = re.compile(r"<parent\b([^>]*)>")
_FROM_ATTR = re.compile(r'\bfrom\s*=\s*"([^"]*)"')
_TO_ATTR = re.compile(r'\bto\s*=\s*"([^"]*)"')


def _section(body: str, tag: str) -> str:
    """Inner text of the first ``<tag>…</tag>``, or '' if absent."""
    m = re.search(rf"<{tag}\b[^>]*>(.*?)</{tag}>", body, re.S)
    return m.group(1) if m else ""


def _lifecycle(state: State | None) -> dict[str, Any]:
    """``status`` / ``score`` / ``has_body`` for the substrate behind a node."""
    if state is None:
        return {"status": "absent", "score": None, "has_body": False}
    return {
        "status": state.status,
        "score": state.review.score if state.review else None,
        "has_body": bool(state.draft),
    }


def _edge(edge_type: str, source: str, target: str) -> dict[str, Any]:
    return {
        "id": f"{edge_type}:{source}->{target}",
        "type": edge_type,
        "source_id": source,
        "target_id": target,
    }


def _node(
    node_id: str,
    tier: str,
    kind: str,
    raw: dict[str, Any],
    *,
    parent_id: str | None,
    lifecycle: dict[str, Any],
) -> dict[str, Any]:
    return {
        "id": node_id,
        "tier": tier,
        "kind": kind,
        "name": raw.get("name", ""),
        "parent_id": parent_id,
        "order": raw.get("order", 0),
        "is_foundation": bool(raw.get("is_foundation", False)),
        "implicit": bool(raw.get("implicit", False)),
        **lifecycle,
    }


def build_project_graph(view: GitView) -> dict[str, Any]:
    """Project the whole-project node + edge graph from a ``GitView``."""
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    node_ids: set[str] = set()

    # ---- feature nodes ----
    fe_states = view.list_tier("feature_expansion")
    fe_lifecycle = _lifecycle(fe_states[0] if fe_states else None)
    fe_manifest = view.manifest_for_tier("feature_expansion")
    if fe_manifest is not None:
        for raw in fe_manifest.nodes:
            nid = raw.get("id")
            if not nid:
                continue
            node_ids.add(nid)
            nodes.append(
                _node(
                    nid, "feature_expansion", "feature", raw, parent_id=None, lifecycle=fe_lifecycle
                )
            )

    # ---- responsibility nodes ----
    req_states = view.list_tier("requirements")
    req_lifecycle = _lifecycle(req_states[0] if req_states else None)
    req_manifest = view.manifest_for_tier("requirements")
    if req_manifest is not None:
        for raw in req_manifest.nodes:
            nid = raw.get("id")
            if not nid:
                continue
            node_ids.add(nid)
            nodes.append(
                _node(
                    nid,
                    "requirements",
                    "responsibility",
                    raw,
                    parent_id=None,
                    lifecycle=req_lifecycle,
                )
            )

    # ---- component (top-level) nodes ----
    sysarch_states = view.list_tier("sysarch")
    sysarch_state = sysarch_states[0] if sysarch_states else None
    sysarch_manifest = view.manifest_for_tier("sysarch")
    alias_to_comp: dict[str, str] = {}
    if sysarch_manifest is not None:
        for raw in sysarch_manifest.nodes:
            nid = raw.get("id")
            if not nid:
                continue
            alias = str(raw.get("alias", "")).strip().lower()
            if alias:
                alias_to_comp[alias] = nid
            node_ids.add(nid)
            # A component's "own" substrate is its comparch.
            comparch = view.get_state(Scope(tier="comparch", comp_id=nid))
            nodes.append(
                _node(
                    nid, "sysarch", "component", raw, parent_id=None, lifecycle=_lifecycle(comparch)
                )
            )

    # ---- subcomponent nodes ----
    for comparch_state in view.list_tier("comparch"):
        parent_comp = comparch_state.scope.comp_id
        manifest = view.get_manifest(comparch_state.scope)
        if manifest is None:
            continue
        for raw in manifest.nodes:
            nid = raw.get("id")
            if not nid:
                continue
            node_ids.add(nid)
            # A subcomponent's "own" substrate is its subcomparch.
            sub = view.get_state(Scope(tier="subcomparch", parent_id=parent_comp, sub_id=nid))
            nodes.append(
                _node(
                    nid,
                    "comparch",
                    "subcomponent",
                    raw,
                    parent_id=parent_comp,
                    lifecycle=_lifecycle(sub),
                )
            )

    # ---- decomposition edges: feature -> responsibility ----
    if req_manifest is not None:
        for raw in req_manifest.nodes:
            resp_id = raw.get("id")
            if not resp_id:
                continue
            for feat_id in raw.get("feats", []):
                if feat_id in node_ids:
                    edges.append(_edge("decomposition", feat_id, resp_id))

    # ---- dependency + domain_parent edges (top-level) ----
    if sysarch_state is not None and sysarch_state.draft is not None:
        try:
            body = view.read_body_text(sysarch_state.draft.body_path)
        except Exception:  # noqa: BLE001 — body missing → no top-level edges
            body = ""
        edges.extend(_top_level_edges(body, alias_to_comp))

    return {
        "ref": view.ref,
        "ref_head_sha": view.head_sha,
        "nodes": nodes,
        "edges": edges,
    }


def _top_level_edges(body: str, alias_to_comp: dict[str, str]) -> list[dict[str, Any]]:
    """Parse ``<dependencies>`` / ``<domain-parent>`` from a sysarch body,
    resolving component aliases to ids. An edge whose endpoints don't both
    resolve is dropped."""
    out: list[dict[str, Any]] = []

    def _resolve(attrs: str) -> tuple[str | None, str | None]:
        fm = _FROM_ATTR.search(attrs)
        tm = _TO_ATTR.search(attrs)
        src = alias_to_comp.get(fm.group(1).strip().lower()) if fm else None
        dst = alias_to_comp.get(tm.group(1).strip().lower()) if tm else None
        return src, dst

    for attrs in _DEP_TAG.findall(_section(body, "dependencies")):
        src, dst = _resolve(attrs)
        if src and dst:
            out.append(_edge("dependency", src, dst))
    for attrs in _PARENT_TAG.findall(_section(body, "domain-parent")):
        src, dst = _resolve(attrs)
        if src and dst:
            out.append(_edge("domain_parent", src, dst))
    return out
