"""End-to-end tests for the subreqs HTTP routes.

Same TestClient + in-memory-DB pattern as test_sysarch_routes.py,
with per-component scoping on the URL. Fixtures seed a project
with a top-level comp_* + its parent resps + a bootstrapped
subreqs_* node ready for draft flow tests.
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
from backend.graph.fragments import FragmentKind, fragment_id  # noqa: E402
from backend.graph.handlers import feature_expansion as fe_handler  # noqa: E402
from backend.graph.handlers.subreqs_generation import (  # noqa: E402
    generate_subreqs,
)
from backend.graph.ids import Kind, mint  # noqa: E402
from backend.graph.reducer import append_event  # noqa: E402
from backend.graph.subrequirements import bootstrap_subreqs_node  # noqa: E402
from backend.main import app  # noqa: E402
from backend.models import Project  # noqa: E402
from backend.models.job import Job  # noqa: E402
from backend.models.node import Draft, Node  # noqa: E402


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
    import backend.graph.handlers.subreqs_generation as _gen_mod
    import backend.graph.handlers.subreqs_mint as _mint_mod

    monkeypatch.setattr(_database_mod, "SessionLocal", factory)
    monkeypatch.setattr(fe_handler, "SessionLocal", factory)
    monkeypatch.setattr(_gen_mod, "SessionLocal", factory)
    monkeypatch.setattr(_mint_mod, "SessionLocal", factory)
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


def _seed_project_with_component(db: Session) -> dict:
    """Seed a project + 2 parent resps + 1 top-level component
    with both resps assigned + bootstrapped subreqs node.

    Returns dict with ``project_id``, ``comp_id``, ``parent_ids``.
    """
    project_id = str(uuid.uuid4())
    db.add(Project(id=project_id, name="T", git_repo_path="/tmp/t"))
    db.flush()

    parent_a = mint(db, Kind.RESP)
    append_event(
        db,
        project_id,
        ev.NodeCreated(
            node_id=parent_a,
            tier="resp",
            kind="domain",
            parent_id=None,
            name="Payment Collection",
            display_order=0,
            content="Handle payment collection.",
        ),
    )
    parent_b = mint(db, Kind.RESP)
    append_event(
        db,
        project_id,
        ev.NodeCreated(
            node_id=parent_b,
            tier="resp",
            kind="domain",
            parent_id=None,
            name="Invoicing",
            display_order=1,
            content="Send invoices.",
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
            name="Billing Service",
            display_order=0,
            content="",
        ),
    )
    append_event(
        db,
        project_id,
        ev.FragmentUpdated(
            fragment_id=fragment_id(comp_id, FragmentKind.TECHSPEC),
            owner_id=comp_id,
            fragment_kind=FragmentKind.TECHSPEC,
            new_content="Handle payments and invoicing.",
        ),
    )
    append_event(
        db,
        project_id,
        ev.FragmentUpdated(
            fragment_id=fragment_id(comp_id, FragmentKind.PUBAPI),
            owner_id=comp_id,
            fragment_kind=FragmentKind.PUBAPI,
            new_content="get_billing_state(id); record_payment(id, amount).",
        ),
    )
    for parent_id in (parent_a, parent_b):
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

    bootstrap_subreqs_node(db, project_id, comp_id)
    db.commit()
    return {"project_id": project_id, "comp_id": comp_id, "parent_ids": [parent_a, parent_b]}


@pytest.fixture()
def seeded(db):
    return _seed_project_with_component(db)


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


def _derived(*ids: str) -> str:
    return "<derived-from>" + "".join(f'<resp id="{rid}"/>' for rid in ids) + "</derived-from>"


def _valid_subreqs(parent_ids: list[str]) -> str:
    # The routes fixture seeds no features, so the in-scope feat
    # set is empty and atomic <feats/> blocks satisfy the
    # feat-coverage check vacuously.
    return (
        "<introduction>Two subresps cover assigned parents.</introduction>"
        "<subrequirements>"
        "<subresponsibility>"
        "<name>Tokenization</name>"
        "<feats/>" + _derived(parent_ids[0]) + "</subresponsibility>"
        "<subresponsibility>"
        "<name>Delivery</name>"
        "<feats/>" + _derived(parent_ids[1]) + "</subresponsibility>"
        "</subrequirements>"
    )


def _patch_cli(monkeypatch, output: str):
    from backend.cli.manager import GenerationResult

    async def fake(**kwargs):
        return GenerationResult(
            text=output, prompt_tokens=100, completion_tokens=50, model="claude-sonnet-4-6"
        )

    monkeypatch.setattr(fe_handler.cli_manager, "generate_with_usage", fake)


class TestGetSubreqs:
    def test_returns_node_state(self, client, seeded):
        resp = client.get(
            f"/api/projects/{seeded['project_id']}/components/{seeded['comp_id']}/subrequirements"
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["node"]["name"] == "Subrequirements"
        assert body["node"]["content"] == ""
        assert body["pending_draft"] is None

    def test_unknown_component_is_404(self, client, seeded):
        resp = client.get(
            f"/api/projects/{seeded['project_id']}/components/comp_nonexist/subrequirements"
        )
        assert resp.status_code == 404

    def test_subcomponent_is_404(self, client, seeded, db):
        # Create a subcomponent (comp_* with parent_id = comp_id)
        sub_id = mint(db, Kind.COMP)
        append_event(
            db,
            seeded["project_id"],
            ev.NodeCreated(
                node_id=sub_id,
                tier="comp",
                kind="domain",
                parent_id=seeded["comp_id"],
                name="SubThing",
                display_order=0,
                content="",
            ),
        )
        db.commit()

        resp = client.get(
            f"/api/projects/{seeded['project_id']}/components/{sub_id}/subrequirements"
        )
        assert resp.status_code == 404
        assert "top-level" in resp.json()["detail"]

    def test_lazy_bootstraps_missing_subreqs(self, client, seeded, db):
        # Remove the pre-seeded subreqs node
        node = db.execute(
            select(Node).where(
                Node.project_id == seeded["project_id"],
                Node.tier == "subreqs",
                Node.parent_id == seeded["comp_id"],
            )
        ).scalar_one()
        db.delete(node)
        db.commit()

        resp = client.get(
            f"/api/projects/{seeded['project_id']}/components/{seeded['comp_id']}/subrequirements"
        )
        assert resp.status_code == 200

        # Bootstrap happened
        after = db.execute(
            select(Node).where(
                Node.project_id == seeded["project_id"],
                Node.tier == "subreqs",
                Node.parent_id == seeded["comp_id"],
            )
        ).scalar_one_or_none()
        assert after is not None

        # Generation job enqueued
        jobs = (
            db.execute(select(Job).where(Job.job_type == "v2.generate_subrequirements"))
            .scalars()
            .all()
        )
        assert any(
            j.payload.get("project_id") == seeded["project_id"]
            and j.payload.get("component_id") == seeded["comp_id"]
            for j in jobs
        )


class TestFeedback:
    def test_enqueues_generation_job(self, client, seeded, db):
        resp = client.post(
            f"/api/projects/{seeded['project_id']}/components/{seeded['comp_id']}/subrequirements/feedback",
            json={"feedback": "Add backoff"},
        )
        assert resp.status_code == 200
        job_id = resp.json()["job_id"]
        job = db.get(Job, job_id)
        assert job is not None
        assert job.job_type == "v2.generate_subrequirements"
        assert job.payload["component_id"] == seeded["comp_id"]
        assert job.payload["feedback"] == "Add backoff"

    def test_read_only_after_approval(self, client, seeded, db):
        node = db.execute(
            select(Node).where(
                Node.project_id == seeded["project_id"],
                Node.tier == "subreqs",
                Node.parent_id == seeded["comp_id"],
            )
        ).scalar_one()
        node.content = "<subrequirements>approved</subrequirements>"
        db.commit()

        resp = client.post(
            f"/api/projects/{seeded['project_id']}/components/{seeded['comp_id']}/subrequirements/feedback",
            json={"feedback": "retry"},
        )
        assert resp.status_code == 409
        assert "read-only" in resp.json()["detail"]


class TestApprove:
    def test_approve_enqueues_mint(self, client, seeded, db, monkeypatch):
        draft_xml = _valid_subreqs(seeded["parent_ids"])
        _patch_cli(monkeypatch, draft_xml)
        asyncio.run(
            generate_subreqs(
                {
                    "project_id": seeded["project_id"],
                    "component_id": seeded["comp_id"],
                    "feedback": None,
                }
            )
        )
        draft = db.execute(
            select(Draft).where(Draft.project_id == seeded["project_id"])
        ).scalar_one()

        resp = client.post(
            f"/api/projects/{seeded['project_id']}/components/{seeded['comp_id']}/subrequirements/approve",
            json={"draft_id": draft.id},
        )
        assert resp.status_code == 200
        assert resp.json()["node"]["content"] == draft_xml

        mint_jobs = (
            db.execute(select(Job).where(Job.job_type == "v2.mint_subrequirements")).scalars().all()
        )
        assert any(j.payload.get("component_id") == seeded["comp_id"] for j in mint_jobs)


class TestDiscard:
    def test_discard_enqueues_new_generation(self, client, seeded, db, monkeypatch):
        draft_xml = _valid_subreqs(seeded["parent_ids"])
        _patch_cli(monkeypatch, draft_xml)
        asyncio.run(
            generate_subreqs(
                {
                    "project_id": seeded["project_id"],
                    "component_id": seeded["comp_id"],
                    "feedback": None,
                }
            )
        )
        draft = db.execute(
            select(Draft).where(Draft.project_id == seeded["project_id"])
        ).scalar_one()

        resp = client.post(
            f"/api/projects/{seeded['project_id']}/components/{seeded['comp_id']}/subrequirements/discard",
            json={"draft_id": draft.id},
        )
        assert resp.status_code == 200
        db.refresh(draft)
        assert draft.status == "discarded"


class TestReset:
    """Destructive reset for the per-component subreqs tier.

    Cascades through to subresps + all comparch-minted state
    (subcomponents, local policies, impl, fanin) under the same
    top-level comp. Clears the subreqs_* node's content, clears
    the comp_*'s own content (which holds comparch XML), and
    re-enqueues ``v2.generate_subrequirements`` for a fresh run.
    """

    def test_reset_requires_approved_state(self, client, seeded):
        resp = client.post(
            f"/api/projects/{seeded['project_id']}/components/{seeded['comp_id']}/subrequirements/reset"
        )
        assert resp.status_code == 409

    def test_reset_deletes_cascaded_subresps_and_re_enqueues(self, client, seeded, db):
        # Manually approve the subreqs node: push non-empty content.
        subreqs_node = db.execute(
            select(Node).where(
                Node.project_id == seeded["project_id"],
                Node.tier == "subreqs",
                Node.parent_id == seeded["comp_id"],
            )
        ).scalar_one()
        subreqs_node.content = "<subrequirements></subrequirements>"
        # Also mint a subresp parented to the comp to verify the
        # reset cascade picks it up.
        subresp_id = mint(db, Kind.RESP)
        append_event(
            db,
            seeded["project_id"],
            ev.NodeCreated(
                node_id=subresp_id,
                tier="resp",
                kind="domain",
                parent_id=seeded["comp_id"],
                name="Minted subresp",
                display_order=0,
                content="Subresp body.",
            ),
        )
        db.commit()

        resp = client.post(
            f"/api/projects/{seeded['project_id']}/components/{seeded['comp_id']}/subrequirements/reset"
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["ok"] is True
        assert body["nodes_deleted"] >= 1

        # Subresp is gone.
        assert db.get(Node, subresp_id) is None
        # Subreqs node content cleared.
        db.refresh(subreqs_node)
        assert subreqs_node.content == ""

        # A fresh generate_subrequirements job enqueues for this comp.
        fresh = [
            j
            for j in db.execute(
                select(Job).where(Job.job_type == "v2.generate_subrequirements")
            ).scalars()
            if (j.payload or {}).get("project_id") == seeded["project_id"]
            and (j.payload or {}).get("component_id") == seeded["comp_id"]
            and j.status in ("queued", "running")
        ]
        assert len(fresh) >= 1
