"""Impl context reader.

Impl articulates a leaf subcomparch into implementation-level detail.
Bundle = parent comparch fragments + project sysarch sections + sibling
sub pubapis + this scope's subcomparch body.

When the scope carries a ``phase`` (impl-tier phasing), the bundle also
threads:

- ``prior_phase_impl_body`` — the same subcomponent's impl artifact
  from the previous phase. NOT the whole prior phase — exactly one
  artifact, so the context stays bounded. The phase-N impl body is
  authored delta-style ("phase N-1 covered A; this pass adds B").
- ``dep_fanin_summaries`` — the prior-phase fan-in synthesis of each
  dependency component. The compressed cross-component view; phase-N
  impl reads handles, not raw sibling impl bodies.

The phase-N *closure slice* (which responsibilities this pass
implements) arrives for free: ``mint-plan`` pre-seeds the impl state's
``meta.parent_resps`` to the cumulative closure, and
``related_features_summary`` already scopes off ``meta.parent_resps``.

State JSON ``meta``:
- ``name`` / ``role``: from subcomparch_mint
- ``parent_resps``: the phase closure (impl) or the <owns> block

State JSON ``edges``:
- ``dependencies``: same shape as subcomparch
"""

from __future__ import annotations

from typing import Any

from siege.fragments import FragmentKind
from siege.git_view import GitView
from siege.state import Scope
from siege.tiers import _base


def _sibling_sub_pubapis(view: GitView, scope: Scope) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for s in view.list_tier("subcomparch"):
        if s.scope.parent_id != scope.parent_id:
            continue
        if s.scope.sub_id == scope.sub_id:
            continue
        pubapi = _base.layered_section(view, s, FragmentKind.PUBAPI, is_top_level=False)
        out.append(
            {
                "sub_id": s.scope.sub_id,
                "name": s.meta.get("name", ""),
                "pubapi": pubapi,
            }
        )
    return out


def _prior_phase_impl_body(view: GitView, scope: Scope) -> str:
    """The same subcomponent's impl body from the nearest earlier phase.

    Robust to non-contiguous phase numbering — takes the largest impl
    phase strictly below ``scope.phase`` for this (parent_id, sub_id),
    not blindly ``phase - 1``. Empty string for the first phase.
    """
    if scope.phase is None:
        return ""
    candidates = [
        s
        for s in view.list_tier("impl")
        if s.scope.parent_id == scope.parent_id
        and s.scope.sub_id == scope.sub_id
        and s.scope.phase is not None
        and s.scope.phase < scope.phase
    ]
    if not candidates:
        return ""
    prior = max(candidates, key=lambda s: s.scope.phase or -1)
    return _base.get_body_text(view, prior)


def _dep_fanin_summaries(view: GitView, scope: Scope) -> list[dict[str, Any]]:
    """Prior-phase fan-in synthesis of each dependency component.

    The dependency components are the *parent comparch's* declared
    dependencies (comp-granular). For each, the fan-in artifact at the
    nearest fan-in phase strictly below ``scope.phase`` — the
    compressed view of what that component looked like by the time
    this phase started.
    """
    if scope.phase is None:
        return []
    parent = _base.parent_state(view, scope)
    if parent is None:
        return []
    dep_comp_ids = parent.edges.get("dependencies", [])
    if not dep_comp_ids:
        return []
    # Index fan-in states by (comp_id) → list of (phase, State).
    fanin_by_comp: dict[str, list] = {}
    for s in view.list_tier("fanin"):
        if s.scope.comp_id and s.scope.phase is not None:
            fanin_by_comp.setdefault(s.scope.comp_id, []).append(s)
    out: list[dict[str, Any]] = []
    for dep in dep_comp_ids:
        prior = [s for s in fanin_by_comp.get(dep, []) if (s.scope.phase or 0) < scope.phase]
        if not prior:
            continue
        latest = max(prior, key=lambda s: s.scope.phase or -1)
        out.append(
            {
                "comp_id": dep,
                "phase": latest.scope.phase,
                "synthesis": _base.get_body_text(view, latest),
            }
        )
    return out


def build_generation_context(view: GitView, scope: Scope) -> dict[str, Any]:
    self_state = view.get_state(scope)
    subcomparch_scope = Scope(tier="subcomparch", parent_id=scope.parent_id, sub_id=scope.sub_id)
    sub_state = view.get_state(subcomparch_scope)
    sub_body = _base.get_body_text(view, sub_state) if sub_state else ""

    bundle: dict[str, Any] = {
        **_base.ref_metadata(view),
        "instructions": _base.generation_prompt("impl"),
        "scope": {
            "tier": "impl",
            "comp_id": None,
            "parent_id": scope.parent_id,
            "sub_id": scope.sub_id,
            "phase": scope.phase,
        },
        "status": self_state.status if self_state else "absent",
        "subcomparch_body": sub_body,
        **_base.parent_fragments(view, scope),
        **_base.component_non_surface_fragments(view, scope),
        "sibling_sub_pubapis": _sibling_sub_pubapis(view, scope),
        "related_features_summary": (
            _base.related_features_summary(view, self_state)
            if self_state
            else (_base.related_features_summary(view, sub_state) if sub_state else "")
        ),
        "prior_review_text": (
            self_state.draft.prior_review_text if self_state and self_state.draft else ""
        ),
        # Phase context — empty for an unphased (legacy) impl scope.
        "prior_phase_impl_body": _prior_phase_impl_body(view, scope),
        "dep_fanin_summaries": _dep_fanin_summaries(view, scope),
        **_base.project_sysarch_sections(view),
    }
    return bundle


def build_review_context(view: GitView, scope: Scope, draft_sha: str) -> dict[str, Any]:
    self_state = view.get_state(scope)
    _base.require_draft(self_state, scope, draft_sha)
    assert self_state is not None
    body = _base.get_body_text(view, self_state)
    gen_ctx = build_generation_context(view, scope)
    return {
        **gen_ctx,
        "review_instructions": _base.review_prompt("impl"),
        "draft_body": body,
        "draft_sha": draft_sha,
    }
