"""Tests for GET /projects/:id/components/:compId/responsibility-coverage.

Single endpoint that returns both lists the subreqs detail pane
renders side by side:
- ``received``: top-level resps routed to this comp via sysarch
  decomposition edges (what the component was asked to own).
- ``computed``: subresps minted under this comp by subreqs mint
  (what the component broke its received responsibilities into).
"""

from __future__ import annotations

import os
import uuid

import pytest

os.environ.setdefault("SIEGE_DISABLE_WORKER_LOOP", "1")

try:
    import cryptography.hazmat.bindings._rust  # noqa: F401
except BaseException as _exc:  # pragma: no cover - env-dependent skip
    pytest.skip(
        f"cryptography/cffi environmental issue: {_exc!r}",
        allow_module_level=True,
    )

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from backend.auth.routes import get_current_user  # noqa: E402
from backend.database import Base, get_db  # noqa: E402
from backend.graph import events as ev  # noqa: E402
from backend.graph.ids import Kind, mint  # noqa: E402
from backend.graph.reducer import append_event  # noqa: E402
from backend.main import app  # noqa: E402
from backend.models import Project  # noqa: E402


@pytest.fixture()
def engine_and_factory(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    import backend.database as _database_mod

    monkeypatch.setattr(_database_mod, "SessionLocal", factory)
    yield engine, factory
    engine.dispose()


@pytest.fixture()
def db(engine_and_factory):
    _, factory = engine_and_factory
    s: Session = factory()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture()
def project(db):
    p = Project(id=str(uuid.uuid4()), name="Test", git_repo_path="/tmp/test")
    db.add(p)
    db.commit()
    return p


@pytest.fixture()
def client(db, project):
    def _get_db():
        yield db

    def _get_user():
        return object()

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[get_current_user] = _get_user
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _mint_top_resp(
    db: Session, project_id: str, name: str, display_order: int, content: str = ""
) -> str:
    rid = mint(db, Kind.RESP)
    append_event(
        db,
        project_id,
        ev.NodeCreated(
            node_id=rid,
            tier="resp",
            kind="domain",
            parent_id=None,
            name=name,
            display_order=display_order,
            content=content,
        ),
    )
    return rid


def _mint_comp(db: Session, project_id: str, name: str) -> str:
    cid = mint(db, Kind.COMP)
    append_event(
        db,
        project_id,
        ev.NodeCreated(
            node_id=cid,
            tier="comp",
            kind="domain",
            parent_id=None,
            name=name,
        ),
    )
    return cid


def _mint_subresp(
    db: Session,
    project_id: str,
    comp_id: str,
    name: str,
    display_order: int,
    content: str = "",
) -> str:
    rid = mint(db, Kind.RESP)
    append_event(
        db,
        project_id,
        ev.NodeCreated(
            node_id=rid,
            tier="resp",
            kind="domain",
            parent_id=comp_id,
            name=name,
            display_order=display_order,
            content=content,
        ),
    )
    return rid


def _connect_resp_to_comp(db: Session, project_id: str, resp_id: str, comp_id: str) -> None:
    edge_id = mint(db, Kind.EDGE)
    append_event(
        db,
        project_id,
        ev.EdgeCreated(
            edge_id=edge_id,
            edge_type="decomposition",
            source_id=resp_id,
            target_id=comp_id,
        ),
    )


class TestEmptyCase:
    def test_comp_with_no_resps_or_subresps(self, client, project, db):
        comp_id = _mint_comp(db, project.id, "Billing")
        db.commit()

        resp = client.get(
            f"/api/projects/{project.id}/components/{comp_id}/responsibility-coverage"
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body == {"received": [], "computed": []}


class TestReceivedOnly:
    def test_assigned_top_level_resps_appear_in_received(self, client, project, db):
        # Two resps, both routed to the same comp via decomposition edges.
        r1 = _mint_top_resp(db, project.id, "Authenticate users", 0, content="Verify creds.")
        r2 = _mint_top_resp(db, project.id, "Manage sessions", 1, content="Maintain sessions.")
        comp_id = _mint_comp(db, project.id, "Identity")
        _connect_resp_to_comp(db, project.id, r1, comp_id)
        _connect_resp_to_comp(db, project.id, r2, comp_id)
        db.commit()

        resp = client.get(
            f"/api/projects/{project.id}/components/{comp_id}/responsibility-coverage"
        )
        body = resp.json()
        assert len(body["received"]) == 2
        received_ids = [r["id"] for r in body["received"]]
        assert received_ids == [r1, r2]
        assert body["received"][0]["name"] == "Authenticate users"
        assert body["received"][0]["content"] == "Verify creds."
        assert body["computed"] == []


class TestComputedOnly:
    def test_subresps_appear_in_computed(self, client, project, db):
        comp_id = _mint_comp(db, project.id, "Identity")
        s1 = _mint_subresp(db, project.id, comp_id, "Password hashing", 0, content="Bcrypt.")
        s2 = _mint_subresp(db, project.id, comp_id, "Session tokens", 1, content="Opaque UUID4.")
        db.commit()

        resp = client.get(
            f"/api/projects/{project.id}/components/{comp_id}/responsibility-coverage"
        )
        body = resp.json()
        assert body["received"] == []
        assert len(body["computed"]) == 2
        computed_ids = [r["id"] for r in body["computed"]]
        assert computed_ids == [s1, s2]
        assert body["computed"][0]["name"] == "Password hashing"


class TestBothReceivedAndComputed:
    def test_returns_both_lists_independently(self, client, project, db):
        r1 = _mint_top_resp(db, project.id, "Authenticate users", 0)
        comp_id = _mint_comp(db, project.id, "Identity")
        _connect_resp_to_comp(db, project.id, r1, comp_id)
        s1 = _mint_subresp(db, project.id, comp_id, "Password hashing", 0)
        s2 = _mint_subresp(db, project.id, comp_id, "Session tokens", 1)
        db.commit()

        resp = client.get(
            f"/api/projects/{project.id}/components/{comp_id}/responsibility-coverage"
        )
        body = resp.json()
        assert [r["id"] for r in body["received"]] == [r1]
        assert [r["id"] for r in body["computed"]] == [s1, s2]


class TestIsolation:
    def test_other_comp_resps_do_not_leak(self, client, project, db):
        # Set up two comps with their own resps and subresps and
        # confirm each comp's coverage query returns only its own.
        r_a = _mint_top_resp(db, project.id, "Resp A", 0)
        r_b = _mint_top_resp(db, project.id, "Resp B", 1)
        comp_a = _mint_comp(db, project.id, "CompA")
        comp_b = _mint_comp(db, project.id, "CompB")
        _connect_resp_to_comp(db, project.id, r_a, comp_a)
        _connect_resp_to_comp(db, project.id, r_b, comp_b)
        s_a = _mint_subresp(db, project.id, comp_a, "SubA", 0)
        s_b = _mint_subresp(db, project.id, comp_b, "SubB", 0)
        db.commit()

        body_a = client.get(
            f"/api/projects/{project.id}/components/{comp_a}/responsibility-coverage"
        ).json()
        body_b = client.get(
            f"/api/projects/{project.id}/components/{comp_b}/responsibility-coverage"
        ).json()

        assert [r["id"] for r in body_a["received"]] == [r_a]
        assert [r["id"] for r in body_a["computed"]] == [s_a]
        assert [r["id"] for r in body_b["received"]] == [r_b]
        assert [r["id"] for r in body_b["computed"]] == [s_b]


class TestSubcompRejected:
    def test_404_when_comp_id_is_a_subcomponent(self, client, project, db):
        comp_id = _mint_comp(db, project.id, "Parent")
        sub_id = mint(db, Kind.COMP)
        append_event(
            db,
            project.id,
            ev.NodeCreated(
                node_id=sub_id,
                tier="comp",
                kind="domain",
                parent_id=comp_id,
                name="Sub",
            ),
        )
        db.commit()

        resp = client.get(f"/api/projects/{project.id}/components/{sub_id}/responsibility-coverage")
        assert resp.status_code == 404


class TestOrdering:
    def test_received_ordered_by_display_order(self, client, project, db):
        # Insert in reverse order and confirm the response sorts
        # ascending by display_order.
        r_high = _mint_top_resp(db, project.id, "High", 2)
        r_low = _mint_top_resp(db, project.id, "Low", 0)
        r_mid = _mint_top_resp(db, project.id, "Mid", 1)
        comp_id = _mint_comp(db, project.id, "C")
        for rid in (r_high, r_low, r_mid):
            _connect_resp_to_comp(db, project.id, rid, comp_id)
        db.commit()

        body = client.get(
            f"/api/projects/{project.id}/components/{comp_id}/responsibility-coverage"
        ).json()
        assert [r["id"] for r in body["received"]] == [r_low, r_mid, r_high]
