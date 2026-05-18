"""Integration tests for the root FastAPI app's route ordering.

The mobile-CC on-ramp depends on `https://<host>/bootstrap.sh`
returning the bash script, not the SPA's index.html. The SPA catch-all
at `/{full_path:path}` would happily swallow the request if the
explicit route weren't registered first — this test pins that
invariant so we don't regress.

Lives in `tests/v2/` (not `siege_mcp/tests/`) because the contract
under test is `backend.main:app`'s route order: a property of the
mounted assembly, not of `siege_mcp.server` alone.
"""

from __future__ import annotations

import os

os.environ.setdefault("SIEGE_ANTHROPIC_API_KEY", "test")

from fastapi.testclient import TestClient  # noqa: E402

from backend.main import app  # noqa: E402


def test_bootstrap_sh_top_level_returns_shell_script():
    c = TestClient(app)
    r = c.get("/bootstrap.sh")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/x-shellscript")
    assert r.text.startswith("#!/usr/bin/env bash")
    # Sanity-check the canonical bits the script must carry.
    assert "siege-bootstrap" in r.text
    assert "MCP_URL" in r.text


def test_bootstrap_sh_via_mcp_mount_also_works():
    """The mount-side route is a side effect of `@app.get` on the inner
    app, but it should keep working — keeps the contract honest if
    someone reaches it that way."""
    c = TestClient(app)
    r = c.get("/siege_mcp/bootstrap.sh")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/x-shellscript")
    assert r.text.startswith("#!/usr/bin/env bash")


def test_spa_catchall_still_serves_html():
    """Other unmatched paths must still fall through to the SPA so
    the dashboard routes (`/cheatsheet`, `/projects`, etc.) work."""
    c = TestClient(app)
    r = c.get("/cheatsheet")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert "<!doctype html>" in r.text.lower() or "<!DOCTYPE html>" in r.text
