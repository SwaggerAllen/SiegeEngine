"""Fan-in context reader.

Fan-in is bottom-up synthesis grounded in built reality: sub pubapis +
raw impl content. Notably **excludes** project sysarch sections and
related-features — fan-in is reality, not intent.

State JSON ``meta``:
- ``owner_comp_id``: which comp this fan-in synthesizes
- ``name`` / ``role``: from the owner comp's sysarch entry

State JSON ``edges``: ``impls_consumed`` — record of which impl scopes
this fan-in pass aggregated.
"""

from __future__ import annotations

from typing import Any

from siege_mcp.fragments import FragmentKind
from siege_mcp.git_view import GitView
from siege_mcp.state import Scope
from siege_mcp.tiers import _base


def _impl_bodies_for_comp(view: GitView, comp_id: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for s in view.list_tier("impl"):
        if s.scope.parent_id != comp_id:
            continue
        body = _base.get_body_text(view, s)
        out.append(
            {
                "sub_id": s.scope.sub_id,
                "name": s.meta.get("name", ""),
                "body": body,
            }
        )
    return out


def _sub_pubapis_for_comp(view: GitView, comp_id: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for s in view.list_tier("subcomparch"):
        if s.scope.parent_id != comp_id:
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
    comp_id = (self_state.meta.get("owner_comp_id") if self_state else None) or scope.comp_id
    comparch_state = view.get_state(Scope(tier="comparch", comp_id=comp_id)) if comp_id else None
    bundle: dict[str, Any] = {
        **_base.ref_metadata(view),
        "instructions": _base.generation_prompt("fanin"),
        "scope": {
            "tier": "fanin",
            "comp_id": scope.comp_id,
            "parent_id": None,
            "sub_id": None,
        },
        "status": self_state.status if self_state else "absent",
        "owner_comp_id": comp_id,
        "owner_name": (comparch_state.meta.get("name", "") if comparch_state else ""),
        "owner_role": (comparch_state.meta.get("role", "") if comparch_state else ""),
        "sub_pubapis": _sub_pubapis_for_comp(view, comp_id or ""),
        "impl_bodies": _impl_bodies_for_comp(view, comp_id or ""),
        "prior_review_text": (
            self_state.draft.prior_review_text if self_state and self_state.draft else ""
        ),
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
        "review_instructions": _base.review_prompt("fanin"),
        "draft_body": body,
        "draft_sha": draft_sha,
    }
