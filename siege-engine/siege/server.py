"""MCP + HTTP transport entry point.

The server exposes the same tool surface twice:

- ``/mcp`` — MCP transport for Claude Code (via the plugin manifest).
- ``/api`` — HTTP transport for the existing dashboard frontend.

Both call into ``siege.tools``; the transport layer is auth + JSON
shape + nothing else. Auth is bearer-token JWT verified against the
same secret the existing FastAPI dashboard uses (see ``siege.auth``).

Running standalone:

    python -m siege.server

The server uses FastAPI for the HTTP routes. The MCP transport reuses
the same FastAPI app — see ``_register_mcp_endpoint`` for the JSON-RPC
wrapper. This keeps deployment one process.

For local dev:

    SIEGE_JWT_SECRET_KEY=dev-secret uvicorn siege.server:app --reload --port 8080
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

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
# `http://...` (scheme downgrade). Any well-behaved client drops the
# Authorization header across the scheme downgrade, so MCP clients that
# happen to POST to `/mcp/` (with slash) lose auth on the retry. Turning
# the auto-redirect off makes the trailing slash a hard 404 instead —
# the client either fixes its URL or fails loudly. Both are better than
# silent auth loss.
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


@app.get("/api/debug/mcp-auth")
def debug_mcp_auth(
    project_id: str | None = None,
    _claims: dict[str, Any] = Depends(_require_token),
) -> dict[str, Any]:
    """Show what the MCP-side auth lookup sees for the current request.

    Counterpart to `/api/github/status` — that one tells you what the
    DASHBOARD's session sees, this one tells you what the MCP server's
    request context sees through the exact code path a tool call
    would take. If the dashboard says you're connected but this
    endpoint reports `has_token: false`, the bug is in
    siege.auth_lookup (or the context propagation), not in the
    OAuth flow.

    Never returns the raw token — only a prefix and length, enough
    to distinguish "no token" from "wrong token" without leaking.
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


# ---------------- Bootstrap script (open, no auth) ----------------
#
# Mobile Claude Code doesn't support `/plugin install`, so users on
# mobile need a per-project-repo seed of .mcp.json + .claude/commands/
# + .claude/skills/. This endpoint serves the bootstrap script that
# does that seeding; users (or Claude on their behalf) run:
#
#     curl -fsSL https://siege.strutco.io/bootstrap.sh | bash
#
# from inside their project repo. The script clones SiegeEngine
# shallowly and mirrors the plugin contents into the project. Auth-
# free intentionally — discoverable + scriptable.

# The script lives one directory up from siege-engine/, alongside the
# project root (`/home/user/SiegeEngine/scripts/`). In the deployed
# container the layout collapses; we resolve relative to the package
# and fall back to a few known candidate paths so dev + prod both
# work without hard-coding.
_BOOTSTRAP_CANDIDATES = (
    Path(__file__).resolve().parent.parent / "scripts" / "siege-bootstrap.sh",
    Path("/app/scripts/siege-bootstrap.sh"),
)


def _resolve_bootstrap_path() -> Path | None:
    for candidate in _BOOTSTRAP_CANDIDATES:
        if candidate.exists():
            return candidate
    return None


def bootstrap_script_response() -> PlainTextResponse:
    """Return the bootstrap script as a plain-text HTTP response.

    Shared between the MCP-mounted route (`/siege_mcp/bootstrap.sh`)
    and the top-level route registered in `backend.main` at
    `/bootstrap.sh`. The top-level route is what users actually hit
    via `curl https://siege.strutco.io/bootstrap.sh | bash`; the
    MCP-mounted one is a side effect of using `@app.get` here.
    """
    path = _resolve_bootstrap_path()
    if path is None:
        return PlainTextResponse(
            "# siege-bootstrap.sh not found on server — see\n"
            "# https://github.com/swaggerallen/siegeengine/blob/main/"
            "siege-engine/scripts/siege-bootstrap.sh\n",
            status_code=500,
            media_type="text/x-shellscript",
        )
    return PlainTextResponse(
        path.read_text(encoding="utf-8"),
        media_type="text/x-shellscript",
    )


@app.get("/bootstrap.sh")
def bootstrap_script() -> PlainTextResponse:
    return bootstrap_script_response()


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


