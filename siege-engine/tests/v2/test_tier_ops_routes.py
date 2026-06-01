"""Tests for the read-only tier-ops endpoints.

Covers:
- ``GET /tiers/{tier}/info`` returns counts + capability flags.
- The scope-iterator helpers emit (parent, sub) / (owner) tuples in
  topological order (exercised directly, used by both the read paths
  and any consumer that needs deterministic per-tier ordering).

The write surface (reset-all, review-sweep, resume, regen-below-
threshold, exploration-sample, full-corpus, batch resume) was
retired alongside the v3 authoring skills.
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
from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from backend.auth.routes import get_current_user  # noqa: E402
from backend.database import Base, get_db  # noqa: E402
from backend.graph import events as ev  # noqa: E402
from backend.graph.fragments import FragmentKind, fragment_id  # noqa: E402
from backend.graph.ids import Kind, mint  # noqa: E402
from backend.graph.reducer import append_event  # noqa: E402
from backend.graph.sysarch import bootstrap_sysarch_node  # noqa: E402
from backend.main import app  # noqa: E402
from backend.models import Project  # noqa: E402
from backend.models.job import Job  # noqa: E402
from backend.models.node import Node  # noqa: E402


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


def _seed_project_with_two_comps(db: Session) -> dict:
    """Seed a project with sysarch approved + two top-level comps,
    each with approved comparch content and a parent resp.

    Returns ``project_id``, ``comp_ids``, ``sysarch_id``.
    """
    project_id = str(uuid.uuid4())
    db.add(Project(id=project_id, name="T", git_repo_path="/tmp/t"))
    db.flush()

    sysarch_id = bootstrap_sysarch_node(db, project_id)
    # Mark the sysarch node as approved by writing content to it.
    append_event(
        db,
        project_id,
        ev.NodeContentUpdated(node_id=sysarch_id, new_content="<sysarch>seeded</sysarch>"),
    )

    comp_ids: list[str] = []
    for idx, name in enumerate(["Billing", "Invoicing"]):
        parent_id = mint(db, Kind.RESP)
        append_event(
            db,
            project_id,
            ev.NodeCreated(
                node_id=parent_id,
                tier="resp",
                kind="domain",
                parent_id=None,
                name=f"{name} Resp",
                display_order=idx,
                content=name,
            ),
        )
        comp_id = mint(db, Kind.COMP)
        append_event(
            db,
            project_id,
            ev.NodeCreated(
                node_id=comp_id,
                tier="comp",
                kind="domain",
                parent_id=None,
                name=name,
                display_order=idx,
                content="",
            ),
        )
        for kind, content in (
            (FragmentKind.TECHSPEC, f"{name} role"),
            (FragmentKind.PUBAPI, f"{name} api"),
        ):
            append_event(
                db,
                project_id,
                ev.FragmentUpdated(
                    fragment_id=fragment_id(comp_id, kind),
                    owner_id=comp_id,
                    fragment_kind=kind,
                    new_content=content,
                ),
            )
        edge_id = mint(db, Kind.EDGE)
        append_event(
            db,
            project_id,
            ev.EdgeCreated(
                edge_id=edge_id,
                edge_type="decomposition",
                source_id=parent_id,
                target_id=comp_id,
            ),
        )
        # Approve comparch content directly on the comp_* node so
        # reset-all has something to act on.
        append_event(
            db,
            project_id,
            ev.NodeContentUpdated(
                node_id=comp_id,
                new_content=f"<comparch>{name}</comparch>",
            ),
        )
        comp_ids.append(comp_id)

    db.commit()
    return {"project_id": project_id, "comp_ids": comp_ids, "sysarch_id": sysarch_id}


@pytest.fixture()
def seeded(db):
    return _seed_project_with_two_comps(db)


@pytest.fixture()
def client(db, seeded):
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


# ── /tiers/{tier}/info ─────────────────────────────────────────────


class TestTierInfo:
    def test_singleton_sysarch_reports_one_node(self, client, seeded):
        r = client.get(f"/api/projects/{seeded['project_id']}/tiers/sysarch/info")
        assert r.status_code == 200
        body = r.json()
        assert body["tier"] == "sysarch"
        assert body["tier_name"] == "System architecture"
        assert body["node_count"] == 1
        assert body["nodes_with_content"] == 1
        assert body["supports_reset"] is True
        assert body["supports_review"] is True

    def test_per_comp_comparch_reports_two_nodes(self, client, seeded):
        r = client.get(f"/api/projects/{seeded['project_id']}/tiers/comparch/info")
        assert r.status_code == 200
        body = r.json()
        assert body["node_count"] == 2
        assert body["nodes_with_content"] == 2
        # Approved content counts as reviewable.
        assert body["reviewable_count"] == 2

    def test_reviewable_count_includes_pending_drafts(self, client, db, seeded):
        """A scope with only a pending draft (no approved content)
        is still reviewable — bootstrap_retry_review accepts the
        pending draft as the review target."""
        from backend.models.node import Draft

        # Find the two seeded comps and clear their content so they're
        # back in the "pending draft" state — only the draft on one of
        # them carries a pending row.
        comps = (
            db.execute(
                select(Node).where(
                    Node.project_id == seeded["project_id"],
                    Node.tier == "comp",
                    Node.parent_id.is_(None),
                )
            )
            .scalars()
            .all()
        )
        for comp in comps:
            comp.content = ""
        # Add a pending draft on the first comp; leave the second
        # with neither content nor draft.
        db.add(
            Draft(
                id=f"draft_{uuid.uuid4().hex[:8]}",
                project_id=seeded["project_id"],
                target_type="node",
                target_id=comps[0].id,
                content="<comparch>regen wip</comparch>",
                status="pending",
                batch_id=f"batch_{uuid.uuid4().hex[:8]}",
            )
        )
        db.commit()

        r = client.get(f"/api/projects/{seeded['project_id']}/tiers/comparch/info")
        assert r.status_code == 200
        body = r.json()
        assert body["nodes_with_content"] == 0
        # Only the comp with a pending draft is reviewable.
        assert body["reviewable_count"] == 1

    def test_avg_generation_seconds_is_null_with_no_completed_jobs(self, client, seeded):
        r = client.get(f"/api/projects/{seeded['project_id']}/tiers/comparch/info")
        body = r.json()
        assert body["avg_generation_seconds"] is None
        assert body["generation_sample_size"] == 0

    def test_avg_generation_seconds_means_completed_run_durations(self, client, db, seeded):
        from datetime import datetime, timedelta

        # Two completed comparch generations, ran 10s and 20s.
        # Average should be 15.
        base = datetime(2026, 4, 29, 12, 0, 0)
        for delay_seconds, comp_id in zip([10, 20], seeded["comp_ids"]):
            db.add(
                Job(
                    job_type="v2.generate_comparch",
                    status="completed",
                    payload={"project_id": seeded["project_id"], "component_id": comp_id},
                    locked_at=base,
                    completed_at=base + timedelta(seconds=delay_seconds),
                )
            )
        # A completed generation for a DIFFERENT project — must not
        # leak into this project's average.
        db.add(
            Job(
                job_type="v2.generate_comparch",
                status="completed",
                payload={"project_id": str(uuid.uuid4()), "component_id": "comp_other"},
                locked_at=base,
                completed_at=base + timedelta(seconds=99999),
            )
        )
        # A still-running generation for THIS project — must be
        # excluded (status != completed).
        db.add(
            Job(
                job_type="v2.generate_comparch",
                status="running",
                payload={"project_id": seeded["project_id"], "component_id": "comp_x"},
                locked_at=base,
                completed_at=None,
            )
        )
        db.commit()

        r = client.get(f"/api/projects/{seeded['project_id']}/tiers/comparch/info")
        body = r.json()
        assert body["generation_sample_size"] == 2
        assert body["avg_generation_seconds"] == 15.0

    def test_unknown_tier_404s(self, client, seeded):
        r = client.get(f"/api/projects/{seeded['project_id']}/tiers/bogus/info")
        # FastAPI rejects literal-mismatch with 422 before our handler.
        assert r.status_code in (404, 422)

    def test_unknown_project_404s(self, client):
        r = client.get(f"/api/projects/{uuid.uuid4()}/tiers/sysarch/info")
        assert r.status_code == 404


class TestScopeIteratorTopoOrder:
    """The tier-ops scope iterators emit (parent, sub) / (owner) tuples
    in topological order so enqueue order matches dispatch order. These
    tests exercise the helpers directly with a fixture that has a real
    dep + subcomp + impl shape — the broader route tests use a flatter
    fixture without sibling deps.
    """

    def _seed_topo_fixture(self, db: Session) -> dict:
        """Project: foundation comp + app comp (app→foundation dep).
        Each top-level has two subs with a sibling dep among them.
        Foundation comp + one sub of each top-level have an impl child.
        """
        project_id = str(uuid.uuid4())
        db.add(Project(id=project_id, name="T", git_repo_path="/tmp/t"))
        db.flush()

        def _new_comp(name: str, parent_id: str | None, order: int) -> str:
            cid = mint(db, Kind.COMP)
            append_event(
                db,
                project_id,
                ev.NodeCreated(
                    node_id=cid,
                    tier="comp",
                    kind="domain",
                    parent_id=parent_id,
                    name=name,
                    display_order=order,
                    content="",
                ),
            )
            return cid

        def _new_dep(src: str, tgt: str) -> None:
            eid = mint(db, Kind.EDGE)
            append_event(
                db,
                project_id,
                ev.EdgeCreated(edge_id=eid, edge_type="dependency", source_id=src, target_id=tgt),
            )

        # Top-level: app depends on foundation. Foundation should
        # sort first even though display_order puts app first.
        comp_app = _new_comp("App", None, 0)
        comp_foundation = _new_comp("Foundation", None, 1)
        _new_dep(comp_app, comp_foundation)

        # App's subs: a_left depends on a_right. a_right should
        # sort first within app.
        sub_a_left = _new_comp("a_left", comp_app, 0)
        sub_a_right = _new_comp("a_right", comp_app, 1)
        _new_dep(sub_a_left, sub_a_right)

        # Foundation's subs: f_first sorts by display_order alone
        # (no sibling deps).
        sub_f_first = _new_comp("f_first", comp_foundation, 0)
        sub_f_second = _new_comp("f_second", comp_foundation, 1)

        # Impls: foundation directly, plus one sub under each top-level.
        for owner in (comp_foundation, sub_a_right, sub_f_first):
            iid = mint(db, Kind.IMPL)
            append_event(
                db,
                project_id,
                ev.NodeCreated(
                    node_id=iid,
                    tier="impl",
                    kind="domain",
                    parent_id=owner,
                    name=f"impl_{owner}",
                    display_order=0,
                    content="",
                ),
            )

        db.commit()
        return {
            "project_id": project_id,
            "comp_app": comp_app,
            "comp_foundation": comp_foundation,
            "sub_a_left": sub_a_left,
            "sub_a_right": sub_a_right,
            "sub_f_first": sub_f_first,
            "sub_f_second": sub_f_second,
        }

    def test_top_level_comp_scope_emits_topo_order(self, db):
        from backend.graph.tier_ops_routes import _top_level_comp_scope

        s = self._seed_topo_fixture(db)
        scopes = _top_level_comp_scope(db, s["project_id"])
        # Foundation first (app depends on it), app second.
        assert scopes == [(s["comp_foundation"],), (s["comp_app"],)]

    def test_subcomp_scope_emits_parent_topo_then_sub_topo(self, db):
        from backend.graph.tier_ops_routes import _subcomp_scope

        s = self._seed_topo_fixture(db)
        scopes = _subcomp_scope(db, s["project_id"])
        # Foundation's subs (display_order ascending — no deps) before
        # app's subs (a_right before a_left because a_left depends on
        # a_right). Scope tuples are 1-element ``(sub_id,)`` so the
        # per-node helpers' ``get_node`` signature matches the
        # ``_get_sub_node(db, project_id, sub_id)`` shape.
        assert scopes == [
            (s["sub_f_first"],),
            (s["sub_f_second"],),
            (s["sub_a_right"],),
            (s["sub_a_left"],),
        ]

    def test_impl_scope_walks_owners_in_combined_topo_order(self, db):
        from backend.graph.tier_ops_routes import _impl_scope

        s = self._seed_topo_fixture(db)
        scopes = _impl_scope(db, s["project_id"])
        # Foundation impl runs before its subcomps; foundation subtree
        # runs before app subtree because app depends on foundation.
        # sub_f_first has impl, sub_f_second does not, sub_a_right has
        # impl, sub_a_left does not.
        assert scopes == [
            (s["comp_foundation"],),
            (s["sub_f_first"],),
            (s["sub_a_right"],),
        ]
