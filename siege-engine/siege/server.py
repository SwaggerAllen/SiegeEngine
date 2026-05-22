"""HTTP read API for the SiegeEngine dashboard.

A thin FastAPI app over ``siege.tools`` — the read-side projection of a
project's git tree (state, context bundles, structure / review
summaries, the phasing plan). The dashboard frontend is the consumer.
Auth is a bearer-token JWT verified against the same secret the
dashboard login issues (see ``siege.auth``).

The skills no longer call this server — they run the ``siege`` CLI
locally (migration step 5 dropped the MCP transport). The server is a
read-only viewer; it never writes.

Running standalone:

    python -m siege.server

For local dev:

    SIEGE_JWT_SECRET_KEY=dev-secret uvicorn siege.server:app --reload --port 8080
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from siege import tools
from siege.auth import AuthError, verify_request_token
from siege.auth_context import user_id_context
from siege.config import settings

logger = logging.getLogger(__name__)


# ---------------- Auth dependency ----------------


def _require_token(
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """Verify the JWT and return the claims.

    The user_id is bound to the request context by the middleware
    below (`_bind_user_context_middleware`), not here — sync FastAPI
    deps run in a threadpool worker, and a ContextVar set there
    doesn't propagate to the route handler's threadpool worker
    because the two workers each copy the request task's context
    independently. Setting it in middleware (which runs on the
    request task itself) makes the binding visible everywhere
    downstream.
    """
    try:
        return verify_request_token(authorization)
    except AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


# ---------------- Request models ----------------


class ListRefsRequest(BaseModel):
    project_id: str
    remote_url: str | None = None


class ScopeRef(BaseModel):
    project_id: str
    ref: str
    tier: str
    comp_id: str | None = None
    parent_id: str | None = None
    sub_id: str | None = None
    phase: int | None = None


class GetReviewContextRequest(ScopeRef):
    draft_sha: str


class ListTierRequest(BaseModel):
    project_id: str
    ref: str
    tier: str
    status: str | None = None
    min_score: int | None = None
    max_score: int | None = None
    is_foundation: bool | None = None
    approved: bool | None = None
    has_review: bool | None = None


class TierRefRequest(BaseModel):
    project_id: str
    ref: str
    tier: str


class ProjectRefRequest(BaseModel):
    project_id: str
    ref: str


class ListBatchesRequest(BaseModel):
    project_id: str
    ref: str
    status: str | None = None


class ValidateArtifactRequest(BaseModel):
    project_id: str
    ref: str
    tier: str
    body: str


# ---------------- FastAPI app ----------------


# `redirect_slashes=False` is load-bearing: when the server sits behind
# an HTTPS terminator that doesn't forward `X-Forwarded-Proto`, the
# automatic trailing-slash redirect emits a Location header pointing at
# `http://...` (scheme downgrade). A well-behaved client drops the
# Authorization header across that downgrade and loses auth on the
# retry. Turning the auto-redirect off makes a stray trailing slash a
# hard 404 instead — the client fixes its URL or fails loudly. Both
# beat silent auth loss.
app = FastAPI(title="siege", version="0.1.0", redirect_slashes=False)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def _bind_user_context_middleware(request, call_next):
    """Decode the bearer token and bind the user id to the request context.

    This is the only place that sets ``siege.auth_context``.
    Middleware runs in the request task's context, so the ContextVar
    binding propagates to every subsequent threadpool worker the
    request spawns (the route handler, its sync dependencies, the
    tool functions called inside them) via the
    ``contextvars.copy_context()`` semantics anyio uses for
    ``run_in_threadpool``.

    Doing this in a FastAPI dependency instead would silently fail:
    sync deps run in their own threadpool worker, and a ContextVar
    set there doesn't reach the route handler's threadpool worker —
    each worker forks the request task's context independently.

    The middleware is lenient: a missing or invalid token leaves the
    binding as None; the route's auth dep is what actually rejects
    bad tokens with 401.
    """
    user_id: str | None = None
    auth = request.headers.get("Authorization")
    if auth:
        try:
            claims = verify_request_token(auth)
            sub = claims.get("sub")
            user_id = str(sub) if sub else None
        except AuthError:
            user_id = None

    with user_id_context(user_id):
        return await call_next(request)


@app.get("/api/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/debug/auth")
def debug_auth(
    project_id: str | None = None,
    _claims: dict[str, Any] = Depends(_require_token),
) -> dict[str, Any]:
    """Show what the auth lookup sees for the current request.

    Counterpart to `/api/github/status` — that one reports what the
    dashboard session sees; this one reports what the request context
    sees through the exact code path a read endpoint takes. If the
    dashboard says you're connected but this reports `has_token:
    false`, the bug is in siege.auth_lookup (or the context
    propagation), not the OAuth flow.

    Never returns the raw token — only a prefix and length, enough to
    tell "no token" from "wrong token" without leaking.
    """
    from siege.auth_context import current_user_id
    from siege.auth_lookup import lookup_project_auth

    user_id = current_user_id()
    auth = lookup_project_auth(project_id or "__missing__", user_id)
    token = auth.access_token
    return {
        "user_id_from_context": user_id,
        "user_id_in_claims": _claims.get("sub"),
        "context_matches_claims": user_id == _claims.get("sub"),
        "project_id_queried": project_id,
        "project_remote_url": auth.remote_url,
        "has_token": bool(token),
        "token_prefix": (token[:6] + "…") if token else None,
        "token_length": len(token) if token else 0,
    }


@app.post("/api/list-refs")
def http_list_refs(
    req: ListRefsRequest,
    _claims: dict[str, Any] = Depends(_require_token),
) -> dict[str, Any]:
    return tools.list_refs(req.project_id, remote_url=req.remote_url)


@app.post("/api/get-state")
def http_get_state(
    req: ScopeRef,
    _claims: dict[str, Any] = Depends(_require_token),
) -> dict[str, Any]:
    return tools.get_state(
        req.project_id,
        req.ref,
        req.tier,  # type: ignore[arg-type]
        comp_id=req.comp_id,
        parent_id=req.parent_id,
        sub_id=req.sub_id,
        phase=req.phase,
    )


@app.post("/api/list-tier")
def http_list_tier(
    req: ListTierRequest,
    _claims: dict[str, Any] = Depends(_require_token),
) -> dict[str, Any]:
    return tools.list_tier(
        req.project_id,
        req.ref,
        req.tier,  # type: ignore[arg-type]
        status=req.status,
        min_score=req.min_score,
        max_score=req.max_score,
        is_foundation=req.is_foundation,
        approved=req.approved,
        has_review=req.has_review,
    )


@app.post("/api/get-generation-context")
def http_get_generation_context(
    req: ScopeRef,
    _claims: dict[str, Any] = Depends(_require_token),
) -> dict[str, Any]:
    return tools.get_generation_context(
        req.project_id,
        req.ref,
        req.tier,  # type: ignore[arg-type]
        comp_id=req.comp_id,
        parent_id=req.parent_id,
        sub_id=req.sub_id,
        phase=req.phase,
    )


@app.post("/api/get-review-context")
def http_get_review_context(
    req: GetReviewContextRequest,
    _claims: dict[str, Any] = Depends(_require_token),
) -> dict[str, Any]:
    return tools.get_review_context(
        req.project_id,
        req.ref,
        req.tier,  # type: ignore[arg-type]
        draft_sha=req.draft_sha,
        comp_id=req.comp_id,
        parent_id=req.parent_id,
        sub_id=req.sub_id,
        phase=req.phase,
    )


@app.post("/api/get-review-summary")
def http_get_review_summary(
    req: TierRefRequest,
    _claims: dict[str, Any] = Depends(_require_token),
) -> dict[str, Any]:
    return tools.get_review_summary(req.project_id, req.ref, req.tier)  # type: ignore[arg-type]


@app.post("/api/get-structure-summary")
def http_get_structure_summary(
    req: TierRefRequest,
    _claims: dict[str, Any] = Depends(_require_token),
) -> dict[str, Any]:
    return tools.get_structure_summary(req.project_id, req.ref, req.tier)  # type: ignore[arg-type]


@app.post("/api/compute-plan")
def http_compute_plan(
    req: ProjectRefRequest,
    _claims: dict[str, Any] = Depends(_require_token),
) -> dict[str, Any]:
    return tools.compute_plan(req.project_id, req.ref)


@app.post("/api/get-project-graph")
def http_get_project_graph(
    req: ProjectRefRequest,
    _claims: dict[str, Any] = Depends(_require_token),
) -> dict[str, Any]:
    return tools.get_project_graph(req.project_id, req.ref)


@app.post("/api/list-batches")
def http_list_batches(
    req: ListBatchesRequest,
    _claims: dict[str, Any] = Depends(_require_token),
) -> dict[str, Any]:
    return tools.list_batches(req.project_id, req.ref, status=req.status)


@app.post("/api/validate-artifact")
def http_validate_artifact(
    req: ValidateArtifactRequest,
    _claims: dict[str, Any] = Depends(_require_token),
) -> dict[str, Any]:
    return tools.validate_artifact(
        req.project_id,
        req.ref,
        req.tier,  # type: ignore[arg-type]
        req.body,
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=settings.bind_host, port=settings.bind_port)
