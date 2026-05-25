"""Read-projection functions for the dashboard HTTP API.

Each function answers one read — state, a context bundle, a summary —
sharing a common shape:

    def read_xxx(project_id: str, ref: str, ...) -> dict

``server.py`` wraps each behind an ``/api/*`` route. (The skills do
*not* call these — they run the equivalent ``siege.cli`` subcommands
locally; migration step 5 retired the MCP transport that once exposed
this surface to them.)

Every function takes ``project_id`` + ``ref`` first. The view cache in
``git_view.cache`` handles the fetch + sha resolution; these just ask
for a view and read from it.
"""

from __future__ import annotations

from typing import Any

from siege.auth_context import current_user_id
from siege.auth_lookup import lookup_project_auth
from siege.git_view import GitView
from siege.git_view import cache as view_cache
from siege.projection import GENERATION_BUILDERS, REVIEW_BUILDERS
from siege.projection.graph import build_project_graph as _build_project_graph
from siege.projection.plan import compute_plan as _compute_plan
from siege.projection.review_summary import build_review_summary
from siege.projection.structure import build_structure_summary
from siege.state import Scope, Tier, dump_state
from siege.validate import validate_artifact as _validate


def _open_view(project_id: str, ref: str, remote_url: str | None = None) -> GitView:
    """Open a GitView with auth resolved from the current request context.

    Looks up the project's stored remote_url (caller can override via
    the `remote_url` arg, useful for list_refs's optional override) and
    the current user's GitHub OAuth token. Both are passed through to
    the view cache; missing values degrade to "no auth" (public repos
    keep working, private repos surface a clear error).
    """
    user_id = current_user_id()
    db_auth = lookup_project_auth(project_id, user_id)
    return view_cache.get_view(
        project_id,
        ref,
        remote_url=remote_url or db_auth.remote_url,
        access_token=db_auth.access_token,
    )


def list_refs(project_id: str, remote_url: str | None = None) -> dict[str, Any]:
    user_id = current_user_id()
    db_auth = lookup_project_auth(project_id, user_id)
    refs = view_cache.list_refs(
        project_id,
        remote_url=remote_url or db_auth.remote_url,
        access_token=db_auth.access_token,
    )
    return {
        "refs": [
            {"name": r.name, "head_sha": r.head_sha, "head_subject": r.head_subject} for r in refs
        ]
    }


def get_state(
    project_id: str,
    ref: str,
    tier: Tier,
    comp_id: str | None = None,
    parent_id: str | None = None,
    sub_id: str | None = None,
    phase: int | None = None,
) -> dict[str, Any]:
    view = _open_view(project_id, ref)
    scope = Scope(tier=tier, comp_id=comp_id, parent_id=parent_id, sub_id=sub_id, phase=phase)
    state = view.get_state(scope)
    if state is None:
        return {
            "ref": view.ref,
            "ref_head_sha": view.head_sha,
            "scope": dict(
                tier=tier, comp_id=comp_id, parent_id=parent_id, sub_id=sub_id, phase=phase
            ),
            "found": False,
        }
    drift = view.drift_for(state)
    payload: dict[str, Any] = {
        "ref": view.ref,
        "ref_head_sha": view.head_sha,
        "found": True,
        **dump_state(state),
    }
    if drift:
        payload["drift"] = drift
    return payload


def get_body(
    project_id: str,
    ref: str,
    tier: Tier,
    comp_id: str | None = None,
    parent_id: str | None = None,
    sub_id: str | None = None,
    phase: int | None = None,
) -> dict[str, Any]:
    """Read-only body fetcher: resolves the scope's state, reads the
    body file off the substrate, returns ``{ref, ref_head_sha,
    body_path, body_text, found}``.

    The dashboard's source-aware read panels (``V3BodyPanel``) call
    this when ``project.source == "upload"`` so the workspace shows
    the substrate's actual artifact instead of falling back to the
    legacy SQL endpoints (which don't have rows for upload projects).

    ``found`` is ``False`` when the scope has no state, no draft, or
    the body file is unreadable — callers render an explanatory blank
    instead of an error.
    """
    view = _open_view(project_id, ref)
    scope = Scope(tier=tier, comp_id=comp_id, parent_id=parent_id, sub_id=sub_id, phase=phase)
    state = view.get_state(scope)
    if state is None or state.draft is None:
        return {
            "ref": view.ref,
            "ref_head_sha": view.head_sha,
            "found": False,
            "body_path": None,
            "body_text": "",
        }
    body_path = state.draft.body_path
    try:
        body_text = view.read_body_text(body_path)
    except Exception:  # noqa: BLE001 — body missing on disk → found False
        return {
            "ref": view.ref,
            "ref_head_sha": view.head_sha,
            "found": False,
            "body_path": body_path,
            "body_text": "",
        }
    return {
        "ref": view.ref,
        "ref_head_sha": view.head_sha,
        "found": True,
        "body_path": body_path,
        "body_text": body_text,
    }


