"""Tests for cohort + sampler-config routes (Phase 3a)."""

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
from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from backend.auth.routes import get_current_user  # noqa: E402
from backend.database import Base, get_db  # noqa: E402
from backend.graph import events as ev  # noqa: E402
from backend.graph.ids import Kind, mint  # noqa: E402
from backend.graph.reducer import append_event  # noqa: E402
from backend.main import app  # noqa: E402
from backend.models import Project, User  # noqa: E402
from backend.models.cohort import Cohort  # noqa: E402
from backend.models.cohort_sampler_config import CohortSamplerConfig  # noqa: E402

# ── Fixtures ───────────────────────────────────────────────────────


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
def client(engine_and_factory):
    _, factory = engine_and_factory

    def _override_db():
        s = factory()
        try:
            yield s
        finally:
            s.close()

    def _override_user():
        return User(id="u1", username="t", password_hash="x", role="admin")

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user] = _override_user
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _seed_project(db: Session) -> str:
    project_id = str(uuid.uuid4())
    db.add(Project(id=project_id, name="T", git_repo_path="/tmp/t"))
    db.flush()
    return project_id


def _seed_top_level_comp(
    db: Session,
    project_id: str,
    *,
    name: str,
    kind: str = "domain",
    is_foundation: bool = False,
) -> str:
    comp_id = mint(db, Kind.COMP)
    append_event(
        db,
        project_id,
        ev.NodeCreated(
            node_id=comp_id,
            tier="comp",
            kind=kind,
            parent_id=None,
            name=name,
            display_order=0,
            is_foundation=is_foundation,
        ),
    )
    return comp_id


# ── Cohort CRUD ────────────────────────────────────────────────────


