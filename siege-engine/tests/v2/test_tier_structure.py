"""Tests for the per-tier structure-summary aggregation.

Two layers of coverage:

- Per-tier extractor functions — exercise each of the eight
  extractors against a hand-seeded project and check the shape +
  numbers in ``per_node`` + ``aggregate``.
- ``GET /tiers/{tier}/structure-summary`` endpoint — happy-path
  smoke + 404 for unknown tier. The service's behaviour is
  exercised at unit level so the route test only verifies wiring.
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
from backend.graph.tier_structure import (  # noqa: E402
    extract_comparch_structure,
    extract_expansion_structure,
    extract_fanin_structure,
    extract_impl_structure,
    extract_references_structure,
    extract_requirements_structure,
    extract_subcomparch_structure,
    extract_sysarch_structure,
    gather_tier_structure_summary,
)
from backend.main import app  # noqa: E402
from backend.models import Project, User  # noqa: E402

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


def _seed_project(db: Session) -> str:
    project_id = str(uuid.uuid4())
    db.add(Project(id=project_id, name="T", git_repo_path="/tmp/t"))
    db.flush()
    return project_id


def _seed_node(
    db: Session,
    project_id: str,
    *,
    node_id: str,
    tier: str,
    name: str,
    parent_id: str | None = None,
    kind: str = "domain",
    is_foundation: bool = False,
    content: str = "",
    is_implicit: bool = False,
    is_deferred: bool = False,
) -> str:
    append_event(
        db,
        project_id,
        ev.NodeCreated(
            node_id=node_id,
            tier=tier,
            kind=kind,
            parent_id=parent_id,
            name=name,
            display_order=0,
            content=content,
            is_implicit=is_implicit,
            is_deferred=is_deferred,
            is_foundation=is_foundation,
        ),
    )
    return node_id


def _add_edge(
    db: Session, project_id: str, *, edge_type: str, source_id: str, target_id: str
) -> None:
    append_event(
        db,
        project_id,
        ev.EdgeCreated(
            edge_id=mint(db, Kind.EDGE),
            edge_type=edge_type,
            source_id=source_id,
            target_id=target_id,
        ),
    )


# ── Extractor unit tests ───────────────────────────────────────────


class TestExpansionStructure:
    def test_empty_project(self, db):
        project_id = _seed_project(db)
        db.commit()
        s = extract_expansion_structure(db, project_id)
        assert s.tier == "expansion"
        assert s.per_node == ()
        assert s.aggregate["feat_count"] == 0
        assert s.aggregate["group_count"] == 0

    def test_counts_feats_and_groups(self, db):
        project_id = _seed_project(db)
        _seed_node(
            db,
            project_id,
            node_id=mint(db, Kind.EXPANSION),
            tier="expansion",
            name="Expansion",
            content="<features>...</features>",
        )
        _seed_node(
            db,
            project_id,
            node_id=mint(db, Kind.FEAT),
            tier="feat",
            name="Login",
        )
        _seed_node(
            db,
            project_id,
            node_id=mint(db, Kind.FEAT),
            tier="feat",
            name="Logout",
            is_implicit=True,
        )
        _seed_node(
            db,
            project_id,
            node_id=mint(db, Kind.FEAT),
            tier="feat",
            name="Skipme",
            is_deferred=True,
        )
        db.commit()
        s = extract_expansion_structure(db, project_id)
        assert s.aggregate["feat_count"] == 3
        assert s.aggregate["implicit_feat_count"] == 1
        assert s.aggregate["deferred_feat_count"] == 1
        assert len(s.per_node) == 1
        assert s.per_node[0].metrics["feat_count"] == 3
        assert s.per_node[0].metrics["has_content"] is True


class TestRequirementsStructure:
    def test_resp_feat_decomposition_counts(self, db):
        project_id = _seed_project(db)
        _seed_node(
            db,
            project_id,
            node_id=mint(db, Kind.REQS),
            tier="reqs",
            name="Reqs",
            content="<reqs>...</reqs>",
        )
        resp_a = _seed_node(
            db,
            project_id,
            node_id=mint(db, Kind.RESP),
            tier="resp",
            name="RespA",
        )
        feat_a = _seed_node(
            db,
            project_id,
            node_id=mint(db, Kind.FEAT),
            tier="feat",
            name="FeatA",
        )
        feat_b = _seed_node(
            db,
            project_id,
            node_id=mint(db, Kind.FEAT),
            tier="feat",
            name="FeatB",
        )
        _add_edge(db, project_id, edge_type="decomposition", source_id=resp_a, target_id=feat_a)
        _add_edge(db, project_id, edge_type="decomposition", source_id=resp_a, target_id=feat_b)
        db.commit()
        s = extract_requirements_structure(db, project_id)
        assert s.aggregate["top_resp_count"] == 1
        assert s.aggregate["feat_count"] == 2
        assert s.aggregate["feats_per_resp"]["count"] == 1
        assert s.aggregate["feats_per_resp"]["max"] == 2


class TestSysarchStructure:
    def test_kind_and_dep_counts(self, db):
        project_id = _seed_project(db)
        _seed_node(
            db,
            project_id,
            node_id=mint(db, Kind.SYSARCH),
            tier="sysarch",
            name="Sysarch",
        )
        comp_a = _seed_node(
            db,
            project_id,
            node_id=mint(db, Kind.COMP),
            tier="comp",
            name="Domain",
            kind="domain",
            is_foundation=True,
        )
        comp_b = _seed_node(
            db,
            project_id,
            node_id=mint(db, Kind.COMP),
            tier="comp",
            name="UI",
            kind="presentational",
        )
        _add_edge(db, project_id, edge_type="dependency", source_id=comp_b, target_id=comp_a)
        _add_edge(db, project_id, edge_type="domain_parent", source_id=comp_b, target_id=comp_a)
        db.commit()
        s = extract_sysarch_structure(db, project_id)
        assert s.aggregate["top_comp_count"] == 2
        assert s.aggregate["domain_count"] == 1
        assert s.aggregate["presentational_count"] == 1
        assert s.aggregate["foundation_count"] == 1
        assert s.aggregate["top_dep_count"] == 1
        assert s.aggregate["domain_parent_count"] == 1


class TestComparchStructure:
    def test_per_comp_metrics_and_multi_owner(self, db):
        project_id = _seed_project(db)
        # Two top-level comps, one of which has subs co-owning a resp.
        comp_billing = _seed_node(
            db,
            project_id,
            node_id=mint(db, Kind.COMP),
            tier="comp",
            name="Billing",
            kind="domain",
            content="<comparch>...</comparch>",
        )
        comp_auth = _seed_node(
            db,
            project_id,
            node_id=mint(db, Kind.COMP),
            tier="comp",
            name="Auth",
            kind="domain",
            is_foundation=True,
        )
        sub_a = _seed_node(
            db,
            project_id,
            node_id=mint(db, Kind.COMP),
            tier="comp",
            name="BillingRead",
            parent_id=comp_billing,
        )
        sub_b = _seed_node(
            db,
            project_id,
            node_id=mint(db, Kind.COMP),
            tier="comp",
            name="BillingWrite",
            parent_id=comp_billing,
        )
        # Top-level resp claimed by both subs (multi-owner).
        resp = _seed_node(
            db,
            project_id,
            node_id=mint(db, Kind.RESP),
            tier="resp",
            name="HandlesPayments",
        )
        _add_edge(db, project_id, edge_type="decomposition", source_id=resp, target_id=comp_billing)
        _add_edge(db, project_id, edge_type="decomposition", source_id=resp, target_id=sub_a)
        _add_edge(db, project_id, edge_type="decomposition", source_id=resp, target_id=sub_b)
        # Outbound dep + sub-dep
        _add_edge(
            db,
            project_id,
            edge_type="dependency",
            source_id=comp_billing,
            target_id=comp_auth,
        )
        _add_edge(db, project_id, edge_type="dependency", source_id=sub_a, target_id=sub_b)
        db.commit()

        s = extract_comparch_structure(db, project_id)
        assert s.aggregate["top_comp_count"] == 2
        assert s.aggregate["foundation_count"] == 1
        assert s.aggregate["empty_subs_count"] == 1  # Auth has no subs
        assert s.aggregate["any_multi_owner_count"] == 1

        rows = {r.name: r for r in s.per_node}
        assert rows["Billing"].metrics["sub_count"] == 2
        assert rows["Billing"].metrics["resp_count"] == 1
        assert rows["Billing"].metrics["dep_count"] == 1
        assert rows["Billing"].metrics["sub_dep_count"] == 1
        assert rows["Billing"].metrics["multi_owner_resp_count"] == 1
        assert rows["Billing"].metrics["empty_subcomponents"] is False
        assert rows["Auth"].metrics["sub_count"] == 0
        assert rows["Auth"].metrics["empty_subcomponents"] is True
        assert rows["Auth"].metrics["is_foundation"] is True


class TestSubcomparchStructure:
    def test_per_sub_owns_and_dep_split(self, db):
        project_id = _seed_project(db)
        # Two top-level comps + one sub each; sub_a depends on sub_b
        # (same-parent), sub_a also depends on top-level B
        # (parent-sibling).
        top_a = _seed_node(
            db,
            project_id,
            node_id=mint(db, Kind.COMP),
            tier="comp",
            name="A",
            kind="domain",
        )
        top_b = _seed_node(
            db,
            project_id,
            node_id=mint(db, Kind.COMP),
            tier="comp",
            name="B",
            kind="presentational",
        )
        sub_a1 = _seed_node(
            db,
            project_id,
            node_id=mint(db, Kind.COMP),
            tier="comp",
            name="A1",
            parent_id=top_a,
            content="<subcomparch>...</subcomparch>",
        )
        sub_a2 = _seed_node(
            db,
            project_id,
            node_id=mint(db, Kind.COMP),
            tier="comp",
            name="A2",
            parent_id=top_a,
        )
        # Resp + decomp edges (sub_a1 + sub_a2 co-own a resp).
        resp = _seed_node(
            db,
            project_id,
            node_id=mint(db, Kind.RESP),
            tier="resp",
            name="SharedResp",
        )
        _add_edge(db, project_id, edge_type="decomposition", source_id=resp, target_id=sub_a1)
        _add_edge(db, project_id, edge_type="decomposition", source_id=resp, target_id=sub_a2)
        # sub_a1 deps
        _add_edge(db, project_id, edge_type="dependency", source_id=sub_a1, target_id=sub_a2)
        _add_edge(db, project_id, edge_type="dependency", source_id=sub_a1, target_id=top_b)
        db.commit()

        s = extract_subcomparch_structure(db, project_id)
        assert s.aggregate["sub_count"] == 2
        assert s.aggregate["any_co_owned_count"] == 2
        assert s.aggregate["with_content_count"] == 1

        rows = {r.name: r for r in s.per_node}
        a1 = rows["A1"].metrics
        assert a1["parent_name"] == "A"
        assert a1["parent_kind"] == "domain"
        assert a1["owns_resp_count"] == 1
        assert a1["dep_count"] == 2
        assert a1["same_parent_dep_count"] == 1
        assert a1["parent_sibling_dep_count"] == 1
        assert a1["co_owned_resp_count"] == 1


class TestImplFanInReferencesStructure:
    def test_impl_owners_and_line_count(self, db):
        project_id = _seed_project(db)
        top = _seed_node(
            db,
            project_id,
            node_id=mint(db, Kind.COMP),
            tier="comp",
            name="Foundation",
            is_foundation=True,
        )
        impl = _seed_node(
            db,
            project_id,
            node_id=mint(db, Kind.IMPL),
            tier="impl",
            name="FoundationImpl",
            parent_id=top,
            content="line 1\nline 2\nline 3",
        )
        db.commit()
        s = extract_impl_structure(db, project_id)
        assert s.aggregate["impl_count"] == 1
        assert s.aggregate["with_content_count"] == 1
        row = s.per_node[0]
        assert row.metrics["owner_id"] == top
        assert row.metrics["top_level_id"] == top
        assert row.metrics["line_count"] == 3
        assert row.id == impl

    def test_fanin_contributing_impl_count(self, db):
        project_id = _seed_project(db)
        top = _seed_node(
            db,
            project_id,
            node_id=mint(db, Kind.COMP),
            tier="comp",
            name="Domain",
        )
        sub = _seed_node(
            db,
            project_id,
            node_id=mint(db, Kind.COMP),
            tier="comp",
            name="DomainSub",
            parent_id=top,
        )
        _seed_node(
            db,
            project_id,
            node_id=mint(db, Kind.IMPL),
            tier="impl",
            name="SubImpl",
            parent_id=sub,
            content="x",
        )
        _seed_node(
            db,
            project_id,
            node_id=mint(db, Kind.FANIN),
            tier="fanin",
            name="DomainFanIn",
            parent_id=top,
            content="<fanin>...</fanin>",
        )
        db.commit()
        s = extract_fanin_structure(db, project_id)
        assert s.aggregate["fanin_count"] == 1
        assert s.aggregate["with_content_count"] == 1
        row = s.per_node[0]
        assert row.metrics["contributing_impl_count"] == 1
        assert row.metrics["owner_kind"] == "domain"

    def test_references_count(self, db):
        project_id = _seed_project(db)
        _seed_node(
            db,
            project_id,
            node_id=mint(db, Kind.REF),
            tier="ref",
            name="API Spec",
            content="some content",
        )
        _seed_node(
            db,
            project_id,
            node_id=mint(db, Kind.REF),
            tier="ref",
            name="Empty",
        )
        db.commit()
        s = extract_references_structure(db, project_id)
        assert s.aggregate["ref_count"] == 2
        assert s.aggregate["with_content_count"] == 1


class TestGatherDispatch:
    def test_unknown_tier_raises_keyerror(self, db):
        project_id = _seed_project(db)
        db.commit()
        with pytest.raises(KeyError):
            gather_tier_structure_summary(db, project_id, "manifest")


# ── Endpoint smoke ────────────────────────────────────────────────


class TestStructureSummaryEndpoint:
    def test_happy_path_returns_serialized_summary(self, db, engine_and_factory):
        project_id = _seed_project(db)
        _seed_node(
            db,
            project_id,
            node_id=mint(db, Kind.SYSARCH),
            tier="sysarch",
            name="Sysarch",
        )
        _seed_node(
            db,
            project_id,
            node_id=mint(db, Kind.COMP),
            tier="comp",
            name="Domain",
            kind="domain",
        )
        db.commit()

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
            client = TestClient(app)
            resp = client.get(f"/api/projects/{project_id}/tiers/sysarch/structure-summary")
            assert resp.status_code == 200, resp.text
            body = resp.json()
            assert body["tier"] == "sysarch"
            assert body["aggregate"]["top_comp_count"] == 1
            assert body["aggregate"]["domain_count"] == 1
            assert len(body["per_node"]) == 1
            assert body["per_node"][0]["metrics"]["top_comp_count"] == 1
        finally:
            app.dependency_overrides.clear()

    def test_unknown_tier_returns_422(self, db, engine_and_factory):
        # FastAPI's Literal validation rejects unknown tiers at the
        # path level with 422 (validation error), before the handler
        # runs. The 404 path is reachable only if a tier name slips
        # the Literal — guarded by the StructureTierName type.
        project_id = _seed_project(db)
        db.commit()

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
            client = TestClient(app)
            resp = client.get(f"/api/projects/{project_id}/tiers/manifest/structure-summary")
            assert resp.status_code == 422
        finally:
            app.dependency_overrides.clear()
