"""End-to-end integration test for the v2 bootstrap pipeline.

Drives a single project through the entire bootstrap chain —
``expansion → features → requirements → sysarch → subreqs →
comparch → policy_application → subcomparch`` — by alternating
real worker-loop ticks with simulated user-approval steps.

The only thing mocked is ``cli_manager.generate_with_usage``.
Every other piece — the pipeline queue, each handler, the
reducer, the projection store, the fan-out enqueue hooks between
handlers — runs exactly as in production. If a fan-out hook
silently breaks (e.g. a new stage forgets to enqueue the next
one), this test stalls at the offending phase and the assertion
at the end reports what was and wasn't minted.

The LLM stub dispatches on the handler's ``SYSTEM_PROMPT``
constant (matched by identity) and builds deterministic valid
XML for each phase, querying the live DB for referenced IDs so
every response references real ``feat_`` / ``resp_`` / ``comp_``
nodes rather than placeholders.

See ``docs/architecture/v2-roadmap.md`` Phase 5 for the chain
shape and ``backend.graph.handlers._bootstrap_generation`` for
the retry loop each generation handler plugs into.
"""

from __future__ import annotations

import asyncio
import os
import re
import uuid

import pytest

os.environ.setdefault("SIEGE_DISABLE_WORKER_LOOP", "1")

try:
    import cryptography.hazmat.bindings._rust  # noqa: F401
except BaseException as _exc:  # pragma: no cover
    pytest.skip(
        f"cryptography/cffi environmental issue: {_exc!r}",
        allow_module_level=True,
    )

from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

import backend.graph  # noqa: E402,F401 — triggers handler registration
from backend.cli.manager import GenerationResult  # noqa: E402
from backend.database import Base  # noqa: E402
from backend.graph import events as ev  # noqa: E402
from backend.graph.expansion import bootstrap_expansion_node  # noqa: E402
from backend.graph.prompts import comparch as _p_comparch  # noqa: E402
from backend.graph.prompts import feature_expansion as _p_features  # noqa: E402
from backend.graph.prompts import policy_application as _p_policy  # noqa: E402
from backend.graph.prompts import requirements as _p_reqs  # noqa: E402
from backend.graph.prompts import subcomparch as _p_subcomparch  # noqa: E402
from backend.graph.prompts import subrequirements as _p_subreqs  # noqa: E402
from backend.graph.prompts import sysarch as _p_sysarch  # noqa: E402
from backend.graph.reducer import append_event  # noqa: E402
from backend.models import InputDocument, Project  # noqa: E402
from backend.models.job import Job  # noqa: E402
from backend.models.node import Draft, Edge, Fragment, Node  # noqa: E402

# ── SessionLocal patching ─────────────────────────────────────────────
#
# Every handler and the pipeline queue import ``SessionLocal`` at
# module load, so the in-memory engine has to be injected into each
# importing module explicitly. The list below is the complete set of
# modules that bind ``SessionLocal`` as a module-level name — if a
# new handler is added, add its module here so the chain test keeps
# exercising it.
_MODULES_WITH_SESSION_LOCAL = (
    "backend.database",
    "backend.pipeline.queue",
    "backend.graph.handlers.feature_expansion",
    "backend.graph.handlers.feature_mint",
    "backend.graph.handlers.requirements_generation",
    "backend.graph.handlers.requirements_mint",
    "backend.graph.handlers.sysarch_generation",
    "backend.graph.handlers.sysarch_mint",
    "backend.graph.handlers.subreqs_generation",
    "backend.graph.handlers.subreqs_mint",
    "backend.graph.handlers.comparch_generation",
    "backend.graph.handlers.comparch_mint",
    "backend.graph.handlers.policy_application_top",
    "backend.graph.handlers.policy_application_local",
    "backend.graph.handlers.subcomparch_generation",
    "backend.graph.handlers.subcomparch_mint",
)