class TestCohortCRUD:
    def test_create_and_get_cohort(self, db, client):
        project_id = _seed_project(db)
        db.commit()
        resp = client.post(
            f"/api/projects/{project_id}/cohorts",
            json={"tier": "comparch", "name": "v1", "comp_ids": ["comp_a", "comp_b"]},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        cohort_id = body["id"]
        assert body["tier"] == "comparch"
        assert body["comp_ids"] == ["comp_a", "comp_b"]
        assert body["archived"] is False
        # GET
        resp = client.get(f"/api/projects/{project_id}/cohorts/{cohort_id}")
        assert resp.status_code == 200
        assert resp.json()["id"] == cohort_id

    def test_list_cohorts_filters_by_tier_and_archived(self, db, client):
        project_id = _seed_project(db)
        db.commit()
        client.post(
            f"/api/projects/{project_id}/cohorts",
            json={"tier": "comparch", "name": "active"},
        )
        archived_resp = client.post(
            f"/api/projects/{project_id}/cohorts",
            json={"tier": "comparch", "name": "old"},
        )
        archived_id = archived_resp.json()["id"]
        client.patch(
            f"/api/projects/{project_id}/cohorts/{archived_id}",
            json={"archived": True},
        )
        client.post(
            f"/api/projects/{project_id}/cohorts",
            json={"tier": "impl", "name": "impl_one"},
        )
        # Default list
        all_resp = client.get(f"/api/projects/{project_id}/cohorts")
        assert {c["name"] for c in all_resp.json()["cohorts"]} == {
            "active",
            "old",
            "impl_one",
        }
        # Tier filter
        comparch_resp = client.get(
            f"/api/projects/{project_id}/cohorts", params={"tier": "comparch"}
        )
        assert {c["name"] for c in comparch_resp.json()["cohorts"]} == {"active", "old"}
        # Archived filter
        active_resp = client.get(f"/api/projects/{project_id}/cohorts", params={"archived": False})
        assert {c["name"] for c in active_resp.json()["cohorts"]} == {
            "active",
            "impl_one",
        }

    def test_patch_updates_name_comp_ids_archived(self, db, client):
        project_id = _seed_project(db)
        db.commit()
        cohort_id = client.post(
            f"/api/projects/{project_id}/cohorts",
            json={"tier": "comparch", "comp_ids": ["a"]},
        ).json()["id"]
        resp = client.patch(
            f"/api/projects/{project_id}/cohorts/{cohort_id}",
            json={"name": "renamed", "comp_ids": ["a", "b"], "archived": True},
        )
        body = resp.json()
        assert body["name"] == "renamed"
        assert body["comp_ids"] == ["a", "b"]
        assert body["archived"] is True

    def test_get_cohort_404_for_unknown_id(self, db, client):
        project_id = _seed_project(db)
        db.commit()
        resp = client.get(f"/api/projects/{project_id}/cohorts/cohort_nope")
        assert resp.status_code == 404


# ── Sampler config ────────────────────────────────────────────────


class TestSamplerConfig:
    def test_get_seeds_default_for_comparch_on_first_read(self, db, client):
        project_id = _seed_project(db)
        db.commit()
        resp = client.get(f"/api/projects/{project_id}/sampler-configs/comparch")
        assert resp.status_code == 200
        body = resp.json()
        assert body["tier"] == "comparch"
        assert body["axes"]["axes"]
        keys = [a["key"] for a in body["axes"]["axes"]]
        assert "kind" in keys
        assert "is_foundation" in keys
        # Idempotent — second GET reuses the same row
        second = client.get(f"/api/projects/{project_id}/sampler-configs/comparch")
        assert second.json()["id"] == body["id"]

    def test_put_replaces_axes(self, db, client):
        project_id = _seed_project(db)
        db.commit()
        client.get(f"/api/projects/{project_id}/sampler-configs/comparch")
        resp = client.put(
            f"/api/projects/{project_id}/sampler-configs/comparch",
            json={"axes": {"axes": [{"key": "kind", "type": "categorical", "weight": 2.0}]}},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["axes"]["axes"]) == 1
        assert body["axes"]["axes"][0]["weight"] == 2.0
        # Verify persistence
        cfg_in_db = db.execute(select(CohortSamplerConfig)).scalar_one()
        assert cfg_in_db.axes["axes"][0]["weight"] == 2.0

    def test_get_unknown_tier_seeds_empty_axes(self, db, client):
        project_id = _seed_project(db)
        db.commit()
        resp = client.get(f"/api/projects/{project_id}/sampler-configs/sysarch")
        assert resp.status_code == 200
        # No default axes seeded for sysarch yet, but the row gets
        # created so the user can populate via PUT.
        assert resp.json()["axes"] == {"axes": []}


# ── Auto-suggest preview ──────────────────────────────────────────


class TestAutoSuggest:
    def test_returns_suggestion_using_seeded_axes(self, db, client):
        project_id = _seed_project(db)
        # Two top-level comps with different kinds → kind axis should
        # cause both to be picked.
        _seed_top_level_comp(db, project_id, name="A", kind="domain")
        _seed_top_level_comp(db, project_id, name="B", kind="presentational")
        db.commit()
        resp = client.post(
            f"/api/projects/{project_id}/cohorts/auto-suggest?tier=comparch",
            json={"target_size": 2},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["tier"] == "comparch"
        assert len(body["suggested_ids"]) == 2

    def test_excludes_supplied_ids(self, db, client):
        project_id = _seed_project(db)
        comp_a = _seed_top_level_comp(db, project_id, name="A", kind="domain")
        _seed_top_level_comp(db, project_id, name="B", kind="presentational")
        db.commit()
        resp = client.post(
            f"/api/projects/{project_id}/cohorts/auto-suggest?tier=comparch",
            json={"target_size": 2, "exclude_ids": [comp_a]},
        )
        assert comp_a not in resp.json()["suggested_ids"]

    def test_unknown_tier_returns_404(self, db, client):
        project_id = _seed_project(db)
        db.commit()
        resp = client.post(
            f"/api/projects/{project_id}/cohorts/auto-suggest?tier=manifest",
            json={"target_size": 2},
        )
        assert resp.status_code == 404


# ── Direct DB sanity ──────────────────────────────────────────────


def test_create_cohort_persists_row(db, client):
    project_id = _seed_project(db)
    db.commit()
    client.post(
        f"/api/projects/{project_id}/cohorts",
        json={"tier": "comparch", "name": "row"},
    )
    rows = list(db.execute(select(Cohort)).scalars())
    assert len(rows) == 1
    assert rows[0].name == "row"
