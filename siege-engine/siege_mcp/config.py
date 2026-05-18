"""siege_mcp configuration.

Reads environment variables with the ``SIEGE_`` prefix to stay aligned
with the existing backend's settings. The MCP server runs alongside (or
eventually replaces) the FastAPI backend, so sharing the env conventions
makes deployment one less moving part.
"""

from __future__ import annotations

import os

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Auth — same JWT as the existing dashboard so a single login covers
    # both transports.
    jwt_secret_key: str = "CHANGE-ME-IN-PRODUCTION"
    jwt_algorithm: str = "HS256"
    jwt_expiry_hours: int = 720

    # Git repo cache — where `GitView` materializes the bare clones it
    # fetches from. Per-project subdirs keyed by project slug.
    git_repos_base_path: str = "data/repos"

    # GitView cache TTL. After this many seconds idle, drop the in-memory
    # snapshot. The on-disk clone stays — only the parsed-state cache is
    # cleared.
    git_view_idle_ttl_seconds: int = 600

    # Per-ref fetch debounce. Multiple reads on the same ref within this
    # window share one `git fetch` call.
    git_fetch_debounce_seconds: float = 2.0

    # Idempotency dedup window — server rejects duplicate (scope, nonce)
    # writes within this many seconds. Skills should rarely hit this; the
    # check is defence against mobile CC double-commits.
    idempotency_dedup_seconds: int = 86_400  # 24h

    # Server bind. MCP transport binds on `${host}:${port}/mcp`; HTTP
    # transport on `${host}:${port}/api`. Same process, same FastAPI app.
    bind_host: str = "127.0.0.1"
    bind_port: int = 8080

    # CORS for the HTTP transport (frontend lives at the same host in
    # prod, but local dev uses 5173).
    cors_origins: list[str] = ["http://localhost:5173"]

    model_config = {"env_file": ".env", "env_prefix": "SIEGE_"}


settings = Settings()

# Fallback: accept ANTHROPIC_API_KEY directly in case the existing
# backend's env file is in scope at startup. The MCP server itself
# doesn't make LLM calls (skills do, via Claude Code), but a stray
# pre-set env var shouldn't break anything.
_ = os.environ.get("ANTHROPIC_API_KEY", "")
