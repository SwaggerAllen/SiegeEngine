"""Comparch context reader.

Comparch is the largest single bundle and the heaviest port. It carries
project-wide sysarch sections + related features + sibling pubapis +
this comp's parent_resps + already-applied policies.

State JSON ``meta`` for this tier:
- ``name``: comp display name
- ``role``: terse role description from sysarch_mint
- ``kind``: "service" | "library" | "interface" | "presentational" etc.
- ``parent_resps``: list of resp_* the comp owns (from sysarch
  decomposition)
- ``is_foundation``: foundation-comp flag (kept in state JSON, not path)

State JSON ``edges``:
- ``dependencies``: list of sibling comp_* this comp depends on
- ``domain_parents``: for presentational comps, the targets whose
  fan-in this comp consumes
- ``policy_applications``: list of policy_* applied to this comp

The bundle keys match the old ``regen_context.py`` output so the
ported prompts work unchanged.
"""

from __future__ import annotations

from typing import Any

from siege_mcp.fragments import FragmentKind
from siege_mcp.git_view import GitView
from siege_mcp.state import Scope
from siege_mcp.tiers import _base


def _self_fragments(view: GitView, self_state) -> dict[str, str]:  # type: ignore[no-untyped-def]
    body = _base.get_body_text(view, self_state)
    if not body:
        return {"component_techspec": "", "component_pubapi": ""}
    return {
        "component_techspec": _base.layered_section(
            view, self_state, FragmentKind.TECHSPEC, is_top_level=True
        ),
        "component_pubapi": _base.layered_section(
            view, self_state, FragmentKind.PUBAPI, is_top_level=True
        ),
    }


def _sibling_comps(view: GitView, scope: Scope) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for s in view.list_tier("comparch"):
        if s.scope.comp_id == scope.comp_id:
            continue
        out.append(
            {
                "comp_id": s.scope.comp_id,
                "name": s.meta.get("name", ""),
                "role": s.meta.get("role", ""),
                "kind": s.meta.get("kind", ""),
            }
        )
    return out


def build_generation_context(view: GitView, scope: Scope) -> dict[str, Any]:
    self_state = view.get_state(scope)
    if self_state is None:
        return _base.fail_missing(view, scope)

    bundle: dict[str, Any] = {
        **_base.ref_metadata(view),
        "scope": {
            "tier": "comparch",
            "comp_id": scope.comp_id,
            "parent_id": None,
            "sub_id": None,
        },
        "status": self_state.status,
        "is_foundation": self_state.is_foundation,
        **_self_fragments(view, self_state),
        "parent_resps": self_state.meta.get("parent_resps", []),
        "related_features_summary": _base.related_features_summary(view, self_state),
        "sibling_comps": _sibling_comps(view, scope),
        "sibling_comp_ids": [s["comp_id"] for s in _sibling_comps(view, scope) if s["comp_id"]],
        "dep_pubapi_fragments": _base.sibling_pubapi_fragments(view, self_state),
        "already_applied_policies": self_state.edges.get("policy_applications", []),
        "prior_review_text": (self_state.draft.prior_review_text if self_state.draft else ""),
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
