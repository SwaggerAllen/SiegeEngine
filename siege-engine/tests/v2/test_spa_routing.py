"""Integration test for the root FastAPI app's SPA catch-all.

Unmatched paths must fall through to the SPA so the dashboard's
client-side routes (`/cheatsheet`, `/projects`, …) resolve to
index.html. Lives in `tests/v2/` (not `siege/tests/`) because the
contract is a property of `backend.main:app`'s mounted assembly, not
of any one module.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("SIEGE_ANTHROPIC_API_KEY", "test")

from fastapi.testclient import TestClient  # noqa: E402

from backend.main import app  # noqa: E402

# The SPA catch-all in backend.main is only registered when
# frontend/dist/ exists (production build present). CI's backend-tests
# job doesn't build the frontend, so the route — and this test — only
# exercise under the production layout; skip otherwise.
_SPA_BUILT = Path("frontend/dist/index.html").exists()


@pytest.mark.skipif(
    not _SPA_BUILT,
    reason="frontend/dist/ not built — SPA catch-all isn't registered in this env",
)
def test_spa_catchall_serves_html():
    c = TestClient(app)
    r = c.get("/cheatsheet")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert "<!doctype html>" in r.text.lower()
