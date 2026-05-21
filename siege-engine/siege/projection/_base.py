"""Cross-tier helpers used by per-tier readers.

The new model: state JSON carries everything downstream readers need.
The writing skill (draft-*) computes the precomputed view at commit
time and writes it into the state JSON's ``meta`` + ``edges`` blocks.
Downstream readers walk those blocks instead of doing graph queries
at read time. This is a deliberate inversion from the old DB model —
denormalize on write, normalize-by-reading on read.

The helpers here factor out the genuinely cross-tier reads:

- ``parent_state`` — fetch a comparch's state given a subcomparch /
  impl scope (parent_id traversal).
- ``sibling_states`` — same-tier scopes other than self.
- ``approved_sibling_pubapis`` — extract pubapi sections from sibling
  comparch / subcomparch bodies. Returns the layered-fallback content
  (rich if available, skeletal seed otherwise).
- ``project_sysarch_sections`` — the 4-key project-wide sysarch sections
  (project_techspec / project_policies / project_dependencies /
  project_domain_parents) every comparch+ tier consumes.
- ``feature_nodes`` / ``responsibility_nodes`` — the node records the
  ``feature_expansion`` / ``requirements`` manifests declare. The
  single-node arch tiers each write one substrate file + one manifest;
  these helpers hand back the manifest's node list.
- ``related_features_summary`` — features reachable from a comp's owned
  responsibilities. The walk is ``parent_resps → resp node.feats →
  feat node``: ``meta.parent_resps`` (resp_* IDs) resolves through the
  requirements manifest to feat_* IDs, which resolve through the
  feature_expansion manifest to names + intents.

The helpers return plain Python dicts / lists; the caller per-tier
shapes them into the prompt's expected keys.
"""

from __future__ import annotations

from typing import Any

from siege.fragments import (
    COMPARCH_LAYER_FALLBACK,
    SUBCOMPARCH_LAYER_FALLBACK,
    FragmentKind,
    parse_body_sections,
    section_for_kind,
)
from siege.git_view import GitView
from siege.prompts import load_generation_prompt, load_review_prompt
from siege.state import Scope, State, Tier


def get_body_text(view: GitView, state: State) -> str:
    """Return the body text for a state, or empty string if no draft yet."""
    if not state.draft:
        return ""
    try:
        return view.read_body_text(state.draft.body_path)
    except Exception:
        return ""


def section_or_empty(body: str, section_name: str) -> str:
    """Pull one section from a parsed body, or empty string."""
    return parse_body_sections(body).get(section_name, "")


def layered_section(
    view: GitView,
    state: State,
    kind: FragmentKind,
    is_top_level: bool,
) -> str:
    """Return the highest-layer non-empty section for a kind.

    Mirrors ``best_layered_fragment_content`` from the old fragments
    module: for a top-level comp, prefer the comparch-layer section
    (e.g. ``comparch:techspec``); fall back to the sysarch seed
    section (``techspec``). For a subcomp, prefer the subcomparch
    layer; fall back to the seed.
    """
    body = get_body_text(view, state)
    sections = parse_body_sections(body)
    if is_top_level:
        layer_kind = {v: k for k, v in COMPARCH_LAYER_FALLBACK.items()}.get(kind, kind)
    else:
        layer_kind = {v: k for k, v in SUBCOMPARCH_LAYER_FALLBACK.items()}.get(kind, kind)
    primary = sections.get(section_for_kind(layer_kind))
    if primary and primary.strip():
        return primary
    fallback = sections.get(section_for_kind(kind))
    return fallback or ""


def parent_state(view: GitView, scope: Scope) -> State | None:
    """For a sub-tier scope, fetch the parent comparch state."""
    if not scope.parent_id:
        return None
    return view.get_state(Scope(tier="comparch", comp_id=scope.parent_id))


def sibling_states(view: GitView, scope: Scope) -> list[State]:
    """Same-tier scopes other than self."""
    self_key = scope.key()
    return [s for s in view.list_tier(scope.tier) if s.scope.key() != self_key]


def project_sysarch_sections(view: GitView) -> dict[str, str]:
    """Extract the 4 project-wide sysarch sections.

    Mirrors ``_load_project_sysarch_sections`` in the old
    ``regen_context.py``. The sections live in the sysarch tier's
    body files (one section per top-level concern). The writing
    skill for sysarch is responsible for emitting them with the
    canonical section names below.
    """
    keys = (
        "project_techspec",
        "project_policies",
        "project_dependencies",
        "project_domain_parents",
    )
    out: dict[str, str] = {k: "" for k in keys}
    for state in view.list_tier("sysarch"):
        body = get_body_text(view, state)
        if not body:
            continue
        sections = parse_body_sections(body)
        for k in keys:
            if not out[k] and sections.get(k):
                out[k] = sections[k]
    return out


def feature_nodes(view: GitView) -> list[dict[str, Any]]:
    """Every feature node the project declares.

    Read from the ``feature_expansion`` manifest. Empty list before
    feature_expansion has drafted, or if its manifest is missing.
    """
    manifest = view.manifest_for_tier("feature_expansion")
    return list(manifest.nodes) if manifest else []


def responsibility_nodes(view: GitView) -> list[dict[str, Any]]:
    """Every responsibility node the project declares.

    Read from the ``requirements`` manifest. Empty list before
    requirements has drafted, or if its manifest is missing.
    """
    manifest = view.manifest_for_tier("requirements")
    return list(manifest.nodes) if manifest else []


