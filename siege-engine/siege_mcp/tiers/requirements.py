"""Requirements context reader.

Requirements rotates the feature axis (user-facing) onto a system axis
(responsibilities + constraints). Per-requirement, the generator needs:

- The expanded feature it derives from (one feature_expansion body)
- Sibling requirements on the same feature (for cross-resp consistency)
- Approved feature-set summary (for global naming + scope discipline)

State JSON ``meta`` for this tier:
- ``feature_id``: which feature this requirement belongs to
- ``name``: short label (downstream sysarch transcludes)
- ``role``: responsibility role (downstream sysarch reads this)

State JSON ``edges``: ``feature: [feat_id]`` (single-element list for
parser uniformity).
"""

from __future__ import annotations

from typing import Any

from siege_mcp.git_view import GitView
from siege_mcp.state import Scope
from siege_mcp.tiers import _base


def build_generation_context(view: GitView, scope: Scope) -> dict[str, Any]:
    self_state = view.get_state(scope)
    feat_id = (self_state.meta.get("feature_id") if self_state else None) or scope.parent_id
    feature_body = ""
    feature_meta: dict[str, Any] = {}
    if feat_id:
        feat_state = view.get_state(Scope(tier="feature_expansion", comp_id=feat_id))
        if feat_state:
            feature_body = _base.get_body_text(view, feat_state)
            feature_meta = {
                "name": feat_state.meta.get("name", ""),
                "summary": feat_state.meta.get("summary", ""),
                "feature_id": feat_id,
            }
    siblings = [
        s
        for s in view.list_tier("requirements")
        if s.meta.get("feature_id") == feat_id and s.scope.comp_id != scope.comp_id
    ]
    return {
        **_base.ref_metadata(view),
        "scope": {
            "tier": "requirements",
            "comp_id": scope.comp_id,
            "parent_id": scope.parent_id,
            "sub_id": None,
        },
        "status": self_state.status if self_state else "absent",
        "feature": {"meta": feature_meta, "body": feature_body},
        "sibling_requirements_on_feature": [
            {
                "req_id": s.scope.comp_id,
                "name": s.meta.get("name", ""),
                "role": s.meta.get("role", ""),
            }
            for s in siblings
            if s.status in ("approved", "reviewed", "drafted")
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
