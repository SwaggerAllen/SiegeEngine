"""Tests for backend.graph.handlers.policy_application_local.

Covers: happy path (2 subs + 1 local policy → 2 LLM calls),
no local policies → no-op, no subcomponents → no-op, full
idempotency skip when all already applied, missing payload.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database import Base
from backend.graph import events as ev
from backend.graph.fragments import FragmentKind, fragment_id
from backend.graph.handlers.policy_application_local import (
    ComponentLocalPolicyApplicationError,
    apply_component_local_policies,
)
from backend.graph.handlers.sysarch_mint import _serialize_policy_blob
from backend.graph.ids import Kind, mint
from backend.graph.parsers.validators import Policy
from backend.graph.reducer import append_event
from backend.models import Project
from backend.models.node import Edge, Node


@pytest.fixture(autouse=True)
def _fast_cli_retry_backoff(monkeypatch):
    import backend.graph.handlers.feature_expansion as _fe_handler

    monkeypatch.setattr(
        _fe_handler,
        "CLI_RETRY_BACKOFF_SECONDS",
        (0.0,) * (_fe_handler.CLI_MAX_TRANSIENT_RETRIES + 1),
    )


@pytest.fixture()
def shared_session_factory(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    import backend.database as _database_mod
    import backend.graph.handlers.policy_application_local as _handler_mod

    monkeypatch.setattr(_database_mod, "SessionLocal", factory)
    monkeypatch.setattr(_handler_mod, "SessionLocal", factory)
    yield factory
    engine.dispose()


def _seed_top_resp(session, project_id, name, order):
    rid = mint(session, Kind.RESP)
    append_event(
        session,
        project_id,
        ev.NodeCreated(
            node_id=rid,
            tier="resp",
            kind="domain",
            parent_id=None,
            name=name,
            display_order=order,
            content=f"{name}.",
        ),
    )
    return rid


def _seed_top_comp(session, project_id, name, order, parent_resp_ids):
    cid = mint(session, Kind.COMP)
    append_event(
        session,
        project_id,
        ev.NodeCreated(
            node_id=cid,
            tier="comp",
            kind="domain",
            parent_id=None,
            name=name,
            display_order=order,
            content="",
        ),
    )
    for rid in parent_resp_ids:
        eid = mint(session, Kind.EDGE)
        append_event(
            session,
            project_id,
            ev.EdgeCreated(
                edge_id=eid,
                edge_type="decomposition",
                source_id=rid,
                target_id=cid,
            ),
        )
    return cid


def _seed_sub_comp(session, project_id, parent_comp, name, order, techspec, pubapi):
    cid = mint(session, Kind.COMP)
    append_event(
        session,
        project_id,
        ev.NodeCreated(
            node_id=cid,
            tier="comp",
            kind="domain",
            parent_id=parent_comp,
            name=name,
            display_order=order,
            content="",
        ),
    )
    append_event(
        session,
        project_id,
        ev.FragmentUpdated(
            fragment_id=fragment_id(cid, FragmentKind.TECHSPEC),
            owner_id=cid,
            fragment_kind=FragmentKind.TECHSPEC,
            new_content=techspec,
        ),
    )
    append_event(
        session,
        project_id,
        ev.FragmentUpdated(
            fragment_id=fragment_id(cid, FragmentKind.PUBAPI),
            owner_id=cid,
            fragment_kind=FragmentKind.PUBAPI,
            new_content=pubapi,
        ),
    )
    return cid


def _seed_subresp(session, project_id, parent_comp, name, order):
    sid = mint(session, Kind.RESP)
    append_event(
        session,
        project_id,
        ev.NodeCreated(
            node_id=sid,
            tier="resp",
            kind="domain",
            parent_id=parent_comp,
            name=name,
            display_order=order,
            content=f"{name}.",
        ),
    )
    return sid


def _seed_local_policy(session, project_id, parent_comp, name, required_resp, order):
    pid = mint(session, Kind.POLICY)
    blob = _serialize_policy_blob(
        Policy(
            name=name,
            trigger=f"any {name.lower()} site",
            required_resp_id=required_resp,
            rationale=f"{name} rationale.",
        )
    )
    append_event(
        session,
        project_id,
        ev.NodeCreated(
            node_id=pid,
            tier="policy",
            kind="domain",
            parent_id=parent_comp,
            name=name,
            display_order=order,
            content=blob,
        ),
    )
    return pid


@pytest.fixture()
def seeded(shared_session_factory):
    """Owning comp "billing" with 2 subcomponents + 1 component-local policy."""
    factory = shared_session_factory
    s: Session = factory()
    try:
        project_id = str(uuid.uuid4())
        s.add(Project(id=project_id, name="T", git_repo_path="/tmp/t"))
        s.flush()

        resp_bill = _seed_top_resp(s, project_id, "Billing", 0)
        comp_billing = _seed_top_comp(s, project_id, "BillingService", 0, [resp_bill])

        # Subcomponents
        sub_token = _seed_sub_comp(
            s,
            project_id,
            comp_billing,
            "TokenStore",
            0,
            "Owns tokenization.",
            "tokenize(raw).",
        )
        sub_retry = _seed_sub_comp(
            s,
            project_id,
            comp_billing,
            "RetryEngine",
            1,
            "Schedules retries.",
            "schedule_retry(ctx).",
        )

        # Subresp (used as required in the local policy)
        subresp = _seed_subresp(s, project_id, comp_billing, "Audit", 0)

        # Decomposition edges subresp → sub
        for sub in (sub_token, sub_retry):
            eid = mint(s, Kind.EDGE)
            append_event(
                s,
                project_id,
                ev.EdgeCreated(
                    edge_id=eid,
                    edge_type="decomposition",
                    source_id=subresp,
                    target_id=sub,
                ),
            )

        # One component-local policy owned by billing
        local_policy = _seed_local_policy(s, project_id, comp_billing, "AuditTrail", subresp, 0)

        s.commit()
        yield {
            "project_id": project_id,
            "comp_billing": comp_billing,
            "sub_token": sub_token,
            "sub_retry": sub_retry,
            "subresp": subresp,
            "local_policy": local_policy,
        }
    finally:
        s.close()


def _decisions_xml(applies: list[str], does_not: list[str]) -> str:
    parts = ["<policy-applications>"]
    for pid in applies:
        parts.append(f'<applies policy="{pid}"><rationale>Applies.</rationale></applies>')
    for pid in does_not:
        parts.append(
            f'<does-not-apply policy="{pid}"><rationale>Does not.</rationale></does-not-apply>'
        )
    parts.append("</policy-applications>")
    return "".join(parts)


def _patch_cli_sequence(monkeypatch, values: list[str]):
    import backend.graph.handlers.feature_expansion as _fe_handler
    from backend.cli.manager import GenerationResult

    calls: list[dict] = []
    remaining = list(values)

    async def fake(**kwargs):
        calls.append(kwargs)
        if not remaining:
            raise RuntimeError("CLI mock exhausted")
        text = remaining.pop(0)
        return GenerationResult(
            text=text, prompt_tokens=100, completion_tokens=50, model="claude-sonnet-4-6"
        )

    monkeypatch.setattr(_fe_handler.cli_manager, "generate_with_usage", fake)
    return calls


class TestHappyPath:
    def test_runs_one_llm_call_per_subcomponent(self, shared_session_factory, seeded, monkeypatch):
        # One call for sub_token (applies), one for sub_retry (does not)
        calls = _patch_cli_sequence(
            monkeypatch,
            [
                _decisions_xml(applies=[seeded["local_policy"]], does_not=[]),
                _decisions_xml(applies=[], does_not=[seeded["local_policy"]]),
            ],
        )
        asyncio.run(
            apply_component_local_policies(
                {
                    "project_id": seeded["project_id"],
                    "component_id": seeded["comp_billing"],
                }
            )
        )
        assert len(calls) == 2

        s = shared_session_factory()
        try:
            edges = list(
                s.execute(
                    select(Edge).where(
                        Edge.project_id == seeded["project_id"],
                        Edge.edge_type == "policy_application",
                    )
                ).scalars()
            )
            targets = {e.target_id for e in edges}
            assert targets == {seeded["sub_token"]}
        finally:
            s.close()


class TestNoOps:
    def test_no_local_policies_skips(self, shared_session_factory, seeded, monkeypatch):
        # Delete the local policy so there are no candidates
        s = shared_session_factory()
        try:
            policy = s.get(Node, seeded["local_policy"])
            s.delete(policy)
            s.commit()
        finally:
            s.close()

        calls = _patch_cli_sequence(monkeypatch, ["unused"])
        asyncio.run(
            apply_component_local_policies(
                {
                    "project_id": seeded["project_id"],
                    "component_id": seeded["comp_billing"],
                }
            )
        )
        assert calls == []

    def test_no_subcomponents_skips(self, shared_session_factory, monkeypatch):
        factory = shared_session_factory
        s: Session = factory()
        try:
            project_id = str(uuid.uuid4())
            s.add(Project(id=project_id, name="T2", git_repo_path="/tmp/t2"))
            s.flush()
            resp = _seed_top_resp(s, project_id, "Core", 0)
            comp = _seed_top_comp(s, project_id, "Core", 0, [resp])
            # Add a local policy but no subcomponents
            _seed_local_policy(s, project_id, comp, "Core", resp, 0)
            s.commit()
        finally:
            s.close()

        calls = _patch_cli_sequence(monkeypatch, ["unused"])
        asyncio.run(
            apply_component_local_policies({"project_id": project_id, "component_id": comp})
        )
        assert calls == []

    def test_all_already_applied_skips(self, shared_session_factory, seeded, monkeypatch):
        s = shared_session_factory()
        try:
            for sub in (seeded["sub_token"], seeded["sub_retry"]):
                eid = mint(s, Kind.EDGE)
                append_event(
                    s,
                    seeded["project_id"],
                    ev.EdgeCreated(
                        edge_id=eid,
                        edge_type="policy_application",
                        source_id=seeded["local_policy"],
                        target_id=sub,
                    ),
                )
            s.commit()
        finally:
            s.close()

        calls = _patch_cli_sequence(monkeypatch, ["unused"])
        asyncio.run(
            apply_component_local_policies(
                {
                    "project_id": seeded["project_id"],
                    "component_id": seeded["comp_billing"],
                }
            )
        )
        assert calls == []


class TestFailureModes:
    def test_missing_payload_raises(self, shared_session_factory):
        with pytest.raises(ComponentLocalPolicyApplicationError, match="project_id"):
            asyncio.run(apply_component_local_policies({}))

    def test_unknown_component_raises(self, shared_session_factory, seeded):
        with pytest.raises(ComponentLocalPolicyApplicationError, match="not found"):
            asyncio.run(
                apply_component_local_policies(
                    {
                        "project_id": seeded["project_id"],
                        "component_id": "comp_missing00",
                    }
                )
            )