def related_features_summary(view: GitView, scope_state: State) -> str:
    """Build the related-features summary for a comp / sub / impl.

    Walks the scope's ``meta.parent_resps`` (resp_* IDs) → the
    requirements manifest (each responsibility node carries the
    ``feats`` it derives from) → the feature_expansion manifest (each
    feature node carries ``name`` + ``intent``).

    Result is a markdown bullet list scoped to exactly the features the
    scope's responsibilities reach — never the whole feature set, never
    a raw body file. Empty string when nothing is reachable.
    """
    parent_resps: list[str] = scope_state.meta.get("parent_resps", [])
    if not parent_resps:
        return ""

    feat_ids: list[str] = []
    for resp_id in parent_resps:
        resp_node = view.get_node(resp_id)
        if not resp_node:
            continue
        for feat_id in resp_node.get("feats", []):
            if feat_id not in feat_ids:
                feat_ids.append(feat_id)

    lines: list[str] = []
    for feat_id in feat_ids:
        feat_node = view.get_node(feat_id)
        if not feat_node:
            continue
        name = feat_node.get("name", feat_id)
        intent = feat_node.get("intent", "")
        lines.append(f"- **{name}** ({feat_id}): {intent}")
    return "\n".join(lines)


def sibling_pubapi_fragments(
    view: GitView,
    self_state: State,
    tier_filter: Tier = "comparch",
) -> dict[str, str]:
    """Return {sibling_comp_id: pubapi content} for self's declared deps.

    Reads ``self_state.edges['dependencies']`` (list of comp ids the
    writer declared) and extracts each sibling's best-layered pubapi.
    """
    dep_ids: list[str] = self_state.edges.get("dependencies", [])
    out: dict[str, str] = {}
    for cid in dep_ids:
        sib = view.get_state(Scope(tier=tier_filter, comp_id=cid))
        if sib is None:
            out[cid] = ""
            continue
        # For comparch tier deps, the layered pubapi sits in the comparch body.
        out[cid] = layered_section(view, sib, FragmentKind.PUBAPI, is_top_level=True)
    return out


def parent_fragments(view: GitView, scope: Scope) -> dict[str, str]:
    """For sub-tier scopes, extract the parent comparch's non-sub fragments.

    Mirrors the parent_* keys ``regen_context.py`` carries into
    subcomparch + impl: ``parent_techspec``, ``parent_pubapi``,
    ``parent_privapi``, ``parent_policies``, ``parent_failure_surface``.
    """
    parent = parent_state(view, scope)
    if parent is None:
        return {}
    body = get_body_text(view, parent)
    if not body:
        return {}
    sections = parse_body_sections(body)
    return {
        "parent_techspec": sections.get(section_for_kind(FragmentKind.COMPARCH_TECHSPEC), ""),
        "parent_pubapi": sections.get(section_for_kind(FragmentKind.COMPARCH_PUBAPI), ""),
        "parent_privapi": sections.get(section_for_kind(FragmentKind.COMPARCH_PRIVAPI), ""),
        "parent_policies": sections.get(section_for_kind(FragmentKind.COMPARCH_POLICIES), ""),
        "parent_failure_surface": sections.get(
            section_for_kind(FragmentKind.COMPARCH_FAILURE_SURFACE), ""
        ),
    }


def component_non_surface_fragments(view: GitView, scope: Scope) -> dict[str, str]:
    """For a top-level impl's owner, the comp's own policies + failure surface.

    Only populated when the impl's owner is itself top-level (foundation
    impl); empty for sub impls.
    """
    if not scope.comp_id:
        return {}
    state = view.get_state(Scope(tier="comparch", comp_id=scope.comp_id))
    if state is None:
        return {}
    body = get_body_text(view, state)
    sections = parse_body_sections(body)
    return {
        "component_policies": sections.get(section_for_kind(FragmentKind.COMPARCH_POLICIES), ""),
        "component_failure_surface": sections.get(
            section_for_kind(FragmentKind.COMPARCH_FAILURE_SURFACE), ""
        ),
    }


def ref_metadata(view: GitView) -> dict[str, Any]:
    """Common ref metadata threaded into every context bundle."""
    return {"ref": view.ref, "ref_head_sha": view.head_sha}


def generation_prompt(tier: Tier) -> str:
    """The static generator instruction text for a tier."""
    return load_generation_prompt(tier)


def review_prompt(tier: Tier) -> str:
    """The static reviewer instruction text for a tier."""
    return load_review_prompt(tier)


def require_draft(state: State | None, scope: Scope, draft_sha: str) -> None:
    """Validate that a scope has a draft matching the expected sha.

    Used by every tier's ``build_review_context`` — pulls the common
    "drafted state must exist + sha must match" check out so the per-tier
    modules stay small.
    """
    if not state or not state.draft:
        raise ValueError(f"No drafted state for {scope.key()} — cannot build review context")
    if state.draft.body_sha256 != draft_sha:
        raise ValueError(
            f"Draft sha drift: state says {state.draft.body_sha256!r}, caller passed {draft_sha!r}"
        )


def fail_missing(view: GitView, scope: Scope) -> dict[str, Any]:
    """Return a context bundle for a scope that doesn't exist yet.

    Skills draft into an absent state — this bundle has no `state`
    block, no `draft`, no `review`. It's the "fresh slate" shape that
    every draft-* skill expects on first run.
    """
    return {
        **ref_metadata(view),
        "scope": {
            "tier": scope.tier,
            "comp_id": scope.comp_id,
            "parent_id": scope.parent_id,
            "sub_id": scope.sub_id,
        },
        "status": "absent",
        "prior_review_text": "",
    }
