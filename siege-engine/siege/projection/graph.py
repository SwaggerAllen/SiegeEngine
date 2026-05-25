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
- ``decomposition`` responsibility → top-level component, parsed
  from the sysarch body's per-``<component>`` ``<responsibilities>``
  blocks and alias-resolved via the sysarch identity ledger;
- ``dependency`` and ``domain_parent`` between top-level components,
  parsed from the sysarch body and alias-resolved via the sysarch
  identity ledger;
- ``dependency`` from every top-level component to the synthetic
  project-sysarch root node — surfaces the project-level techspec /
  dependency-graph baseline every component implicitly rests on;
- ``dependency`` from every top-level component to every policy
  node — the v3 read model treats policies as cross-cutting
  upstream constraints every comp's design must honor.
- ``decomposition`` responsibility → policy when the policy's
  ``<required>`` resolves to a known resp — connects the resp's
  requirement to its sysarch-tier policy mechanism.

A synthetic ``sysarch_root`` node is emitted when a sysarch ledger
exists; its name is "Project Sysarch" and its lifecycle mirrors the
sysarch substrate's own status. Per-``<policy>`` nodes (kind
``policy``) are emitted from the sysarch body's ``<policies>`` block;
their ids are minted by slugging the ``<name>`` text.

Deferred (see the v3 spec's projection-layer notes): subcomponent-level
dependency edges, and the comparch ``<owns>`` ownership projection
(resp → subcomp + feat → subcomp).
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

# Per-component ownership of top-level responsibilities:
#   <component alias="billing">
#     ...
#     <responsibilities>
#       <resp id="resp_xxx"/>
#       <resp id="resp_yyy"/>
#     </responsibilities>
#   </component>
# Source the alias from the opening-tag attrs, then walk the inner block
# for <resp id="..."/> refs and emit resp → comp decomposition edges.
_COMPONENT_BLOCK = re.compile(r"<component\b([^>]*)>(.*?)</component>", re.S)
_ALIAS_ATTR = re.compile(r'\balias\s*=\s*"([^"]*)"')
_RESP_REF = re.compile(r'<resp\s+id="([^"]+)"')

# Top-level policies inside <policies>:
#   <policy>
#     <name>LLM Telemetry</name>
#     <trigger>any LLM call</trigger>
#     <required>resp_telemetry1</required>   <!-- optional -->
#     <rationale>…</rationale>
#   </policy>
# Names are free-form text — there's no stable id in the body, so we
# slug the name to mint ``policy_<slug>`` ids in the projection.
_POLICY_BLOCK = re.compile(r"<policy\b[^>]*>(.*?)</policy>", re.S)
_POLICY_NAME = re.compile(r"<name>\s*(.*?)\s*</name>", re.S)
_POLICY_REQUIRED = re.compile(r"<required>\s*(.*?)\s*</required>", re.S)
_SLUG_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def _section(body: str, tag: str) -> str:
    """Inner text of the first ``<tag>…</tag>``, or '' if absent."""
    m = re.search(rf"<{tag}\b[^>]*>(.*?)</{tag}>", body, re.S)
    return m.group(1) if m else ""


def _slug(name: str) -> str:
    """Slug a free-form policy name to a stable id suffix.

    Lowercase, non-alphanumerics → hyphens, collapsed + trimmed. An
    empty input slugs to ``""`` — the caller falls back to a positional
    index in that case so we still emit *some* id.
    """
    return _SLUG_NON_ALNUM.sub("-", name.lower()).strip("-")


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
    top_level_comp_ids: list[str] = []
    if sysarch_manifest is not None:
        for raw in sysarch_manifest.nodes:
            nid = raw.get("id")
            if not nid:
                continue
            alias = str(raw.get("alias", "")).strip().lower()
            if alias:
                alias_to_comp[alias] = nid
            node_ids.add(nid)
            top_level_comp_ids.append(nid)
            # A component's "own" substrate is its comparch.
            comparch = view.get_state(Scope(tier="comparch", comp_id=nid))
            nodes.append(
                _node(
                    nid, "sysarch", "component", raw, parent_id=None, lifecycle=_lifecycle(comparch)
                )
            )

    # ---- synthetic project-sysarch root node ----
    # One node per project standing for the project-level sysarch
    # baseline — techspec, project-wide dependency graph, top-level
    # policies. Every top-level component dep-edges to it so the DAG
    # has a visible root every component implicitly rests on.
    sysarch_root_id: str | None = None
    if sysarch_state is not None:
        sysarch_root_id = "sysarch_root"
        node_ids.add(sysarch_root_id)
        nodes.append(
            _node(
                sysarch_root_id,
                "sysarch",
                "sysarch_root",
                {"name": "Project Sysarch", "order": -1},
                parent_id=None,
                lifecycle=_lifecycle(sysarch_state),
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

    # ---- sysarch-body-derived edges (dep, domain_parent, resp → comp) ----
    policies: list[tuple[dict[str, Any], str | None]] = []
    if sysarch_state is not None and sysarch_state.draft is not None:
        try:
            body = view.read_body_text(sysarch_state.draft.body_path)
        except Exception:  # noqa: BLE001 — body missing → no top-level edges
            body = ""
        edges.extend(_top_level_edges(body, alias_to_comp))
        for edge in _resp_to_comp_edges(body, alias_to_comp):
            if edge["source_id"] in node_ids:
                edges.append(edge)
        policies = _policy_nodes(body, _lifecycle(sysarch_state))

    # ---- policy nodes + resp → policy decomposition edges ----
    # Policy nodes come from the sysarch body, so they're scoped to
    # the sysarch substrate's own lifecycle (same as sysarch_root).
    for pnode, required in policies:
        node_ids.add(pnode["id"])
        nodes.append(pnode)
        if required and required in node_ids:
            edges.append(_edge("decomposition", required, pnode["id"]))

    # ---- comp → synthetic sysarch root + per-policy dependency edges ----
    # Every top-level comp dep-edges to the sysarch baseline (root +
    # policies) — surfaces the cross-cutting constraints every comp's
    # design must honor.
    if sysarch_root_id is not None:
        for comp_id in top_level_comp_ids:
            edges.append(_edge("dependency", comp_id, sysarch_root_id))
    for pnode, _ in policies:
        for comp_id in top_level_comp_ids:
            edges.append(_edge("dependency", comp_id, pnode["id"]))

    return {
        "ref": view.ref,
        "ref_head_sha": view.head_sha,
        "nodes": nodes,
        "edges": edges,
    }


def _resp_to_comp_edges(body: str, alias_to_comp: dict[str, str]) -> list[dict[str, Any]]:
    """For each ``<component alias="X">…<responsibilities><resp id="resp_Y"/>…``
    in a sysarch body, emit a ``decomposition`` edge resp_Y → comp_X.

    A responsibility can legitimately appear in both its owning domain
    component and a presentational counterpart (the "mirror" pattern in
    the sysarch prompt), so we dedupe on the (resp, comp) pair to avoid
    emitting the same edge twice when both blocks reference the same id.
    """
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for attrs, inner in _COMPONENT_BLOCK.findall(body):
        m = _ALIAS_ATTR.search(attrs)
        if not m:
            continue
        comp_id = alias_to_comp.get(m.group(1).strip().lower())
        if not comp_id:
            continue
        resps_section = _section(inner, "responsibilities")
        for resp_id in _RESP_REF.findall(resps_section):
            key = (resp_id, comp_id)
            if key in seen:
                continue
            seen.add(key)
            out.append(_edge("decomposition", resp_id, comp_id))
    return out


def _policy_nodes(
    body: str, sysarch_lifecycle: dict[str, Any]
) -> list[tuple[dict[str, Any], str | None]]:
    """For each ``<policy>`` block inside ``<policies>``, mint a node
    + carry its ``<required>`` resp ref (if any) for downstream edge
    emission.

    Each policy carries:
    - ``id``: ``policy_<slug-of-name>``. Policies have no stable id
      in the body — the slug *is* the id. Collisions are deduped by
      appending ``_2``, ``_3``, … so two policies named identically
      still get distinct nodes.
    - ``name``: the ``<name>`` text verbatim (display label).
    - ``kind``: ``"policy"``; ``tier``: ``"sysarch"``.
    - lifecycle: mirrors the sysarch substrate's own state — policies
      live and die with the sysarch body they were parsed from.

    Returns a list of ``(node, required_resp_id)`` tuples. The caller
    resolves the resp ref against the global node-id set; we don't do
    that here so the parser stays decoupled from the projection's
    in-progress identity tables.
    """
    out: list[tuple[dict[str, Any], str | None]] = []
    used_ids: set[str] = set()
    policies_section = _section(body, "policies")
    for order, inner in enumerate(_POLICY_BLOCK.findall(policies_section)):
        name_match = _POLICY_NAME.search(inner)
        name = name_match.group(1).strip() if name_match else ""
        slug = _slug(name) or f"unnamed-{order}"
        base_id = f"policy_{slug}"
        node_id = base_id
        # Dedupe — slugs of distinct policy names can collide, and an
        # empty slug always collides with the next empty slug. Numeric
        # suffix gives us a stable, predictable disambiguator.
        suffix = 2
        while node_id in used_ids:
            node_id = f"{base_id}_{suffix}"
            suffix += 1
        used_ids.add(node_id)
        req_match = _POLICY_REQUIRED.search(inner)
        required = req_match.group(1).strip() if req_match else None
        node = _node(
            node_id,
            "sysarch",
            "policy",
            {"name": name or node_id, "order": order},
            parent_id=None,
            lifecycle=sysarch_lifecycle,
        )
        out.append((node, required or None))
    return out


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
