"""Sysarch context reader.

Sysarch compresses approved requirements into top-level components. The
generator reads the full approved requirements set + the approved
feature summaries and decomposes them into comp_* nodes.

State JSON ``meta`` for this tier:
- ``name``: section name (e.g. ``project_techspec`` — sysarch sections
  are the project-wide ones every comparch consumes via
  ``project_sysarch_sections``)

State JSON ``edges``: ``requirements_consumed: [req_id, ...]`` —
declarative record of which approved requirements this section
incorporates.
"""

from __future__ import annotations

from typing import Any

from siege_mcp.git_view import GitView
from siege_mcp.state import Scope
from siege_mcp.tiers import _base


def _all_approved_requirements(view: GitView) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for s in view.list_tier("requirements"):
        if s.status != "approved":
            continue
        body = _base.get_body_text(view, s)
        out.append(
            {
                "req_id": s.scope.comp_id,
                "name": s.meta.get("name", ""),
                "role": s.meta.get("role", ""),
                "feature_id": s.meta.get("feature_id", ""),
                "body": body,
            }
        )
    return out


def _all_approved_features(view: GitView) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for s in view.list_tier("feature_expansion"):
        if s.status not in ("approved", "reviewed"):
            continue
        out.append(
            {
                "feature_id": s.scope.comp_id,
                "name": s.meta.get("name", ""),
                "summary": s.meta.get("summary", ""),
            }
        )
    return out


def build_generation_context(view: GitView, scope: Scope) -> dict[str, Any]:
    self_state = view.get_state(scope)
    return {
        **_base.ref_metadata(view),
        "scope": {
            "tier": "sysarch",
            "comp_id": scope.comp_id,
            "parent_id": None,
            "sub_id": None,
        },
        "status": self_state.status if self_state else "absent",
        "section_name": (self_state.meta.get("name") if self_state else "") or scope.comp_id,
        "approved_requirements": _all_approved_requirements(view),
        "approved_features": _all_approved_features(view),
        "sibling_sections": [
            {"id": s.scope.comp_id, "name": s.meta.get("name", "")}
            for s in view.list_tier("sysarch")
            if s.scope.comp_id != scope.comp_id
        ],
        "prior_review_text": (
            self_state.draft.prior_review_text if self_state and self_state.draft else ""
        ),
    }


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
