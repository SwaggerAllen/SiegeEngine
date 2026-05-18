"""Impl context reader.

Impl articulates a leaf subcomparch into implementation-level detail.
Bundle = parent comparch fragments + project sysarch sections + sibling
sub pubapis + this scope's subcomparch body.

State JSON ``meta``:
- ``name`` / ``role``: from subcomparch_mint
- ``parent_resps``: from comparch's <owns> block

State JSON ``edges``:
- ``dependencies``: same shape as subcomparch
"""

from __future__ import annotations

from typing import Any

from siege_mcp.fragments import FragmentKind
from siege_mcp.git_view import GitView
from siege_mcp.state import Scope
from siege_mcp.tiers import _base


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


def build_generation_context(view: GitView, scope: Scope) -> dict[str, Any]:
    self_state = view.get_state(scope)
    subcomparch_scope = Scope(tier="subcomparch", parent_id=scope.parent_id, sub_id=scope.sub_id)
    sub_state = view.get_state(subcomparch_scope)
    sub_body = _base.get_body_text(view, sub_state) if sub_state else ""

    bundle: dict[str, Any] = {
        **_base.ref_metadata(view),
        "scope": {
            "tier": "impl",
            "comp_id": None,
            "parent_id": scope.parent_id,
            "sub_id": scope.sub_id,
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
        "draft_body": body,
        "draft_sha": draft_sha,
    }