# ---------------- MCP transport (protocol-compliant) ----------------
#
# The MCP protocol over HTTP is JSON-RPC 2.0 with a fixed set of
# methods the client calls. The first iteration of this endpoint
# implemented a custom dispatcher mapping JSON-RPC `method` directly
# to tool names (e.g. `"method": "list_refs"`), but real MCP clients
# (including Claude Code) call the standard protocol methods —
# `initialize`, `tools/list`, `tools/call` — and ignore everything
# else. That misimplementation made every standard method 404 with
# "Method not found" from the client's perspective and broke the
# entire plugin workflow upstream.
#
# This handler now speaks the real protocol:
#
#   initialize    → return server capabilities + info
#   tools/list    → return the tool catalog with JSON Schema
#   tools/call    → dispatch {name, arguments} to the underlying
#                   `tools.*` function
#
# Spec: https://modelcontextprotocol.io/specification


class MCPCall(BaseModel):
    """One JSON-RPC 2.0 message."""

    jsonrpc: str = Field(default="2.0")
    id: int | str | None = None
    method: str
    params: dict[str, Any] = Field(default_factory=dict)


# Per-tool argument schema, used for `tools/list`. Schemas describe the
# request body shape the LLM client will send; the dispatcher below
# unpacks the `arguments` dict into the underlying function call.

_TIER_ENUM = [
    "feature_expansion",
    "requirements",
    "sysarch",
    "comparch",
    "subcomparch",
    "impl",
    "fanin",
]


def _scope_schema(*, required: list[str] | None = None) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "project_id": {"type": "string"},
            "ref": {"type": "string", "description": "git ref (branch or sha)"},
            "tier": {"type": "string", "enum": _TIER_ENUM},
            "comp_id": {"type": "string"},
            "parent_id": {"type": "string"},
            "sub_id": {"type": "string"},
            "phase": {
                "type": "integer",
                "description": "phase index for a phased impl/fanin scope; omit for arch tiers",
            },
        },
        "required": required or ["project_id", "ref", "tier"],
    }


_TOOL_DEFS: list[dict[str, Any]] = [
    {
        "name": "list_refs",
        "description": "List git refs (branches + sha + subject) available for a project.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string"},
                "remote_url": {"type": "string"},
            },
            "required": ["project_id"],
        },
    },
    {
        "name": "get_state",
        "description": (
            "Read the state JSON for one scope on a ref. Returns the parsed state plus a "
            "`drift` block when the body's actual sha256 doesn't match the recorded value."
        ),
        "inputSchema": _scope_schema(),
    },
    {
        "name": "list_tier",
        "description": (
            "List every state scope at a tier on a ref, with optional status/score/foundation "
            "filters."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string"},
                "ref": {"type": "string"},
                "tier": {"type": "string", "enum": _TIER_ENUM},
                "status": {"type": "string"},
                "min_score": {"type": "integer"},
                "max_score": {"type": "integer"},
                "is_foundation": {"type": "boolean"},
                "approved": {"type": "boolean"},
                "has_review": {"type": "boolean"},
            },
            "required": ["project_id", "ref", "tier"],
        },
    },
    {
        "name": "get_generation_context",
        "description": (
            "Return the generation-context bundle for a scope: per-tier instructions + parent "
            "fragments + sibling pubapis + project sysarch sections + related features. The "
            "skill threads this verbatim into the LLM prompt."
        ),
        "inputSchema": _scope_schema(),
    },
    {
        "name": "get_review_context",
        "description": (
            "Return the reviewer-side bundle for a drafted scope. `draft_sha` must match the "
            "current draft.body_sha256 (drift guard)."
        ),
        "inputSchema": {
            **_scope_schema(),
            "properties": {
                **_scope_schema()["properties"],
                "draft_sha": {
                    "type": "string",
                    "description": "sha256 of the draft body; must match state.draft.body_sha256",
                },
            },
            "required": ["project_id", "ref", "tier", "draft_sha"],
        },
    },
    {
        "name": "get_review_summary",
        "description": (
            "Score histogram + worst-N intros for a tier. Drives the /regen_below candidate "
            "selection."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string"},
                "ref": {"type": "string"},
                "tier": {"type": "string", "enum": _TIER_ENUM},
            },
            "required": ["project_id", "ref", "tier"],
        },
    },
    {
        "name": "get_structure_summary",
        "description": (
            "Per-tier topological structure — comps, deps, foundation markers, kinds, plus "
            "tier-level aggregates."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string"},
                "ref": {"type": "string"},
                "tier": {"type": "string", "enum": _TIER_ENUM},
            },
            "required": ["project_id", "ref", "tier"],
        },
    },
    {
        "name": "compute_plan",
        "description": (
            "Compute the impl-tier phasing plan: per-phase impl nodes + topological "
            "build order, derived from the phase registry (state/phases/) and the "
            "comparch/subcomparch tiers. Reports auto-rearrangements (components pulled "
            "earlier by a dependency) and hard errors (unassigned features). Read-only "
            "projection — the mint-plan skill materializes the result."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string"},
                "ref": {"type": "string"},
            },
            "required": ["project_id", "ref"],
        },
    },
    {
        "name": "list_batches",
        "description": "List batch state files on a ref, optionally filtered by status.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string"},
                "ref": {"type": "string"},
                "status": {"type": "string"},
            },
            "required": ["project_id", "ref"],
        },
    },
    {
        "name": "validate_artifact",
        "description": (
            "Pre-commit validation gate for a tier artifact body. Returns `ok` + `errors` + "
            "`warnings` + extracted metadata. Doesn't read from git — pure-text check."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string"},
                "ref": {"type": "string"},
                "tier": {"type": "string", "enum": _TIER_ENUM},
                "body": {"type": "string"},
            },
            "required": ["project_id", "ref", "tier", "body"],
        },
    },
]