@pytest.fixture()
def shared_session_factory(monkeypatch):
    """Shared in-memory engine patched into every handler module."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    import importlib

    for mod_path in _MODULES_WITH_SESSION_LOCAL:
        module = importlib.import_module(mod_path)
        monkeypatch.setattr(module, "SessionLocal", factory)

    yield factory
    engine.dispose()


@pytest.fixture(autouse=True)
def _fast_cli_retry_backoff(monkeypatch):
    """Zero the transient-CLI retry backoff so any retry path runs instantly."""
    import backend.graph.handlers.feature_expansion as _fe_handler

    monkeypatch.setattr(
        _fe_handler,
        "CLI_RETRY_BACKOFF_SECONDS",
        (0.0,) * (_fe_handler.CLI_MAX_TRANSIENT_RETRIES + 1),
    )


# ── Stub XML builders ─────────────────────────────────────────────────
#
# Each phase's builder returns a structurally valid response for
# the validator it will be fed through. Builders take the live DB
# session and the rendered user prompt so they can echo real IDs
# back rather than placeholders. Called from the dispatch stub
# during a generation handler's ``cli_manager.generate_with_usage``
# invocation.


_RESP_ID_RE = re.compile(r"resp_[A-Za-z0-9]+")
_FEAT_ID_RE = re.compile(r"feat_[A-Za-z0-9]+")


def _features_xml() -> str:
    return (
        "<features>"
        "<feature><name>Billing</name><intent>Users pay for plans.</intent></feature>"
        "<feature><name>Auth</name><intent>Users sign in.</intent></feature>"
        "</features>"
        "<vocabulary>"
        '<term name="boulder" scope="project">'
        "<vocab-entry>"
        "<definition>A unit of structured work carrying its own processing sub-DAG.</definition>"
        "<disambiguation>Not a leaf node in the decomposition graph.</disambiguation>"
        "</vocab-entry>"
        "</term>"
        '<term name="tranche" scope="feature" feature-name="Billing">'
        "<vocab-entry>"
        "<definition>A time-bounded batch of invoices processed in one "
        "settlement cycle.</definition>"
        "</vocab-entry>"
        "</term>"
        "</vocabulary>"
    )


def _requirements_xml(session, project_id: str) -> str:
    feat_ids = [
        row[0]
        for row in session.execute(
            select(Node.id)
            .where(Node.project_id == project_id, Node.tier == "feat")
            .order_by(Node.display_order, Node.id)
        )
    ]
    covers = "<covers>" + "".join(f'<feat id="{fid}"/>' for fid in feat_ids) + "</covers>"
    entries = [
        ("Authentication", "Identify callers and make them available downstream."),
        ("BillingDomain", "Handle payments and subscription state."),
        ("Foundation", "Own project root, build config, shared utilities."),
    ]
    inner = "".join(
        f"<responsibility><name>{name}</name><intent>{intent}</intent>{covers}</responsibility>"
        for name, intent in entries
    )
    return f"<requirements>{inner}</requirements>"


def _sysarch_xml(session, project_id: str) -> str:
    resps = list(
        session.execute(
            select(Node)
            .where(
                Node.project_id == project_id,
                Node.tier == "resp",
                Node.parent_id.is_(None),
            )
            .order_by(Node.display_order, Node.id)
        ).scalars()
    )
    components: list[str] = []
    for i, r in enumerate(resps):
        alias = f"comp{i}"
        is_foundation = i == len(resps) - 1
        foundation_tag = "<foundation/>" if is_foundation else ""
        components.append(
            f'<component alias="{alias}">'
            f"<name>{r.name}Service</name>"
            f"<kind>domain</kind>"
            f"<role>Own the {r.name} subsystem.</role>"
            f"<api-intent>public API for {r.name}</api-intent>"
            f'<responsibilities><resp id="{r.id}"/></responsibilities>'
            f"{foundation_tag}"
            f"</component>"
        )
    foundation_alias = f"comp{len(resps) - 1}"
    deps = "".join(f'<dep from="comp{i}" to="{foundation_alias}"/>' for i in range(len(resps) - 1))
    return (
        "<sysarch>"
        "<techspec>Python + FastAPI + PostgreSQL event-sourced stack.</techspec>"
        f"<components>{''.join(components)}</components>"
        "<policies></policies>"
        f"<dependencies>{deps}</dependencies>"
        "<domain-parent></domain-parent>"
        "</sysarch>"
    )


def _subrequirements_xml(prompt: str) -> str:
    # Parent resps are rendered into the prompt with their IDs;
    # grab them straight from the rendered text so we don't need
    # to figure out which component this gen is targeting from
    # the DB side — the handler already did that work.
    parent_resp_ids = _unique_in_order(_RESP_ID_RE.findall(prompt))
    if not parent_resp_ids:
        raise AssertionError(
            "subrequirements stub: no resp_* IDs in rendered prompt — "
            "handler changed its prompt shape?"
        )
    # Emit two subresps, each derived from all parent resps, so
    # the per-resp coverage check passes regardless of the
    # parent count.
    derived = (
        "<derived-from>"
        + "".join(f'<resp id="{rid}"/>' for rid in parent_resp_ids)
        + "</derived-from>"
    )
    return (
        "<subrequirements>"
        f"<subresponsibility><name>CoreHandling</name>"
        f"<intent>Primary subresp for this comp.</intent>{derived}"
        f"</subresponsibility>"
        f"<subresponsibility><name>SupportHandling</name>"
        f"<intent>Secondary subresp for this comp.</intent>{derived}"
        f"</subresponsibility>"
        "</subrequirements>"
    )


def _comparch_xml(session, project_id: str) -> str:
    target = _current_target_comp(session, project_id, kind="top")
    assert target is not None, "comparch stub: no target top-level comp without content"
    subresps = list(
        session.execute(
            select(Node)
            .where(
                Node.project_id == project_id,
                Node.tier == "resp",
                Node.parent_id == target.id,
            )
            .order_by(Node.display_order, Node.id)
        ).scalars()
    )
    assert subresps, f"comparch stub: target {target.id} has no subresps"
    # Foundations don't nest: when the target comp was minted with
    # the foundation role, the decomposition must NOT include
    # another foundation subcomponent. Concrete subcomponents
    # divide the foundation's territory exhaustively instead.
    target_is_foundation = bool(target.is_foundation)
    subs: list[str] = []
    for i, r in enumerate(subresps):
        alias = f"sub{i}"
        if target_is_foundation:
            foundation_tag = ""
        else:
            foundation_tag = "<foundation/>" if i == len(subresps) - 1 else ""
        subs.append(
            f'<subcomponent alias="{alias}">'
            f"<name>{target.name}{r.name}</name>"
            f"<role>Own the {r.name} slice of {target.name}.</role>"
            f"<api-intent>internal API for {r.name}</api-intent>"
            f'<responsibilities><resp id="{r.id}"/></responsibilities>'
            f"{foundation_tag}"
            f"</subcomponent>"
        )
    if target_is_foundation:
        # No foundation sub → no foundation-dep requirement.
        sub_deps = ""
    else:
        foundation_alias = f"sub{len(subresps) - 1}"
        sub_deps = "".join(
            f'<dep from="sub{i}" to="{foundation_alias}"/>' for i in range(len(subresps) - 1)
        )
    return (
        "<comparch>"
        "<technical-specification>Typical Python stack for this component."
        "</technical-specification>"
        f"<public-surface>public API for {target.name}.</public-surface>"
        "<private-surface>Internal helpers.</private-surface>"
        "<policies></policies>"
        "<dependencies></dependencies>"
        f"<subcomponents>{''.join(subs)}</subcomponents>"
        f"<sub-dependencies>{sub_deps}</sub-dependencies>"
        "</comparch>"
    )


def _subcomparch_xml() -> str:
    # Leaf of the component-tier chain. Empty deps is legal —
    # the stub doesn't need to reference sibling subs or the
    # parent's siblings.
    return (
        "<subcomparch>"
        "<technical-specification>Leaf subcomponent implementation details."
        "</technical-specification>"
        "<public-surface>Scoped API for this subcomponent.</public-surface>"
        "<private-surface>Internal helpers private to this subcomponent.</private-surface>"
        "<dependencies></dependencies>"
        "</subcomparch>"
    )


def _unique_in_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for x in items:
        if x in seen:
            continue
        seen.add(x)
        out.append(x)
    return out


def _current_target_comp(session, project_id: str, *, kind: str) -> Node | None:
    """Find the next comp (top-level or sub) that still needs a draft.

    The worker is single-threaded, so there's exactly one generation
    running at a time. The "current target" is the first ``comp_*``
    node (by display order) whose content is still empty AND which
    has no pending draft yet — the latter check skips comps for
    which a prior stub call in the same drain pass already minted a
    draft.
    """
    q = select(Node).where(
        Node.project_id == project_id,
        Node.tier == "comp",
        Node.content == "",
    )
    if kind == "top":
        q = q.where(Node.parent_id.is_(None))
    elif kind == "sub":
        q = q.where(Node.parent_id.isnot(None))
    q = q.order_by(Node.display_order, Node.id)
    for comp in session.execute(q).scalars():
        existing_draft = session.execute(
            select(Draft).where(
                Draft.project_id == project_id,
                Draft.target_id == comp.id,
                Draft.status == "pending",
            )
        ).first()
        if existing_draft is None:
            return comp
    return None


# ── LLM stub dispatch ─────────────────────────────────────────────────


@pytest.fixture()
def stub_cli(monkeypatch, shared_session_factory):
    """Patch cli_manager.generate_with_usage to the phase dispatcher.

    Patching the method on the module-level singleton mutates the
    shared instance, so every handler module that imports
    ``cli_manager`` sees the patched coroutine.
    """
    from backend.cli import manager as _manager_mod

    # Map from the handler's SYSTEM_PROMPT identity to a builder
    # that returns valid XML for that phase. Identity match keeps
    # the dispatch unambiguous even though several prompts mention
    # neighbouring phases' root tags in prose.
    phase_by_system_prompt: dict[int, str] = {
        id(_p_features.SYSTEM_PROMPT): "features",
        id(_p_reqs.SYSTEM_PROMPT): "requirements",
        id(_p_sysarch.SYSTEM_PROMPT): "sysarch",
        id(_p_subreqs.SYSTEM_PROMPT): "subrequirements",
        id(_p_comparch.SYSTEM_PROMPT): "comparch",
        id(_p_subcomparch.SYSTEM_PROMPT): "subcomparch",
        id(_p_policy.SYSTEM_PROMPT): "policy_application",
    }

    phases_called: list[str] = []

    async def fake_generate(**kwargs) -> GenerationResult:
        system_prompt = kwargs.get("system_prompt", "") or ""
        prompt = kwargs.get("prompt", "") or ""
        phase = phase_by_system_prompt.get(id(system_prompt))
        if phase is None:
            raise AssertionError(
                "LLM stub: unrecognised system prompt; dispatch table "
                "needs an entry for this handler"
            )
        phases_called.append(phase)

        session = shared_session_factory()
        try:
            # All bootstrap rows live under a single project in the
            # test harness — pick the first project row and use it.
            project_id = session.execute(select(Project.id)).scalar_one()

            if phase == "features":
                text = _features_xml()
            elif phase == "requirements":
                text = _requirements_xml(session, project_id)
            elif phase == "sysarch":
                text = _sysarch_xml(session, project_id)
            elif phase == "subrequirements":
                text = _subrequirements_xml(prompt)
            elif phase == "comparch":
                text = _comparch_xml(session, project_id)
            elif phase == "subcomparch":
                text = _subcomparch_xml()
            elif phase == "policy_application":
                # Empty <policies> at every tier means the policy
                # handlers early-return with no candidates and never
                # reach the LLM. If we land here the test's policy
                # scope has changed — fail loudly rather than return
                # an empty decision list silently.
                raise AssertionError(
                    "policy_application stub was called but the chain "
                    "test expects empty policy scopes that no-op "
                    "before reaching the LLM"
                )
            else:
                raise AssertionError(f"unhandled phase {phase!r}")
        finally:
            session.close()

        return GenerationResult(
            text=text,
            prompt_tokens=100,
            completion_tokens=50,
            model="claude-sonnet-4-6-stub",
        )

    monkeypatch.setattr(_manager_mod.cli_manager, "generate_with_usage", fake_generate)
    return phases_called


# ── Queue-drain + approval helpers ────────────────────────────────────


async def _drain_pipeline_queue() -> None:
    """Drain the job queue to empty by replicating one tick of the worker loop.

    Stripped-down clone of :func:`backend.pipeline.queue.worker_loop`'s
    body — no event-wait, no poll interval. Stops as soon as
    ``_claim_next_sync`` returns ``None``.
    """
    from backend.pipeline.queue import _JOB_HANDLERS, _claim_next_sync, _complete_job_sync

    while True:
        claimed = await asyncio.to_thread(_claim_next_sync)
        if claimed is None:
            return
        job_id, job_type, payload = claimed
        handler = _JOB_HANDLERS.get(job_type)
        if handler is None:
            await asyncio.to_thread(_complete_job_sync, job_id, f"Unknown job type: {job_type}")
            continue
        error: str | None = None
        try:
            await handler(payload)
        except Exception as exc:  # noqa: BLE001 — mirror worker loop exactly
            error = str(exc)[:1000]
        await asyncio.to_thread(_complete_job_sync, job_id, error)


def _approve_all_pending_drafts(factory, project_id: str) -> int:
    """Approve every pending draft for ``project_id`` and enqueue its mint.

    Stand-in for the per-tier approve routes — the real routes run
    the same two steps (DraftApproved event + tier-specific mint
    enqueue), and this helper collapses them into a single pass so
    the test can advance the chain after each drain. Returns the
    number of drafts approved so the driver knows whether the
    chain has converged.
    """
    from backend.pipeline import queue as pipeline_queue

    session = factory()
    try:
        drafts = list(
            session.execute(
                select(Draft).where(
                    Draft.project_id == project_id,
                    Draft.status == "pending",
                )
            ).scalars()
        )
        for draft in drafts:
            node = session.get(Node, draft.target_id)
            assert node is not None, f"draft {draft.id} targets missing node"
            append_event(session, project_id, ev.DraftApproved(draft_id=draft.id))
            if node.tier == "expansion":
                pipeline_queue.enqueue(
                    session,
                    job_type="v2.mint_features",
                    payload={"project_id": project_id},
                )
            elif node.tier == "reqs":
                pipeline_queue.enqueue(
                    session,
                    job_type="v2.mint_requirements",
                    payload={"project_id": project_id},
                )
            elif node.tier == "sysarch":
                pipeline_queue.enqueue(
                    session,
                    job_type="v2.mint_sysarch",
                    payload={"project_id": project_id},
                )
            elif node.tier == "subreqs":
                assert node.parent_id is not None
                pipeline_queue.enqueue(
                    session,
                    job_type="v2.mint_subrequirements",
                    payload={"project_id": project_id, "component_id": node.parent_id},
                )
            elif node.tier == "comp":
                if node.parent_id is None:
                    pipeline_queue.enqueue(
                        session,
                        job_type="v2.mint_comparch",
                        payload={"project_id": project_id, "component_id": node.id},
                    )
                else:
                    pipeline_queue.enqueue(
                        session,
                        job_type="v2.mint_subcomparch",
                        payload={"project_id": project_id, "component_id": node.id},
                    )
            else:
                raise AssertionError(f"unexpected draft target tier: {node.tier!r}")
        session.commit()
        return len(drafts)
    finally:
        session.close()


async def _drive_full_chain(factory, project_id: str, *, max_iterations: int = 100) -> int:
    """Alternate drain / approve steps until the chain settles.

    The loop terminates when a drain pass leaves the job queue
    empty *and* no pending drafts remain to approve. Returns the
    number of drain/approve iterations consumed so tests can
    assert the loop actually converged (rather than hitting the
    safety limit).
    """
    for iteration in range(1, max_iterations + 1):
        await _drain_pipeline_queue()
        approved = _approve_all_pending_drafts(factory, project_id)
        if approved == 0:
            return iteration
    raise AssertionError(
        f"bootstrap chain did not converge within {max_iterations} iterations — "
        "likely a broken fan-out enqueue"
    )


# ── Seed + kickoff helpers ────────────────────────────────────────────


def _seed_project(factory) -> str:
    """Insert a Project row + input doc + bootstrap expansion node."""
    project_id = str(uuid.uuid4())
    session = factory()
    try:
        session.add(
            Project(id=project_id, name="ChainTestProject", git_repo_path="/tmp/chain_test")
        )
        session.flush()
        session.add(
            InputDocument(
                id=str(uuid.uuid4()),
                project_id=project_id,
                name="project_doc.md",
                doc_type="project_doc",
                content=(
                    "A small SaaS that lets users sign in and pay for plans. "
                    "Should support basic auth and subscription billing."
                ),
            )
        )
        bootstrap_expansion_node(session, project_id)
        session.commit()
        return project_id
    finally:
        session.close()


def _kickoff_bootstrap(factory, project_id: str) -> None:
    """Enqueue the first job in the chain."""
    from backend.pipeline import queue as pipeline_queue

    session = factory()
    try:
        pipeline_queue.enqueue(
            session,
            job_type="v2.generate_feature_expansion",
            payload={"project_id": project_id, "feedback": None},
        )
        session.commit()
    finally:
        session.close()


# ── The test ─────────────────────────────────────────────────────────


class TestFullBootstrapChain:
    def test_chain_runs_end_to_end(self, shared_session_factory, stub_cli):
        factory = shared_session_factory
        project_id = _seed_project(factory)
        _kickoff_bootstrap(factory, project_id)

        iterations = asyncio.run(_drive_full_chain(factory, project_id))
        assert iterations > 0

        session = factory()
        try:
            # No failed jobs — every handler in the chain succeeded.
            failed = list(session.execute(select(Job).where(Job.status == "failed")).scalars())
            assert failed == [], f"failed jobs in chain: {[j.job_type for j in failed]}"

            # Every queue entry ran to completion.
            unfinished = list(
                session.execute(select(Job).where(Job.status.in_(("queued", "running")))).scalars()
            )
            assert unfinished == [], (
                f"jobs still pending after convergence: "
                f"{[(j.job_type, j.status) for j in unfinished]}"
            )

            # Every bootstrap tier produced its nodes.
            feats = list(
                session.execute(
                    select(Node).where(Node.project_id == project_id, Node.tier == "feat")
                ).scalars()
            )
            top_resps = list(
                session.execute(
                    select(Node).where(
                        Node.project_id == project_id,
                        Node.tier == "resp",
                        Node.parent_id.is_(None),
                    )
                ).scalars()
            )
            top_comps = list(
                session.execute(
                    select(Node).where(
                        Node.project_id == project_id,
                        Node.tier == "comp",
                        Node.parent_id.is_(None),
                    )
                ).scalars()
            )
            subresps = list(
                session.execute(
                    select(Node).where(
                        Node.project_id == project_id,
                        Node.tier == "resp",
                        Node.parent_id.isnot(None),
                    )
                ).scalars()
            )
            subcomps = list(
                session.execute(
                    select(Node).where(
                        Node.project_id == project_id,
                        Node.tier == "comp",
                        Node.parent_id.isnot(None),
                    )
                ).scalars()
            )
            assert len(feats) == 2
            assert len(top_resps) == 3
            assert len(top_comps) == 3
            # Each comp has 2 subresps → 6 subresps total.
            assert len(subresps) == 6
            # Each comp decomposes into 2 subcomponents → 6 subcomps.
            assert len(subcomps) == 6

            # Foundation persistence: sysarch seeds one top-level
            # foundation (the last in display order), and comparch
            # seeds one foundation subcomponent per non-foundation
            # parent. A foundation top-level's own comparch does
            # NOT nest another foundation subcomponent — so the
            # foundation sub count is exactly (top-level comps - 1),
            # covering only the non-foundation parents.
            top_foundations = [c for c in top_comps if c.is_foundation]
            assert len(top_foundations) == 1
            sub_foundations = [c for c in subcomps if c.is_foundation]
            assert len(sub_foundations) == len(top_comps) - 1, (
                f"expected {len(top_comps) - 1} foundation subcomponents "
                f"(one per non-foundation parent), got {len(sub_foundations)}"
            )
            # And every foundation sub's parent is a non-foundation top-level.
            top_by_id = {c.id: c for c in top_comps}
            for fsub in sub_foundations:
                assert fsub.parent_id is not None
                parent = top_by_id[fsub.parent_id]
                assert parent.is_foundation is False

            # Vocabulary: stage 3 extended feature_mint to also
            # project vocab_* nodes from the expansion's
            # <vocabulary> sibling block. The stub emits two
            # entries — one project-level ("boulder") and one
            # feature-local under Billing ("tranche"). Verify
            # both landed at the correct scope.
            vocab_nodes = list(
                session.execute(
                    select(Node).where(
                        Node.project_id == project_id,
                        Node.tier == "vocab",
                    )
                ).scalars()
            )
            assert len(vocab_nodes) == 2
            boulder = next(v for v in vocab_nodes if v.name == "boulder")
            tranche = next(v for v in vocab_nodes if v.name == "tranche")
            # boulder is project-level (parent_id is None)
            assert boulder.parent_id is None
            assert "<vocab-entry>" in boulder.content
            # tranche is feature-local, parented to the Billing feat
            billing_feat = next(f for f in feats if f.name == "Billing")
            assert tranche.parent_id == billing_feat.id
            assert "<vocab-entry>" in tranche.content

            # Every top-level comp AND every subcomponent ended
            # with approved arch-doc content — i.e. both comparch
            # and subcomparch passes ran end-to-end, not just up
            # through comparch.
            for comp in top_comps + subcomps:
                assert comp.content, f"comp {comp.id} ({comp.name}) has empty content"
                assert comp.content.lstrip().startswith(("<comparch>", "<subcomparch>"))

            # Fragments: every top-level comp should have the five
            # comparch fragments (techspec/pubapi/privapi/policies/deps).
            # Every subcomponent should have the four subcomparch
            # fragments (techspec/pubapi/privapi/deps — no policies).
            for comp in top_comps:
                frag_kinds = set(
                    row[0]
                    for row in session.execute(
                        select(Fragment.fragment_kind).where(Fragment.owner_id == comp.id)
                    )
                )
                assert frag_kinds == {
                    "techspec",
                    "pubapi",
                    "privapi",
                    "policies",
                    "deps",
                }, f"{comp.id} fragments = {frag_kinds}"
            for sub in subcomps:
                frag_kinds = set(
                    row[0]
                    for row in session.execute(
                        select(Fragment.fragment_kind).where(Fragment.owner_id == sub.id)
                    )
                )
                assert frag_kinds == {
                    "techspec",
                    "pubapi",
                    "privapi",
                    "deps",
                }, f"{sub.id} fragments = {frag_kinds}"

            # The decomposition edge network is populated. Every
            # subresp has at least one decomposition edge to a
            # subcomponent (from comparch mint).
            decomp_edges = list(
                session.execute(
                    select(Edge).where(
                        Edge.project_id == project_id,
                        Edge.edge_type == "decomposition",
                    )
                ).scalars()
            )
            # Features → top-level resps is many-to-many via covers,
            # plus top-level resps → top-level comps (3),
            # plus subresps → subcomps (6). The exact count depends
            # on the covers stub but at minimum we should see the
            # non-covers structural edges.
            assert len(decomp_edges) >= 9

            # The chain exercised every generation phase at least
            # once. policy_application is EXPECTED to be absent —
            # empty <policies> scopes cause both policy handlers to
            # early-return before reaching the LLM stub.
            phases = set(stub_cli)
            assert phases == {
                "features",
                "requirements",
                "sysarch",
                "subrequirements",
                "comparch",
                "subcomparch",
            }, f"unexpected phases called: {phases}"
        finally:
            session.close()
