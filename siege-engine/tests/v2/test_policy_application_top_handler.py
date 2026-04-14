"""Tests for backend.graph.handlers.policy_application_top.

Covers: happy path (3 candidates, 2 apply, 1 doesn't), empty
candidates, idempotency (already-applied policies excluded),
policy-induced dep edge patching, parse-validate retry on
missing coverage, missing comp errors.
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
from backend.graph.handlers.policy_application_top import (
    PolicyApplicationHandlerError,
    apply_top_level_policies,
)
from backend.graph.handlers.sysarch_mint import _serialize_policy_blob
from backend.graph.ids import Kind, mint
from backend.graph.parsers.validators import Policy
from backend.graph.reducer import append_event
from backend.models import Project
from backend.models.node import Edge


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
    import backend.graph.handlers.policy_application_top as _handler_mod

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
            content=f"{name} intent.",
        ),
    )
    return rid


def _seed_comp(session, project_id, name, order, parent_resp_ids, techspec, pubapi):
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


def _seed_top_policy(session, project_id, name, required_resp_id, order):
    pid = mint(session, Kind.POLICY)
    blob = _serialize_policy_blob(
        Policy(
            name=name,
            trigger=f"any {name.lower()} call",
            required_resp_id=required_resp_id,
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
            parent_id=None,
            name=name,
            display_order=order,
            content=blob,
        ),
    )
    return pid


@pytest.fixture()
def seeded(shared_session_factory):
    """Project with billing + auth + audit components, three
    top-level policies, and a seeded telemetry resp owned by
    audit so the policy-induced dep patching can be tested."""
    factory = shared_session_factory
    s: Session = factory()
    try:
        project_id = str(uuid.uuid4())
        s.add(Project(id=project_id, name="T", git_repo_path="/tmp/t"))
        s.flush()

        resp_bill = _seed_top_resp(s, project_id, "Billing", 0)
        resp_audit = _seed_top_resp(s, project_id, "AuditLogSink", 1)
        resp_auth = _seed_top_resp(s, project_id, "Auth", 2)

        comp_billing = _seed_comp(
            s,
            project_id,
            "BillingService",
            0,
            [resp_bill],
            techspec="Python + PostgreSQL billing service.",
            pubapi="get_billing_state(id); record_payment(id, amount).",
        )
        comp_audit = _seed_comp(
            s,
            project_id,
            "AuditService",
            1,
            [resp_audit],
            techspec="Audit log writer.",
            pubapi="write_audit(actor, action).",
        )
        comp_auth = _seed_comp(
            s,
            project_id,
            "AuthService",
            2,
            [resp_auth],
            techspec="Identity.",
            pubapi="authenticate(creds).",
        )

        # Three candidate policies:
        # - Telemetry requires audit — applies to billing via LLM calls
        # - Rate limiting requires auth — applies to billing
        # - Logging requires audit — applies to billing
        policy_tele = _seed_top_policy(s, project_id, "Telemetry", resp_audit, 0)
        policy_rate = _seed_top_policy(s, project_id, "RateLimit", resp_auth, 1)
        policy_log = _seed_top_policy(s, project_id, "Logging", resp_audit, 2)

        s.commit()
        yield {
            "project_id": project_id,
            "comp_billing": comp_billing,
            "comp_audit": comp_audit,
            "comp_auth": comp_auth,
            "resp_bill": resp_bill,
            "resp_audit": resp_audit,
            "resp_auth": resp_auth,
            "policy_tele": policy_tele,
            "policy_rate": policy_rate,
            "policy_log": policy_log,
        }
    finally:
        s.close()


def _decisions_xml(applies: list[str], does_not: list[str]) -> str:
    parts = ["<policy-applications>"]
    for pid in applies:
        parts.append(
            f'<applies policy="{pid}"><rationale>Applies because reasoning.</rationale></applies>'
        )
    for pid in does_not:
        parts.append(
            f'<does-not-apply policy="{pid}">'
            "<rationale>Does not apply because reasoning.</rationale>"
            "</does-not-apply>"
        )
    parts.append("</policy-applications>")
    return "".join(parts)


def _patch_cli(monkeypatch, output: str):
    import backend.graph.handlers.feature_expansion as _fe_handler
    from backend.cli.manager import GenerationResult

    calls: list[dict] = []

    async def fake(**kwargs):
        calls.append(kwargs)
        return GenerationResult(
            text=output, prompt_tokens=100, completion_tokens=50, model="claude-sonnet-4-6"
        )

    monkeypatch.setattr(_fe_handler.cli_manager, "generate_with_usage", fake)
    return calls


def _patch_cli_sequence(monkeypatch, outputs: list[str]):
    import backend.graph.handlers.feature_expansion as _fe_handler
    from backend.cli.manager import GenerationResult

    calls: list[dict] = []
    remaining = list(outputs)

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
    def test_applies_some_does_not_apply_others(self, shared_session_factory, seeded, monkeypatch):
        # Two apply, one does not
        xml = _decisions_xml(
            applies=[seeded["policy_tele"], seeded["policy_log"]],
            does_not=[seeded["policy_rate"]],
        )
        _patch_cli(monkeypatch, xml)
        asyncio.run(
            apply_top_level_policies(
                {
                    "project_id": seeded["project_id"],
                    "component_id": seeded["comp_billing"],
                }
            )
        )

        s = shared_session_factory()
        try:
            app_edges = list(
                s.execute(
                    select(Edge).where(
                        Edge.project_id == seeded["project_id"],
                        Edge.edge_type == "policy_application",
                        Edge.target_id == seeded["comp_billing"],
                    )
                ).scalars()
            )
            applied_policy_ids = {e.source_id for e in app_edges}
            assert applied_policy_ids == {seeded["policy_tele"], seeded["policy_log"]}
        finally:
            s.close()

    def test_patches_missing_dep_edge(self, shared_session_factory, seeded, monkeypatch):
        # Telemetry requires resp_audit (owned by audit comp).
        # Billing has no dep on audit yet. Applying Telemetry
        # should patch a dep edge from billing → audit.
        xml = _decisions_xml(
            applies=[seeded["policy_tele"]],
            does_not=[seeded["policy_rate"], seeded["policy_log"]],
        )
        _patch_cli(monkeypatch, xml)
        asyncio.run(
            apply_top_level_policies(
                {
                    "project_id": seeded["project_id"],
                    "component_id": seeded["comp_billing"],
                }
            )
        )

        s = shared_session_factory()
        try:
            dep_edges = list(
                s.execute(
                    select(Edge).where(
                        Edge.project_id == seeded["project_id"],
                        Edge.edge_type == "dependency",
                        Edge.source_id == seeded["comp_billing"],
                        Edge.target_id == seeded["comp_audit"],
                    )
                ).scalars()
            )
            assert len(dep_edges) == 1, "expected policy-induced dep patch"
        finally:
            s.close()

    def test_does_not_patch_existing_dep(self, shared_session_factory, seeded, monkeypatch):
        # Pre-seed an existing dep from billing to audit so the
        # patch step finds it and skips.
        s = shared_session_factory()
        try:
            edge_id = mint(s, Kind.EDGE)
            append_event(
                s,
                seeded["project_id"],
                ev.EdgeCreated(
                    edge_id=edge_id,
                    edge_type="dependency",
                    source_id=seeded["comp_billing"],
                    target_id=seeded["comp_audit"],
                ),
            )
            s.commit()
        finally:
            s.close()

        xml = _decisions_xml(
            applies=[seeded["policy_tele"]],
            does_not=[seeded["policy_rate"], seeded["policy_log"]],
        )
        _patch_cli(monkeypatch, xml)
        asyncio.run(
            apply_top_level_policies(
                {
                    "project_id": seeded["project_id"],
                    "component_id": seeded["comp_billing"],
                }
            )
        )

        s = shared_session_factory()
        try:
            dep_edges = list(
                s.execute(
                    select(Edge).where(
                        Edge.project_id == seeded["project_id"],
                        Edge.edge_type == "dependency",
                        Edge.source_id == seeded["comp_billing"],
                        Edge.target_id == seeded["comp_audit"],
                    )
                ).scalars()
            )
            assert len(dep_edges) == 1, "should not have duplicated the existing dep"
        finally:
            s.close()


class TestIdempotency:
    def test_already_applied_excluded_from_candidates(
        self, shared_session_factory, seeded, monkeypatch
    ):
        # Pre-apply Telemetry
        s = shared_session_factory()
        try:
            edge_id = mint(s, Kind.EDGE)
            append_event(
                s,
                seeded["project_id"],
                ev.EdgeCreated(
                    edge_id=edge_id,
                    edge_type="policy_application",
                    source_id=seeded["policy_tele"],
                    target_id=seeded["comp_billing"],
                ),
            )
            s.commit()
        finally:
            s.close()

        # Only 2 remaining candidates — LLM output covers those
        xml = _decisions_xml(
            applies=[seeded["policy_log"]],
            does_not=[seeded["policy_rate"]],
        )
        calls = _patch_cli(monkeypatch, xml)
        asyncio.run(
            apply_top_level_policies(
                {
                    "project_id": seeded["project_id"],
                    "component_id": seeded["comp_billing"],
                }
            )
        )
        prompt = calls[0]["prompt"]
        # Telemetry should NOT appear in the candidate list
        assert seeded["policy_tele"] not in prompt
        assert seeded["policy_log"] in prompt

    def test_no_candidates_skips_llm(self, shared_session_factory, seeded, monkeypatch):
        # Pre-apply everything
        s = shared_session_factory()
        try:
            for pid in (seeded["policy_tele"], seeded["policy_rate"], seeded["policy_log"]):
                edge_id = mint(s, Kind.EDGE)
                append_event(
                    s,
                    seeded["project_id"],
                    ev.EdgeCreated(
                        edge_id=edge_id,
                        edge_type="policy_application",
                        source_id=pid,
                        target_id=seeded["comp_billing"],
                    ),
                )
            s.commit()
        finally:
            s.close()

        calls = _patch_cli(monkeypatch, "unused")
        asyncio.run(
            apply_top_level_policies(
                {
                    "project_id": seeded["project_id"],
                    "component_id": seeded["comp_billing"],
                }
            )
        )
        assert len(calls) == 0, "LLM should not be called when no candidates"


class TestFailureModes:
    def test_unknown_component_raises(self, shared_session_factory, seeded):
        with pytest.raises(PolicyApplicationHandlerError, match="not found"):
            asyncio.run(
                apply_top_level_policies(
                    {
                        "project_id": seeded["project_id"],
                        "component_id": "comp_missing00",
                    }
                )
            )

    def test_missing_payload_raises(self, shared_session_factory):
        with pytest.raises(PolicyApplicationHandlerError, match="project_id"):
            asyncio.run(apply_top_level_policies({}))


class TestParseValidateRetry:
    def test_retry_on_missing_coverage(self, shared_session_factory, seeded, monkeypatch):
        # First attempt misses one candidate
        bad = _decisions_xml(
            applies=[seeded["policy_tele"]],
            does_not=[seeded["policy_rate"]],  # missing policy_log
        )
        good = _decisions_xml(
            applies=[seeded["policy_tele"]],
            does_not=[seeded["policy_rate"], seeded["policy_log"]],
        )
        calls = _patch_cli_sequence(monkeypatch, [bad, good])
        asyncio.run(
            apply_top_level_policies(
                {
                    "project_id": seeded["project_id"],
                    "component_id": seeded["comp_billing"],
                }
            )
        )
        assert len(calls) == 2
        assert "does not cover every candidate" in calls[1]["prompt"]
