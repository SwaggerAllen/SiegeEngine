"""Requirements context reader.

Requirements rotates the feature axis (user-facing) onto a system axis
(responsibilities). It is a single-node tier: one ``requirements``
substrate file per project, whose body declares every responsibility.

The generator needs the full approved feature set — each feature with
its stable ``feat_*`` ID — so it can rotate features into
responsibilities and tag each ``<responsibility>`` with the ``<feat>``
IDs it derives from. Those features come from the ``feature_expansion``
node index (the rehydrated identity ledger), not the raw
feature_expansion body: the generator reads feature *records*, never a
whole XML body file.

On commit the draft skill derives this tier's own identity ledger at
``ids/requirements/<id>.json`` — the ``id``↔``name`` binding per
``resp_*`` node. Sysarch and ``related_features_summary`` read the
rehydrated node index (which re-derives the ``feats`` edges from the
body) downstream.
"""

from __future__ import annotations

from typing import Any

from siege.git_view import GitView
from siege.projection import _base
from siege.state import Scope


def build_generation_context(view: GitView, scope: Scope) -> dict[str, Any]:
    self_state = view.get_state(scope)
    features = [
        {
            "id": n.get("id", ""),
            "name": n.get("name", ""),
            "intent": n.get("intent", ""),
            "implicit": n.get("implicit", False),
        }
        for n in _base.feature_nodes(view)
    ]
    return {
        **_base.ref_metadata(view),
        "instructions": _base.generation_prompt("requirements"),
        "scope": {
            "tier": "requirements",
            "comp_id": scope.comp_id,
            "parent_id": None,
            "sub_id": None,
        },
        "status": self_state.status if self_state else "absent",
        "features": features,
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
        "review_instructions": _base.review_prompt("requirements"),
        "draft_body": body,
        "draft_sha": draft_sha,
    }
