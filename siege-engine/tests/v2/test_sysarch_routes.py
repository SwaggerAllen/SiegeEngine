"""End-to-end tests for the sysarch HTTP routes.

Same TestClient + in-memory-DB pattern as test_requirements_routes.py.
CLI is mocked so the generation handler produces deterministic
content fed through the real parse-validate loop.
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

import asyncio  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from backend.auth.routes import get_current_user  # noqa: E402
from backend.database import Base, get_db  # noqa: E402
from backend.graph import events as ev  # noqa: E402
from backend.graph.handlers import feature_expansion as fe_handler  # noqa: E402
from backend.graph.handlers.sysarch_generation import (  # noqa: E402
    generate_sysarch,
)
from backend.graph.ids import Kind, mint  # noqa: E402
from backend.graph.reducer import append_event  # noqa: E402
from backend.graph.sysarch import bootstrap_sysarch_node  # noqa: E402
from backend.main import app  # noqa: E402
from backend.models import InputDocument, Project  # noqa: E402
from backend.models.job import Job  # noqa: E402
from backend.models.node import Draft, Node  # noqa: E402


@pytest.fixture()
def engine_and_factory(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    # SQLite ignores FK constraints by default, which means the
    # ``ON DELETE CASCADE`` on edges/fragments pointing at nodes
    # doesn't fire and NodeDeleted would leave orphaned child rows.
    # Production Postgres enforces FKs; turn it on here so the tests
    # match real-world cascade behaviour — the ``/sysarch/reset``
    # route specifically relies on fragments + edges being cleaned up
    # via cascade when their owner node is deleted.
    from sqlalchemy import event as sa_event

    @sa_event.listens_for(engine, "connect")
    def _sqlite_enable_fk(dbapi_conn, _):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    import backend.database as _database_mod
    import backend.graph.handlers.sysarch_generation as _sys_gen
    import backend.graph.handlers.sysarch_mint as _sys_mint

    monkeypatch.setattr(_database_mod, "SessionLocal", factory)
    monkeypatch.setattr(fe_handler, "SessionLocal", factory)
    monkeypatch.setattr(_sys_gen, "SessionLocal", factory)
    monkeypatch.setattr(_sys_mint, "SessionLocal", factory)
    yield engine, factory
    engine.dispose()


@pytest.fixture(autouse=True)
def _fast_cli_retry_backoff(monkeypatch):
    monkeypatch.setattr(
        fe_handler,
        "CLI_RETRY_BACKOFF_SECONDS",
        (0.0,) * (fe_handler.CLI_MAX_TRANSIENT_RETRIES + 1),
    )


@pytest.fixture()
def db(engine_and_factory):
    _, factory = engine_and_factory
    session: Session = factory()
    try:
        yield session
    finally:
        session.close()


def _mint_top_level_resp(session, project_id, name, order):
    resp_id = mint(session, Kind.RESP)
    append_event(
        session,
        project_id,
        ev.NodeCreated(
            node_id=resp_id,
            tier="resp",
            kind="domain",
            parent_id=None,
            name=name,
            display_order=order,
            content=f"{name} intent.",
        ),
    )
    return resp_id


@pytest.fixture()
def project_with_sysarch(db):
    p = Project(
        id=str(uuid.uuid4()),
        name="Test Project",
        git_repo_path="/tmp/test-repo",
    )
    db.add(p)
    # Flush the project row before appending any events. Now that
    # this module enables SQLite FK enforcement (to match Postgres
    # production behaviour for the reset cascade test), the
    # graph_events rows' project_id FK requires the parent row to
    # be visible at INSERT time.
    db.flush()
    db.add(
        InputDocument(
            project_id=p.id,
            name="Project Document",
            content="A task management app.",
            doc_type="project_doc",
        )
    )
    _mint_top_level_resp(db, p.id, "Authentication", 0)
    _mint_top_level_resp(db, p.id, "Billing", 1)
    _mint_top_level_resp(db, p.id, "Foundation", 2)
    bootstrap_sysarch_node(db, p.id)
    db.commit()
    return p


@pytest.fixture()
def project_no_sysarch(db):
    """Project with resps but no sysarch node — exercises lazy bootstrap."""
    p = Project(
        id=str(uuid.uuid4()),
        name="Legacy",
        git_repo_path="/tmp/legacy",
    )
    db.add(p)
    db.flush()  # see project_with_sysarch docstring re: FK enforcement
    _mint_top_level_resp(db, p.id, "X", 0)
    db.commit()
    return p


@pytest.fixture()
def client(db, project_with_sysarch):
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


def _resp_ids(db, project_id):
    return [
        rid
        for (rid,) in db.execute(
            select(Node.id)
            .where(
                Node.project_id == project_id,
                Node.tier == "resp",
                Node.parent_id.is_(None),
            )
            .order_by(Node.display_order)
        ).all()
    ]


def _valid_sysarch(resp_ids: list[str]) -> str:
    auth_id, billing_id, foundation_id = resp_ids
    return (
        "<sysarch>"
        "<techspec>Typical Python + React stack.</techspec>"
        "<components>"
        '<component alias="auth">'
        "<name>Authentication</name><kind>domain</kind>"
        "<role>Identify callers.</role>"
        "<api-intent>authenticate().</api-intent>"
        f'<responsibilities><resp id="{auth_id}"/></responsibilities>'
        "</component>"
        '<component alias="billing">'
        "<name>Billing</name><kind>domain</kind>"
        "<role>Handle payments.</role>"
        "<api-intent>get_billing_state().</api-intent>"
        f'<responsibilities><resp id="{billing_id}"/></responsibilities>'
        "</component>"
        '<component alias="foundation">'
        "<name>Foundation</name><kind>domain</kind>"
        "<role>Project root, shared utilities.</role>"
        "<api-intent>load_settings().</api-intent>"
        f'<responsibilities><resp id="{foundation_id}"/></responsibilities>'
        "<foundation/>"
        "</component>"
        "</components>"
        "<policies></policies>"
        "<dependencies>"
        '<dep from="billing" to="foundation"/>'
        '<dep from="auth" to="foundation"/>'
        "</dependencies>"
        "<domain-parent></domain-parent>"
        "</sysarch>"
    )


def _patch_cli(monkeypatch, output, **kw):
    from backend.cli.manager import GenerationResult

    async def fake(**kwargs):
        return GenerationResult(
            text=output,
            prompt_tokens=kw.get("prompt_tokens", 100),
            completion_tokens=kw.get("completion_tokens", 50),
            model=kw.get("model", "claude-sonnet-4-6"),
        )

    monkeypatch.setattr(fe_handler.cli_manager, "generate_with_usage", fake)


class TestGetSysarch:
    def test_returns_node_state(self, client, project_with_sysarch):
        resp = client.get(f"/api/projects/{project_with_sysarch.id}/sysarch")
        assert resp.status_code == 200
        body = resp.json()
        assert body["node"]["name"] == "System Architecture"
        assert body["node"]["content"] == ""
        assert body["pending_draft"] is None
        assert body["generation_status"] == "idle"

    def test_lazy_bootstraps_missing_sysarch(self, client, project_no_sysarch, db):
        resp = client.get(f"/api/projects/{project_no_sysarch.id}/sysarch")
        assert resp.status_code == 200
        node = db.execute(
            select(Node).where(Node.project_id == project_no_sysarch.id, Node.tier == "sysarch")
        ).scalar_one_or_none()
        assert node is not None
        jobs = db.execute(select(Job).where(Job.job_type == "v2.generate_sysarch")).scalars().all()
        assert any(j.payload.get("project_id") == project_no_sysarch.id for j in jobs)

    def test_unknown_project_is_404(self, client):
        resp = client.get("/api/projects/does-not-exist/sysarch")
        assert resp.status_code == 404


class TestFeedback:
    def test_feedback_enqueues_generate_job(self, client, project_with_sysarch, db):
        resp = client.post(
            f"/api/projects/{project_with_sysarch.id}/sysarch/feedback",
            json={"feedback": "Split billing into subscription + invoicing"},
        )
        assert resp.status_code == 200
        job_id = resp.json()["job_id"]
        job = db.get(Job, job_id)
        assert job is not None
        assert job.job_type == "v2.generate_sysarch"
        assert job.payload["project_id"] == project_with_sysarch.id
        assert job.payload["feedback"] == "Split billing into subscription + invoicing"

    def test_read_only_after_approval(self, client, project_with_sysarch, db):
        node = db.execute(
            select(Node).where(Node.project_id == project_with_sysarch.id, Node.tier == "sysarch")
        ).scalar_one()
        node.content = "<sysarch>already approved</sysarch>"
        db.commit()

        resp = client.post(
            f"/api/projects/{project_with_sysarch.id}/sysarch/feedback",
            json={"feedback": "retry"},
        )
        assert resp.status_code == 409
        assert "read-only after approval" in resp.json()["detail"]


class TestApprove:
    def test_approve_commits_content_and_enqueues_mint(
        self, client, project_with_sysarch, db, monkeypatch
    ):
        draft_xml = _valid_sysarch(_resp_ids(db, project_with_sysarch.id))
        _patch_cli(monkeypatch, draft_xml)
        asyncio.run(generate_sysarch({"project_id": project_with_sysarch.id, "feedback": None}))
        draft = db.execute(
            select(Draft).where(Draft.project_id == project_with_sysarch.id)
        ).scalar_one()

        resp = client.post(
            f"/api/projects/{project_with_sysarch.id}/sysarch/approve",
            json={"draft_id": draft.id},
        )
        assert resp.status_code == 200
        assert resp.json()["node"]["content"] == draft_xml

        jobs = db.execute(select(Job).where(Job.job_type == "v2.mint_sysarch")).scalars().all()
        assert any(j.payload.get("project_id") == project_with_sysarch.id for j in jobs)


class TestDiscard:
    def test_discard_enqueues_new_generation(self, client, project_with_sysarch, db, monkeypatch):
        draft_xml = _valid_sysarch(_resp_ids(db, project_with_sysarch.id))
        _patch_cli(monkeypatch, draft_xml)
        asyncio.run(generate_sysarch({"project_id": project_with_sysarch.id, "feedback": None}))
        draft = db.execute(
            select(Draft).where(Draft.project_id == project_with_sysarch.id)
        ).scalar_one()

        resp = client.post(
            f"/api/projects/{project_with_sysarch.id}/sysarch/discard",
            json={"draft_id": draft.id},
        )
        assert resp.status_code == 200

        db.refresh(draft)
        assert draft.status == "discarded"
        fresh = [
            j
            for j in db.execute(select(Job).where(Job.job_type == "v2.generate_sysarch")).scalars()
            if j.payload.get("project_id") == project_with_sysarch.id
        ]
        assert fresh


class TestReset:
    """The ``/sysarch/reset`` route is the only escape hatch once a
    user has approved a sysarch draft and wants to regenerate
    against a different prompt. It has to cascade deletion
    through the whole downstream projection (comps, policies,
    subreqs, subresps, fragments, edges), discard any pending
    drafts targeting those nodes, cancel any queued downstream
    jobs, clear sysarch ``node.content`` back to None, and
    enqueue a fresh generation. The guard: the sysarch node
    must actually be in approved state — otherwise use the
    pending-draft regen path."""

    def test_reset_requires_approved_state(self, client, project_with_sysarch, db, monkeypatch):
        # Pending draft, no approval — reset should 409.
        draft_xml = _valid_sysarch(_resp_ids(db, project_with_sysarch.id))
        _patch_cli(monkeypatch, draft_xml)
        asyncio.run(generate_sysarch({"project_id": project_with_sysarch.id, "feedback": None}))

        resp = client.post(f"/api/projects/{project_with_sysarch.id}/sysarch/reset")
        assert resp.status_code == 409
        assert "not in approved state" in resp.json()["detail"]

    def test_reset_cascades_approved_state(self, client, project_with_sysarch, db, monkeypatch):
        # Approve a sysarch draft, hand-mint some downstream state
        # (comps + policies + subreqs + a nested resp + a fragment +
        # a pending draft on one of the comps), then reset.
        draft_xml = _valid_sysarch(_resp_ids(db, project_with_sysarch.id))
        _patch_cli(monkeypatch, draft_xml)
        asyncio.run(generate_sysarch({"project_id": project_with_sysarch.id, "feedback": None}))
        draft = db.execute(
            select(Draft).where(Draft.project_id == project_with_sysarch.id)
        ).scalar_one()
        client.post(
            f"/api/projects/{project_with_sysarch.id}/sysarch/approve",
            json={"draft_id": draft.id},
        )

        # Fake the downstream mint state the sysarch_mint + later
        # pipeline tiers would have created. Two comps, one policy,
        # one subreqs node, one nested subresp, one fragment on a
        # comp, one pending draft on a comp.
        from backend.models.node import Fragment

        comp_ids = []
        for i, name in enumerate(["Auth", "Billing"]):
            cid = mint(db, Kind.COMP)
            append_event(
                db,
                project_with_sysarch.id,
                ev.NodeCreated(
                    node_id=cid,
                    tier="comp",
                    kind="domain",
                    parent_id=None,
                    name=name,
                    display_order=i,
                    content="",
                ),
            )
            comp_ids.append(cid)

        policy_id = mint(db, Kind.POLICY)
        append_event(
            db,
            project_with_sysarch.id,
            ev.NodeCreated(
                node_id=policy_id,
                tier="policy",
                kind="domain",
                parent_id=None,
                name="Telemetry",
                display_order=0,
                content="<policy/>",
            ),
        )

        subreqs_id = mint(db, Kind.SUBREQS)
        append_event(
            db,
            project_with_sysarch.id,
            ev.NodeCreated(
                node_id=subreqs_id,
                tier="subreqs",
                kind="domain",
                parent_id=comp_ids[0],
                name="Auth subreqs",
                display_order=0,
                content="",
            ),
        )

        # Nested subresp — tier='resp' but parent_id set to a comp.
        subresp_id = mint(db, Kind.RESP)
        append_event(
            db,
            project_with_sysarch.id,
            ev.NodeCreated(
                node_id=subresp_id,
                tier="resp",
                kind="domain",
                parent_id=comp_ids[0],
                name="Password reset",
                display_order=0,
                content="intent",
            ),
        )

        # A pending draft targeting one of the comp nodes — the
        # reset should discard it so it doesn't dangle with a
        # stale target_id.
        import secrets

        from backend.graph.fragments import FragmentKind, fragment_id

        append_event(
            db,
            project_with_sysarch.id,
            ev.DraftGenerated(
                draft_id=f"draft_{secrets.token_hex(8)}",
                target_type="node",
                target_id=comp_ids[0],
                content="<comparch/>",
                batch_id=f"batch_{uuid.uuid4().hex[:16]}",
            ),
        )

        # A fragment owned by a comp — FK cascade should drop this
        # automatically when we delete the comp.
        frag_id_value = fragment_id(comp_ids[0], FragmentKind.PUBAPI)
        append_event(
            db,
            project_with_sysarch.id,
            ev.FragmentUpdated(
                fragment_id=frag_id_value,
                owner_id=comp_ids[0],
                fragment_kind=FragmentKind.PUBAPI,
                new_content="pub content",
            ),
        )

        # Also queue a downstream job that should be cancelled.
        import backend.pipeline.queue as pq

        pq.enqueue(
            db,
            job_type="v2.generate_subrequirements",
            payload={"project_id": project_with_sysarch.id, "comp_id": comp_ids[0]},
        )

        db.commit()

        # Sanity check: things exist before the reset.
        assert (
            db.execute(
                select(Node).where(Node.project_id == project_with_sysarch.id, Node.tier == "comp")
            )
            .scalars()
            .all()
        )
        assert db.execute(
            select(Fragment).where(
                Fragment.project_id == project_with_sysarch.id,
                Fragment.owner_id == comp_ids[0],
            )
        ).scalar_one_or_none()
        sysarch_node_before = db.execute(
            select(Node).where(Node.project_id == project_with_sysarch.id, Node.tier == "sysarch")
        ).scalar_one()
        assert sysarch_node_before.content  # approved

        # Now reset.
        resp = client.post(f"/api/projects/{project_with_sysarch.id}/sysarch/reset")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["ok"] is True
        # 2 comps + 1 policy + 1 subreqs + 1 nested resp = 5 nodes
        assert body["nodes_deleted"] == 5
        # 1 pending comparch draft on comp_ids[0]
        assert body["drafts_discarded"] == 1
        # 1 queued subrequirements job + however many mint_sysarch /
        # generate_sysarch jobs the approve flow queued. At least 1.
        assert body["jobs_cancelled"] >= 1

        # After reset: sysarch node still exists, content cleared
        # back to empty (column is nullable=False so this is the
        # "not approved" sentinel that has_been_approved checks).
        db.expire_all()
        sysarch_node_after = db.execute(
            select(Node).where(Node.project_id == project_with_sysarch.id, Node.tier == "sysarch")
        ).scalar_one()
        assert sysarch_node_after.content == ""
        assert sysarch_node_after.id == sysarch_node_before.id  # same row, not recreated
        # Confirm the freeze check has flipped off.
        from backend.graph.sysarch import has_been_approved

        assert has_been_approved(db, project_with_sysarch.id) is False

        # Downstream nodes are gone.
        assert (
            not db.execute(
                select(Node).where(Node.project_id == project_with_sysarch.id, Node.tier == "comp")
            )
            .scalars()
            .all()
        )
        assert (
            not db.execute(
                select(Node).where(
                    Node.project_id == project_with_sysarch.id, Node.tier == "policy"
                )
            )
            .scalars()
            .all()
        )
        assert (
            not db.execute(
                select(Node).where(
                    Node.project_id == project_with_sysarch.id, Node.tier == "subreqs"
                )
            )
            .scalars()
            .all()
        )
        # Nested resps are gone, but top-level resps survive.
        surviving_resps = (
            db.execute(
                select(Node).where(Node.project_id == project_with_sysarch.id, Node.tier == "resp")
            )
            .scalars()
            .all()
        )
        assert all(r.parent_id is None for r in surviving_resps)
        assert len(surviving_resps) == 3  # the three top-level resps the fixture seeds

        # Fragment cascaded away via the FK on owner_id.
        assert (
            db.execute(
                select(Fragment).where(
                    Fragment.project_id == project_with_sysarch.id,
                    Fragment.owner_id == comp_ids[0],
                )
            ).scalar_one_or_none()
            is None
        )

        # The pending comparch draft is now discarded.
        comparch_draft = db.execute(
            select(Draft).where(
                Draft.project_id == project_with_sysarch.id,
                Draft.target_type == "node",
                Draft.target_id == comp_ids[0],
            )
        ).scalar_one()
        assert comparch_draft.status == "discarded"

        # A fresh generate_sysarch job is queued post-reset so the
        # UI flips back to the generating spinner.
        fresh_jobs = [
            j
            for j in db.execute(select(Job).where(Job.job_type == "v2.generate_sysarch")).scalars()
            if j.payload.get("project_id") == project_with_sysarch.id and j.status == "queued"
        ]
        assert fresh_jobs, "reset should enqueue a fresh generate_sysarch job"

        # And the previously-queued downstream subreqs job got cancelled.
        subreqs_jobs = (
            db.execute(select(Job).where(Job.job_type == "v2.generate_subrequirements"))
            .scalars()
            .all()
        )
        assert all(j.status == "cancelled" for j in subreqs_jobs)

    def test_reset_on_missing_sysarch_returns_404(self, client, project_no_sysarch):
        resp = client.post(f"/api/projects/{project_no_sysarch.id}/sysarch/reset")
        # Lazy-bootstrap runs on GET; reset doesn't. The node is
        # absent → the route returns either 404 (node missing) or
        # 409 (not approved because no content). Both are
        # acceptable — the invariant is "reset can't silently
        # no-op on a project that has never generated sysarch."
        assert resp.status_code in (404, 409)
