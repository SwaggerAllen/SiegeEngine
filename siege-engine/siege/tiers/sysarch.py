"""Sysarch context reader.

Sysarch compresses approved responsibilities into top-level components.
It is a single-node tier: one ``sysarch`` substrate file per project,
whose body holds the five project-level sections (techspec, components,
policies, dependencies, domain-parent).

The generator reads two node lists, both from upstream manifests:

- ``approved_features`` — every feature node (``feat_*`` ID + name +
  intent), from the ``feature_expansion`` manifest.
- ``approved_requirements`` — every responsibility node (``resp_*`` ID
  + name + the ``feats`` it owns), from the ``requirements`` manifest.

It reads node records, never raw upstream body files.
"""

from __future__ import annotations

from typing import Any

from siege.git_view import GitView
from siege.state import Scope
from siege.tiers import _base


def _approved_features(view: GitView) -> list[dict[str, Any]]:
    return [
        {
            "id": n.get("id", ""),
            "name": n.get("name", ""),
            "intent": n.get("intent", ""),
            "implicit": n.get("implicit", False),
        }
        for n in _base.feature_nodes(view)
    ]


def _approved_responsibilities(view: GitView) -> list[dict[str, Any]]:
    return [
        {
            "id": n.get("id", ""),
            "name": n.get("name", ""),
            "feats": list(n.get("feats", [])),
        }
        for n in _base.responsibility_nodes(view)
    ]


def build_generation_context(view: GitView, scope: Scope) -> dict[str, Any]:
    self_state = view.get_state(scope)
    return {
        **_base.ref_metadata(view),
        "instructions": _base.generation_prompt("sysarch"),
        "scope": {
            "tier": "sysarch",
            "comp_id": scope.comp_id,
            "parent_id": None,
            "sub_id": None,
        },
        "status": self_state.status if self_state else "absent",
        "approved_features": _approved_features(view),
        "approved_requirements": _approved_responsibilities(view),
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
        "review_instructions": _base.review_prompt("sysarch"),
        "draft_body": body,
        "draft_sha": draft_sha,
    }