def list_tier(
    project_id: str,
    ref: str,
    tier: Tier,
    status: str | None = None,
    min_score: int | None = None,
    max_score: int | None = None,
    is_foundation: bool | None = None,
    approved: bool | None = None,
    has_review: bool | None = None,
) -> dict[str, Any]:
    view = _open_view(project_id, ref)
    states = view.list_tier(tier)

    def _keep(s) -> bool:  # type: ignore[no-untyped-def]
        if status is not None and s.status != status:
            return False
        if approved is True and s.status != "approved":
            return False
        if approved is False and s.status == "approved":
            return False
        if is_foundation is not None and s.is_foundation != is_foundation:
            return False
        if has_review is True and not s.review:
            return False
        if has_review is False and s.review:
            return False
        score = s.review.score if s.review else None
        if min_score is not None and (score is None or score < min_score):
            return False
        if max_score is not None and (score is None or score > max_score):
            return False
        return True

    filtered = [s for s in states if _keep(s)]
    return {
        "ref": view.ref,
        "ref_head_sha": view.head_sha,
        "tier": tier,
        "scopes": [dump_state(s) for s in filtered],
    }


def get_generation_context(
    project_id: str,
    ref: str,
    tier: Tier,
    comp_id: str | None = None,
    parent_id: str | None = None,
    sub_id: str | None = None,
    phase: int | None = None,
) -> dict[str, Any]:
    view = _open_view(project_id, ref)
    scope = Scope(tier=tier, comp_id=comp_id, parent_id=parent_id, sub_id=sub_id, phase=phase)
    builder = GENERATION_BUILDERS.get(tier)
    if builder is None:
        raise ValueError(f"No generation builder for tier {tier!r}")
    return builder(view, scope)


def get_review_context(
    project_id: str,
    ref: str,
    tier: Tier,
    draft_sha: str,
    comp_id: str | None = None,
    parent_id: str | None = None,
    sub_id: str | None = None,
    phase: int | None = None,
) -> dict[str, Any]:
    view = _open_view(project_id, ref)
    scope = Scope(tier=tier, comp_id=comp_id, parent_id=parent_id, sub_id=sub_id, phase=phase)
    builder = REVIEW_BUILDERS.get(tier)
    if builder is None:
        raise ValueError(f"No review builder for tier {tier!r}")
    return builder(view, scope, draft_sha)


def get_review_summary(project_id: str, ref: str, tier: Tier) -> dict[str, Any]:
    view = _open_view(project_id, ref)
    return build_review_summary(view, tier)


def get_structure_summary(project_id: str, ref: str, tier: Tier) -> dict[str, Any]:
    view = _open_view(project_id, ref)
    return build_structure_summary(view, tier)


def compute_plan(project_id: str, ref: str) -> dict[str, Any]:
    """Compute the phasing plan — impl nodes per phase + build order.

    Pure read-only projection (mirrors get_review_summary). Reads the
    phase registry + comparch/subcomparch/requirements tiers; never
    writes. The mint-plan skill consumes this to materialize
    state/plan.json + the per-node impl state files.
    """
    view = _open_view(project_id, ref)
    return _compute_plan(view)


def get_project_graph(project_id: str, ref: str) -> dict[str, Any]:
    """The whole-project node + edge graph — the dashboard graph viz feed.

    Pure read-only projection: walks the identity ledgers + bodies and
    emits a cross-tier ``{nodes, edges}`` graph. Never writes.
    """
    view = _open_view(project_id, ref)
    return _build_project_graph(view)


def list_batches(project_id: str, ref: str, status: str | None = None) -> dict[str, Any]:
    """List batch state files, optionally filtered by status."""
    view = _open_view(project_id, ref)
    batches: list[dict[str, Any]] = []
    # Batches live at state/batches/<id>.json — load them via direct tree read
    # since they're not tier-shaped.
    for path in view.clone.ls_tree(view.head_sha, "state/batches/"):
        if not path.endswith(".json"):
            continue
        try:
            raw = view.clone.show_blob(view.head_sha, path).decode("utf-8")
            import json

            data = json.loads(raw)
        except Exception:  # noqa: BLE001
            continue
        if status and data.get("status") != status:
            continue
        batches.append(data)
    return {
        "ref": view.ref,
        "ref_head_sha": view.head_sha,
        "batches": batches,
    }


def list_propagations(project_id: str, ref: str, status: str | None = None) -> dict[str, Any]:
    """List propagation records, optionally filtered by rolled-up status.

    The dashboard renders this on the ``/status`` flow so the user can
    see open iteration loops without grepping the repo. Same direct-
    tree-read pattern as ``list_batches`` — propagations live at
    ``state/propagations/<id>.json``.
    """
    import json as _json

    from siege.propagation import dump_propagation, load_propagation

    view = _open_view(project_id, ref)
    out: list[dict[str, Any]] = []
    for path in view.clone.ls_tree(view.head_sha, "state/propagations/"):
        if not path.endswith(".json"):
            continue
        try:
            data = _json.loads(view.clone.show_blob(view.head_sha, path).decode("utf-8"))
            prop = load_propagation(data)
        except Exception:  # noqa: BLE001 — skip malformed
            continue
        if status and prop.status != status:
            continue
        out.append(dump_propagation(prop))
    return {
        "ref": view.ref,
        "ref_head_sha": view.head_sha,
        "propagations": out,
    }


def validate_artifact(
    project_id: str,
    ref: str,
    tier: Tier,
    body: str,
) -> dict[str, Any]:
    """Validation gate. Doesn't need a view — pure-text check."""
    return _validate(tier=tier, body=body)
