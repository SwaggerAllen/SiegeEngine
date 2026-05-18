"""MCP + HTTP transport entry point.

The server exposes the same tool surface twice:

- ``/mcp`` — MCP transport for Claude Code (via the plugin manifest).
- ``/api`` — HTTP transport for the existing dashboard frontend.

Both call into ``siege_mcp.tools``; the transport layer is auth + JSON
shape + nothing else. Auth is bearer-token JWT verified against the
same secret the existing FastAPI dashboard uses (see ``siege_mcp.auth``).

Running standalone:

    python -m siege_mcp.server

The server uses FastAPI for the HTTP routes. The MCP transport reuses
the same FastAPI app — see ``_register_mcp_endpoint`` for the JSON-RPC
wrapper. This keeps deployment one process.

For local dev:

    SIEGE_JWT_SECRET_KEY=dev-secret uvicorn siege_mcp.server:app --reload --port 8080
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

from siege_mcp import tools
from siege_mcp.auth import AuthError, verify_request_token
from siege_mcp.config import settings

logger = logging.getLogger(__name__)


# ---------------- Auth dependency ----------------


def _require_token(authorization: str | None = Header(default=None)) -> dict[str, Any]:
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


app = FastAPI(title="siege_mcp", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


# ---------------- Cheat sheet (open, no auth) ----------------
#
# Served as the source for the dashboard's /cheatsheet page. Kept open
# (no JWT required) because it's static documentation — the frontend
# fetches it on every render. The markdown body lives in the repo at
# docs/cheatsheet.md; CLAUDE.md flags this file as load-bearing so it
# stays in sync as commands + skills evolve.

_CHEATSHEET_PATH = Path(__file__).resolve().parent.parent / "docs" / "cheatsheet.md"


@app.get("/api/cheatsheet")
def cheatsheet() -> dict[str, str]:
    if not _CHEATSHEET_PATH.exists():
        return {"markdown": "# Cheat sheet missing\n\nExpected at docs/cheatsheet.md."}
    return {"markdown": _CHEATSHEET_PATH.read_text(encoding="utf-8")}


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


@app.get("/bootstrap.sh")
def bootstrap_script() -> PlainTextResponse:
    path = _resolve_bootstrap_path()
    if path is None:
        return PlainTextResponse(
            "# siege-bootstrap.sh not found on server — see\n"
            "# https://github.com/swaggerallen/siegeengine/blob/main/scripts/siege-bootstrap.sh\n",
            status_code=500,
            media_type="text/x-shellscript",
        )
    return PlainTextResponse(
        path.read_text(encoding="utf-8"),
        media_type="text/x-shellscript",
    )


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


# ---------------- MCP transport ----------------


class MCPCall(BaseModel):
    """One JSON-RPC-shaped MCP tool call.

    The MCP protocol uses JSON-RPC 2.0; we accept a minimal shape and
    dispatch by tool name. ``params`` is passed through verbatim to the
    tool function as kwargs.
    """

    jsonrpc: str = Field(default="2.0")
    id: int | str | None = None
    method: str
    params: dict[str, Any] = Field(default_factory=dict)


_MCP_DISPATCH: dict[str, Callable[..., dict[str, Any]]] = {
    "list_refs": tools.list_refs,
    "get_state": tools.get_state,
    "list_tier": tools.list_tier,
    "get_generation_context": tools.get_generation_context,
    "get_review_context": tools.get_review_context,
    "get_review_summary": tools.get_review_summary,
    "get_structure_summary": tools.get_structure_summary,
    "list_batches": tools.list_batches,
    "validate_artifact": tools.validate_artifact,
}


@app.post("/mcp")
def mcp(
    call: MCPCall,
    _claims: dict[str, Any] = Depends(_require_token),
) -> dict[str, Any]:
    """MCP JSON-RPC entry point."""
    fn = _MCP_DISPATCH.get(call.method)
    if fn is None:
        return {
            "jsonrpc": "2.0",
            "id": call.id,
            "error": {"code": -32601, "message": f"Method not found: {call.method}"},
        }
    try:
        result = fn(**call.params)
    except TypeError as exc:
        return {
            "jsonrpc": "2.0",
            "id": call.id,
            "error": {"code": -32602, "message": f"Invalid params: {exc}"},
        }
    except Exception as exc:  # noqa: BLE001 — top-level RPC boundary
        logger.exception("MCP tool %s raised", call.method)
        return {
            "jsonrpc": "2.0",
            "id": call.id,
            "error": {"code": -32000, "message": str(exc)},
        }
    return {"jsonrpc": "2.0", "id": call.id, "result": result}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=settings.bind_host, port=settings.bind_port)
