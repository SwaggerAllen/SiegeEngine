"""Subcomparch context reader.

Subcomparch is the leaf articulation tier. Per-sub, it consumes the
parent comparch's non-sub fragments (techspec / pubapi / privapi /
policies / failure_surface), same-parent sibling sub pubapis (with
sysarch-seed fallback), and the project-wide sysarch sections.

State JSON ``meta`` for this tier:
- ``name``: sub display name (from comparch_mint)
- ``role``: terse role
- ``parent_resps``: subset of the parent comp's parent_resps this sub
  carries (the comparch's ``<owns>`` block determines this)

State JSON ``edges``:
- ``dependencies``: list of {comp_id, sub_id} this sub depends on
  (mostly same-parent siblings; cross-comp deps are rare)
"""

from __future__ import annotations

from typing import Any

from siege.fragments import FragmentKind
from siege.git_view import GitView
from siege.state import Scope
from siege.tiers import _base


def _sibling_subs(view: GitView, scope: Scope) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for s in view.list_tier("subcomparch"):
        if s.scope.parent_id != scope.parent_id:
            continue
        if s.scope.sub_id == scope.sub_id:
            continue
        body = _base.get_body_text(view, s)
        pubapi = _base.layered_section(view, s, FragmentKind.PUBAPI, is_top_level=False)
        out.append(
            {
                "sub_id": s.scope.sub_id,
                "name": s.meta.get("name", ""),
                "role": s.meta.get("role", ""),
                "pubapi": pubapi,
                "has_body": bool(body),
            }
        )
    return out


def build_generation_context(view: GitView, scope: Scope) -> dict[str, Any]:
    self_state = view.get_state(scope)

    bundle: dict[str, Any] = {
        **_base.ref_metadata(view),
        "instructions": _base.generation_prompt("subcomparch"),
        "scope": {
            "tier": "subcomparch",
            "comp_id": None,
            "parent_id": scope.parent_id,
            "sub_id": scope.sub_id,
        },
        "status": self_state.status if self_state else "absent",
        **_base.parent_fragments(view, scope),
        "sibling_subs": _sibling_subs(view, scope),
        "related_features_summary": (
            _base.related_features_summary(view, self_state) if self_state else ""
        ),
        "prior_review_text": (
            self_state.draft.prior_review_text if self_state and self_state.draft else ""
        ),
        **_base.project_sysarch_sections(view),
    }
    if self_state:
        bundle["parent_resps"] = self_state.meta.get("parent_resps", [])
        bundle["self_techspec_seed"] = _base.layered_section(
            view, self_state, FragmentKind.TECHSPEC, is_top_level=False
        )
        bundle["self_pubapi_seed"] = _base.layered_section(
            view, self_state, FragmentKind.PUBAPI, is_top_level=False
        )
    return bundle


def build_review_context(view: GitView, scope: Scope, draft_sha: str) -> dict[str, Any]:
    self_state = view.get_state(scope)
    _base.require_draft(self_state, scope, draft_sha)
    assert self_state is not None
    body = _base.get_body_text(view, self_state)
    gen_ctx = build_generation_context(view, scope)
    return {
        **gen_ctx,
        "review_instructions": _base.review_prompt("subcomparch"),
        "draft_body": body,
        "draft_sha": draft_sha,
    }
