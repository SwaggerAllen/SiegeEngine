"""Web UI auth-flow tests via Starlette TestClient."""
from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from wgtracker.web.app import create_app


@pytest.fixture()
def client():
    return TestClient(create_app(), follow_redirects=False)


def test_fresh_db_redirects_to_setup(client):
    r = client.get("/")
    assert r.status_code == 303
    assert r.headers["location"] == "/setup"


def test_first_registration_becomes_admin_and_can_reach_admin(client):
    r = client.post("/setup", data={"email": "admin@x.com", "password": "password123"})
    assert r.status_code == 303 and r.headers["location"] == "/threads"
    # Session cookie now set; admin page is reachable.
    r = client.get("/admin")
    assert r.status_code == 200
    assert "Invite links" in r.text


def test_setup_closes_after_first_user(client):
    client.post("/setup", data={"email": "admin@x.com", "password": "password123"})
    r = client.get("/setup")
    assert r.status_code == 303 and r.headers["location"] == "/login"


def test_unauthenticated_browse_redirects_to_login(client):
    client.post("/setup", data={"email": "admin@x.com", "password": "password123"})
    fresh = TestClient(create_app(), follow_redirects=False)
    r = fresh.get("/threads")
    assert r.status_code == 303 and r.headers["location"] == "/login"


def test_admin_creates_invite_then_viewer_registers_and_is_readonly(client):
    client.post("/setup", data={"email": "admin@x.com", "password": "password123"})
    r = client.post("/admin/invites", data={"note": "alice", "expires_in_days": 14})
    assert r.status_code == 200
    m = re.search(r"/invite/([A-Za-z0-9_\-]+)", r.text)
    assert m, "invite link should be rendered"
    token = m.group(1)

    # New client (the invitee).
    viewer = TestClient(create_app(), follow_redirects=False)
    page = viewer.get(f"/invite/{token}")
    assert page.status_code == 200 and "read-only" in page.text
    reg = viewer.post(
        f"/invite/{token}", data={"email": "alice@x.com", "password": "password123"}
    )
    assert reg.status_code == 303 and reg.headers["location"] == "/threads"

    # Viewer can browse...
    assert viewer.get("/threads").status_code == 200
    # ...but cannot manage invites.
    forbidden = viewer.get("/admin")
    assert forbidden.status_code == 200 and "Admins only" in forbidden.text

    # Token is single-use now.
    third = TestClient(create_app(), follow_redirects=False)
    assert "already used" in third.get(f"/invite/{token}").text


def test_healthz(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["status"] in ("ok", "degraded")
