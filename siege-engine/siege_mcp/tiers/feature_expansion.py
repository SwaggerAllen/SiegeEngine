"""Feature expansion context reader.

Feature expansion is the most upstream tier — it extracts feature
artifacts from the project's input document. Generation context is
small: the input doc + sibling features (for cross-feature consistency)
+ any prior review.

State JSON ``meta`` for this tier:
- ``name``: short display name
- ``summary``: one-sentence pitch (downstream tiers transclude this)
- ``feature_id``: same as comp_id; explicit for clarity

State JSON ``edges`` for this tier: none (root of the chain).
"""

from __future__ import annotations

from typing import Any

from siege_mcp.git_view import GitView
from siege_mcp.state import Scope
from siege_mcp.tiers import _base


def build_generation_context(view: GitView, scope: Scope) -> dict[str, Any]:
    self_state = view.get_state(scope)
    sibling = _base.sibling_states(view, scope)
    sibling_summaries = [
        {
            "feature_id": s.scope.comp_id,
            "name": s.meta.get("name", ""),
            "summary": s.meta.get("summary", ""),
        }
        for s in sibling
        if s.status in ("approved", "reviewed", "drafted")
    ]
    bundle = {
        **_base.ref_metadata(view),
        "scope": {
            "tier": "feature_expansion",
            "comp_id": scope.comp_id,
            "parent_id": None,
            "sub_id": None,
        },
        "status": self_state.status if self_state else "absent",
        "sibling_features": sibling_summaries,
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
    sibling = _base.sibling_states(view, scope)
    return {
        **_base.ref_metadata(view),
        "scope": {
            "tier": "feature_expansion",
            "comp_id": scope.comp_id,
            "parent_id": None,
            "sub_id": None,
        },
        "draft_body": body,
        "draft_sha": draft_sha,
        "sibling_features": [
            {
                "feature_id": s.scope.comp_id,
                "name": s.meta.get("name", ""),
                "summary": s.meta.get("summary", ""),
            }
            for s in sibling
            if s.status in ("approved", "reviewed", "drafted")
        ],
    }