_TOOL_DISPATCH: dict[str, Callable[..., dict[str, Any]]] = {
    "list_refs": tools.list_refs,
    "get_state": tools.get_state,
    "list_tier": tools.list_tier,
    "get_generation_context": tools.get_generation_context,
    "get_review_context": tools.get_review_context,
    "get_review_summary": tools.get_review_summary,
    "get_structure_summary": tools.get_structure_summary,
    "compute_plan": tools.compute_plan,
    "list_batches": tools.list_batches,
    "validate_artifact": tools.validate_artifact,
}


_PROTOCOL_VERSION = "2024-11-05"
_SERVER_INFO = {"name": "siegeengine", "version": "0.1.0"}


def _ok(call_id: int | str | None, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": call_id, "result": result}


def _err(call_id: int | str | None, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": call_id, "error": {"code": code, "message": message}}


def _handle_initialize(_params: dict[str, Any]) -> dict[str, Any]:
    return {
        "protocolVersion": _PROTOCOL_VERSION,
        "capabilities": {"tools": {}},
        "serverInfo": _SERVER_INFO,
    }


def _handle_tools_list(_params: dict[str, Any]) -> dict[str, Any]:
    return {"tools": _TOOL_DEFS}


def _handle_tools_call(params: dict[str, Any]) -> dict[str, Any]:
    name = params.get("name")
    arguments = params.get("arguments") or {}
    fn = _TOOL_DISPATCH.get(name) if isinstance(name, str) else None
    if fn is None:
        return {
            "content": [{"type": "text", "text": f"unknown tool: {name!r}"}],
            "isError": True,
        }
    try:
        result = fn(**arguments)
    except TypeError as exc:
        return {
            "content": [{"type": "text", "text": f"invalid arguments to {name}: {exc}"}],
            "isError": True,
        }
    except Exception as exc:  # noqa: BLE001 — top-level RPC boundary
        logger.exception("MCP tool %s raised", name)
        return {
            "content": [{"type": "text", "text": f"{type(exc).__name__}: {exc}"}],
            "isError": True,
        }
    # Wrap structured tool output as a text content block carrying the
    # JSON serialization; the spec lets a tool return both `content`
    # (display-suitable) and `structuredContent` (parseable). Carrying
    # the JSON in `content[0].text` keeps clients that ignore the
    # structured field working too.
    import json as _json

    serialized = _json.dumps(result, indent=2, sort_keys=True)
    return {
        "content": [{"type": "text", "text": serialized}],
        "structuredContent": result,
        "isError": False,
    }


_METHOD_DISPATCH: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "initialize": _handle_initialize,
    "tools/list": _handle_tools_list,
    "tools/call": _handle_tools_call,
}


# Both `/mcp` and `/mcp/` accept calls. With redirect_slashes=False
# we avoid the 307-with-scheme-downgrade bug; with the trailing slash
# explicitly routed, clients that happen to canonicalize their URL
# with a slash also Just Work. Same handler either way.
@app.post("/mcp")
@app.post("/mcp/")
def mcp(
    call: MCPCall,
    _claims: dict[str, Any] = Depends(_require_token),
) -> dict[str, Any]:
    """MCP JSON-RPC entry point (protocol-compliant)."""
    # `notifications/*` per spec are fire-and-forget; clients send
    # them with no `id` field and expect no response. We still return
    # 200 with an empty result so HTTP semantics stay clean.
    if call.method.startswith("notifications/"):
        return _ok(call.id, {})
    handler = _METHOD_DISPATCH.get(call.method)
    if handler is None:
        return _err(call.id, -32601, f"Method not found: {call.method}")
    try:
        result = handler(call.params)
    except Exception as exc:  # noqa: BLE001 — top-level RPC boundary
        logger.exception("MCP method %s raised", call.method)
        return _err(call.id, -32000, str(exc))
    return _ok(call.id, result)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=settings.bind_host, port=settings.bind_port)
