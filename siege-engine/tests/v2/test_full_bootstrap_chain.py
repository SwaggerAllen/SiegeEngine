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
# Skip Phase 8 AI self-review jobs in the chain integration test —
# the stubbed CLI only knows the generator prompts; adding review
# prompts would bloat the stub and double the test runtime.
os.environ.setdefault("SIEGE_DISABLE_AI_REVIEW", "1")

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
from backend.graph.prompts import fanin as _p_fanin  # noqa: E402
from backend.graph.prompts import impl as _p_impl  # noqa: E402
from backend.graph.prompts import policy_application as _p_policy  # noqa: E402
from backend.graph.prompts import subcomparch as _p_subcomparch  # noqa: E402
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
    "backend.graph.handlers.impl_generation",
    "backend.graph.handlers.fanin_generation",
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
        "<introduction>Chain integration test: stub intro.</introduction>"
        "<features>"
        "<feature><name>Billing</name><intent>Ok intent.</intent></feature>"
        "<feature><name>Auth</name><intent>Ok intent.</intent></feature>"
        # Two additional features so the requirements stub can hand
        # each of the four synthetic responsibilities a distinct
        # primary-owned feature under the single-owner rule.
        "<feature><name>Admin</name><intent>Ok intent.</intent></feature>"
        "<feature><name>Reports</name><intent>Ok intent.</intent></feature>"
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
    # Atomic grammar: each atom is a unique scope phrase with a
    # flat <feats> list. Many-to-many is legal, so giving every
    # atom every feat satisfies coverage in the simplest way.
    # Atom names match the sysarch stub's expected resp names
    # (Authentication, BillingDomain, BillingUI, Foundation).
    names = ("Authentication", "BillingDomain", "BillingUI", "Foundation")
    feats_block = "<feats>" + "".join(f'<feat id="{fid}"/>' for fid in feat_ids) + "</feats>"
    rows = [f"<responsibility><name>{name}</name>{feats_block}</responsibility>" for name in names]
    inner = "".join(rows)
    return (
        "<introduction>Chain integration test: stub intro.</introduction>"
        f"<requirements>{inner}</requirements>"
    )


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
    # The presentational slice: the resp named "BillingUI" is owned
    # by the domain component that also owns "BillingDomain". The
    # presentational component mirrors its domain parent's resp
    # (resp_BillingUI) — presentational components can no longer
    # have unique resps, they must share resps assigned to a domain
    # component via a domain_parent edge.
    presentational_resp_name = "BillingUI"
    presentational_domain_target = "BillingDomain"
    resp_by_name: dict[str, Node] = {r.name: r for r in resps}
    # Build a mapping: each domain component's alias → list of resp IDs.
    # The BillingDomain domain component also absorbs the BillingUI resp
    # so the coverage rule is satisfied. The presentational comp then
    # mirrors that resp via a domain_parent edge.
    domain_resps = [r for r in resps if r.name != presentational_resp_name]
    resp_name_to_alias: dict[str, str] = {}
    components: list[str] = []
    for i, r in enumerate(domain_resps):
        alias = f"comp{i}"
        resp_name_to_alias[r.name] = alias
        is_foundation = i == len(domain_resps) - 1
        foundation_tag = "<foundation/>" if is_foundation else ""
        # If this domain comp is the BillingDomain target, it also
        # owns the BillingUI resp.
        resp_ids = [r.id]
        if r.name == presentational_domain_target and presentational_resp_name in resp_by_name:
            resp_ids.append(resp_by_name[presentational_resp_name].id)
        resp_xml = "".join(f'<resp id="{rid}"/>' for rid in resp_ids)
        components.append(
            f'<component alias="{alias}">'
            f"<name>{r.name}Service</name>"
            f"<kind>domain</kind>"
            f"<role>Own the {r.name} subsystem.</role>"
            f"<api-intent>public API for {r.name}</api-intent>"
            f"<responsibilities>{resp_xml}</responsibilities>"
            f"{foundation_tag}"
            f"</component>"
        )
    # Add the presentational component mirroring BillingUI resp.
    pres_resp = resp_by_name.get(presentational_resp_name)
    pres_alias: str | None = None
    if pres_resp is not None:
        pres_alias = f"comp{len(domain_resps)}"
        resp_name_to_alias[presentational_resp_name] = pres_alias
        components.append(
            f'<component alias="{pres_alias}">'
            f"<name>{presentational_resp_name}Service</name>"
            f"<kind>presentational</kind>"
            f"<role>Own the {presentational_resp_name} subsystem.</role>"
            f"<api-intent>public API for {presentational_resp_name}</api-intent>"
            f'<responsibilities><resp id="{pres_resp.id}"/></responsibilities>'
            f"</component>"
        )
    foundation_alias = f"comp{len(domain_resps) - 1}"
    total_comps = len(domain_resps) + (1 if pres_alias else 0)
    # Every non-foundation top-level depends on the foundation.
    deps = "".join(
        f'<dep from="comp{i}" to="{foundation_alias}"/>'
        for i in range(total_comps)
        if f"comp{i}" != foundation_alias
    )
    # The presentational comp presents its sibling domain comp.
    domain_parent_entries = ""
    if pres_alias is not None and presentational_domain_target in resp_name_to_alias:
        domain_parent_entries = (
            f'<parent from="{pres_alias}" to="{resp_name_to_alias[presentational_domain_target]}"/>'
        )
    return (
        "<introduction>Chain integration test: stub intro.</introduction>"
        "<sysarch>"
        "<techspec>Python + FastAPI + PostgreSQL event-sourced stack.</techspec>"
        f"<components>{''.join(components)}</components>"
        "<policies></policies>"
        f"<dependencies>{deps}</dependencies>"
        f"<domain-parent>{domain_parent_entries}</domain-parent>"
        "</sysarch>"
    )


def _subrequirements_xml(prompt: str) -> str:
    # Parent resps are rendered under the "Top-level
    # responsibilities assigned to this component" header in the
    # prompt; grab only those so the stub doesn't capture resp IDs
    # from the sibling-dependency block (those belong to peer
    # comps and would fail the cross-component-leak validator).
    header = "# Top-level responsibilities assigned to this component"
    if header not in prompt:
        raise AssertionError(
            "subrequirements stub: missing parent-resps header — handler changed its prompt shape?"
        )
    # Scope the resp-id grab to the slice between the parent-resps
    # header and the next top-level ``#`` header. Sibling / domain-
    # parent context is emitted under its own header, so slicing
    # out this section and stopping at the next ``#`` keeps the
    # stub derived-from set accurate for this component.
    section = prompt.split(header, 1)[1]
    section = section.split("\n# ", 1)[0]
    parent_resp_ids = _unique_in_order(_RESP_ID_RE.findall(section))
    if not parent_resp_ids:
        raise AssertionError(
            "subrequirements stub: no resp_* IDs under parent-resps "
            "header — handler changed its prompt shape?"
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


def _comparch_xml(session, project_id: str, prompt: str) -> str:
    # Target discovery: read the first resp_* id out of the
    # rendered prompt and walk its ``parent_id`` back to the
    # owning top-level comp. The comparch prompt renders the
    # target's pre-minted subresps via ``subresps_summary`` as a
    # bullet list keyed by real resp IDs, so any subresp in the
    # prompt is unambiguously owned by this comp. This is more
    # robust than a DB heuristic (which breaks once comparch jobs
    # are enqueued out of display order — Phase 6's ordering
    # change makes the presentational comp's comparch fire after
    # its domain parent's, not in display order).
    resp_ids = _unique_in_order(_RESP_ID_RE.findall(prompt))
    target: Node | None = None
    for rid in resp_ids:
        resp_node = session.get(Node, rid)
        if resp_node is None or resp_node.parent_id is None:
            continue  # top-level resps (parent_id=None) don't resolve to a comp here
        parent_comp = session.get(Node, resp_node.parent_id)
        if parent_comp is not None and parent_comp.tier == "comp":
            target = parent_comp
            break
    assert target is not None, (
        "comparch stub: could not infer target top-level comp from prompt — "
        "expected at least one subresp id rendered via subresps_summary"
    )
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


def _fanin_xml() -> str:
    # Phase 7 synthesis: three required sections.
    return (
        "<fanin>"
        "<summary>Stub fan-in summary of the built component.</summary>"
        "<exposed-surface>public API for this component's subs.</exposed-surface>"
        "<realized-behavior>Subs compose via call-through ordering.</realized-behavior>"
        "</fanin>"
    )


def _impl_xml() -> str:
    # Phase 8 leaf: a single implementation doc under each impl
    # owner. Prose sections, not code — the plan prompt (Phase 14)
    # is what translates these into (file, region, change)
    # tuples. Structural validator enforces presence + ordering;
    # content is opaque.
    return (
        "<implementation>"
        "<behavior>Stub behavior description for the test harness — "
        "leaf accepts calls and mutates its private state.</behavior>"
        "<invariants>Stub invariants — all inputs validated at the "
        "boundary; private state never leaks outward.</invariants>"
        "<sequencing>Stub sequencing — operations are idempotent "
        "except for the state-mutating ones which run in order.</sequencing>"
        "<edge-cases>Stub edge cases — empty input returns a "
        "sentinel; concurrent mutation surfaces as a retry error."
        "</edge-cases>"
        "</implementation>"
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

    # Dispatch phase by a distinctive substring in the system
    # prompt's opening paragraph. The five bootstrap prompts
    # (feature_expansion, requirements, sysarch, subrequirements,
    # comparch) are now rendered per-call via
    # ``render_system_prompt(counts)``, so identity-match no longer
    # works — each invocation produces a fresh string. Two prompts
    # (subcomparch, policy_application) still have a module-level
    # SYSTEM_PROMPT constant and match by identity for historical
    # reasons; we fall through to substring match if identity
    # lookup misses. Substrings were chosen from each template's
    # opening sentence to be unique across tiers.
    phase_by_identity: dict[int, str] = {
        id(_p_subcomparch.SYSTEM_PROMPT): "subcomparch",
        id(_p_policy.SYSTEM_PROMPT): "policy_application",
        id(_p_impl.SYSTEM_PROMPT): "impl",
        id(_p_fanin.SYSTEM_PROMPT): "fanin",
    }
    phase_by_substring: tuple[tuple[str, str], ...] = (
        ("extracting structured features", "features"),
        ("rotating** the problem from user-facing", "requirements"),
        ("producing the **system", "sysarch"),
        ("expanding a single component", "subrequirements"),
        ("last compression step** before implementation", "comparch"),
    )

    def _phase_for(system_prompt: str) -> str | None:
        hit = phase_by_identity.get(id(system_prompt))
        if hit is not None:
            return hit
        for needle, phase in phase_by_substring:
            if needle in system_prompt:
                return phase
        return None

    phases_called: list[str] = []
    # Capture every rendered user prompt per phase so Phase 6
    # assertions can verify the comparch / subcomparch stubs
    # actually received the domain-parent block for presentational
    # targets. One list per phase — order matches ``phases_called``.
    prompts_by_phase: dict[str, list[str]] = {}

    async def fake_generate(**kwargs) -> GenerationResult:
        system_prompt = kwargs.get("system_prompt", "") or ""
        prompt = kwargs.get("prompt", "") or ""
        phase = _phase_for(system_prompt)
        if phase is None:
            raise AssertionError(
                "LLM stub: unrecognised system prompt; dispatch table "
                "needs an entry for this handler"
            )
        phases_called.append(phase)
        prompts_by_phase.setdefault(phase, []).append(prompt)

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
                text = _comparch_xml(session, project_id, prompt)
            elif phase == "subcomparch":
                text = _subcomparch_xml()
            elif phase == "impl":
                text = _impl_xml()
            elif phase == "fanin":
                text = _fanin_xml()
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
    return {"phases": phases_called, "prompts": prompts_by_phase}


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
            elif node.tier == "impl":
                # Phase 8: impl approval commits Node.content via
                # the DraftApproved reducer branch. No mint job
                # follows — impls have no fragments and no
                # children. Plan / codegen coupling is Phase 14.
                # Phase 7: fire the on_approve hook the real
                # bootstrap_approve wires up, so fan-in regen
                # enqueues under fanned-out domain comps.
                from backend.graph.handlers.impl_generation import on_impl_approved

                on_impl_approved(session, project_id, node, (node.parent_id,))
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
            assert len(feats) == 4
            # Phase 6 adds a BillingUI resp/comp as the presentational
            # slice alongside the three pre-existing domain resps.
            assert len(top_resps) == 4
            assert len(top_comps) == 4
            # Each comp has 2 subresps → 8 subresps total.
            assert len(subresps) == 8
            # Each comp decomposes into 2 subcomponents → 8 subcomps.
            assert len(subcomps) == 8

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

            # ── Phase 8: impl leaves minted + filled ──────────────
            # comparch_mint creates one impl shell per
            # subcomponent (all subs in this harness) and one
            # per un-fanned-out top-level comp (none in this
            # harness — every top-level decomposes into subs).
            # generate_impl fills each shell with the stub
            # <implementation> block.
            impl_nodes = list(
                session.execute(
                    select(Node).where(
                        Node.project_id == project_id,
                        Node.tier == "impl",
                    )
                ).scalars()
            )
            # One impl per subcomponent — every sub is a leaf.
            assert len(impl_nodes) == len(subcomps), (
                f"expected {len(subcomps)} impl leaves (one per "
                f"subcomponent), got {len(impl_nodes)}"
            )
            # Every impl's parent is a subcomponent (not a
            # fanned-out top-level comp — those have no impl).
            subcomp_ids = {s.id for s in subcomps}
            for impl in impl_nodes:
                assert impl.parent_id in subcomp_ids, (
                    f"impl {impl.id} has parent_id "
                    f"{impl.parent_id!r}, expected one of the "
                    "subcomponent ids"
                )
                assert impl.content, f"impl {impl.id} has empty content"
                assert impl.content.lstrip().startswith("<implementation>")
            # Fanned-out top-level comps have NO impl child —
            # their impl lives in their subcomponents' impls.
            for comp in top_comps:
                impl_under_top = [i for i in impl_nodes if i.parent_id == comp.id]
                assert impl_under_top == [], (
                    f"top-level fanned-out comp {comp.id} unexpectedly has an impl child"
                )

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
            phases = set(stub_cli["phases"])
            assert phases == {
                "features",
                "requirements",
                "sysarch",
                "subrequirements",
                "comparch",
                "subcomparch",
                "impl",
                "fanin",
            }, f"unexpected phases called: {phases}"

            # ── Phase 7: fan-in shells minted + filled ────────────
            # Every fanned-out domain top-level comp has a
            # tier="fanin" child with non-empty content after all
            # impls approve. Presentational comps do not get
            # fan-ins. (All four top-level comps in this harness
            # fan out into 2 subs; three are domain, one is
            # presentational — BillingUIService.)
            fanin_nodes = list(
                session.execute(
                    select(Node).where(
                        Node.project_id == project_id,
                        Node.tier == "fanin",
                    )
                ).scalars()
            )
            domain_top_comps = [c for c in top_comps if c.kind == "domain"]
            assert len(fanin_nodes) == len(domain_top_comps), (
                f"expected {len(domain_top_comps)} fan-in shells "
                f"(one per fanned-out domain top-level), got "
                f"{len(fanin_nodes)}"
            )
            fanin_parent_ids = {f.parent_id for f in fanin_nodes}
            domain_top_ids = {c.id for c in domain_top_comps}
            assert fanin_parent_ids == domain_top_ids, (
                f"fan-in parent ids {fanin_parent_ids} do not "
                f"match domain top-level ids {domain_top_ids}"
            )
            # Presentational top-level must have no fan-in child.
            pres_top = next(c for c in top_comps if c.kind == "presentational")
            assert not any(f.parent_id == pres_top.id for f in fanin_nodes)
            # Every fan-in got filled by generate_fanin.
            for fanin in fanin_nodes:
                assert fanin.content, (
                    f"fan-in {fanin.id} under comp {fanin.parent_id} "
                    "has empty content after chain convergence"
                )
                assert fanin.content.lstrip().startswith("<fanin>")

            # Fan-in generation ran at least once per domain comp.
            # The queue's payload-dedup may collapse multiple
            # impl approvals into a single run, so we assert
            # "at least one per domain comp, at most len(impls)".
            fanin_phase_calls = [p for p in stub_cli["phases"] if p == "fanin"]
            assert len(fanin_phase_calls) >= len(domain_top_comps)

            # ── Phase 6: presentational path ──────────────────────
            # sysarch emitted a presentational comp + domain_parent
            # edge. Verify the edge landed in the projection.
            dp_edges = list(
                session.execute(
                    select(Edge).where(
                        Edge.project_id == project_id,
                        Edge.edge_type == "domain_parent",
                    )
                ).scalars()
            )
            assert len(dp_edges) == 1, f"expected one domain_parent edge, got {len(dp_edges)}"
            dp_edge = dp_edges[0]
            presentational_comp = session.get(Node, dp_edge.source_id)
            domain_target_comp = session.get(Node, dp_edge.target_id)
            assert presentational_comp is not None
            assert domain_target_comp is not None
            assert presentational_comp.kind == "presentational"
            assert domain_target_comp.kind == "domain"
            assert presentational_comp.name == "BillingUIService"
            assert domain_target_comp.name == "BillingDomainService"

            # The comparch prompt rendered for the presentational
            # comp must contain the "# This component presents"
            # block carrying the domain target's id and pubapi
            # snippet. Exactly one prompt should carry that section
            # — only BillingUI's own comparch regen runs through
            # the presentational branch of build_regen_context.
            # (The presentational comp's *own* id does not appear
            # in its own prompt because _format_component_summary
            # prints only the name, not the id. We locate the
            # prompt by the section header instead.)
            comparch_prompts = stub_cli["prompts"]["comparch"]
            prompts_with_presenting = [
                p for p in comparch_prompts if "# This component presents" in p
            ]
            assert len(prompts_with_presenting) == 1, (
                f"expected exactly one comparch prompt to carry the "
                f"'# This component presents' section, got "
                f"{len(prompts_with_presenting)}"
            )
            presentational_comparch_prompt = prompts_with_presenting[0]
            # The presenting section must reference the domain
            # target by real comp_* id, and carry the pubapi text.
            assert domain_target_comp.id in presentational_comparch_prompt
            assert "public API for BillingDomain" in presentational_comparch_prompt
            # And the prompt's own component_summary should show
            # the presentational comp's name (but not id — see
            # comment above).
            assert "BillingUIService" in presentational_comparch_prompt

            # Ordering proof: domain_parent edges count as a
            # dependency for comparch regen order, so BillingUI's
            # comparch must run *after* BillingDomain's comparch
            # has been approved and comparch_mint has replaced
            # the skeletal sysarch-time techspec ("Own the
            # BillingDomain subsystem.") with the comparch-level
            # techspec ("Typical Python stack for this
            # component."). If the ordering were still FIFO /
            # display-order, BillingUI would fire before
            # BillingDomain's approval and its domain-parent
            # block would still carry the sysarch seed.
            assert "Typical Python stack for this component." in (presentational_comparch_prompt), (
                "presentational comparch prompt still shows the "
                "sysarch-time techspec seed; domain-parent ordering "
                "did not take effect"
            )
            assert "Own the BillingDomain subsystem." not in (presentational_comparch_prompt), (
                "presentational comparch prompt still carries the "
                "sysarch-time role seed instead of the approved "
                "comparch techspec"
            )

            # ── Phase 7: presentational regen sees fan-in ─────────
            # After the chain converges (so fan-in content exists),
            # a fresh comparch regen for the presentational comp
            # should populate domain_parent_fanins from the
            # BillingDomain fan-in. The presentational prompt
            # captured during bootstrap ran BEFORE any impls were
            # approved, so its fanin map was empty; assert against
            # a fresh regen context instead.
            from backend.graph.regen_context import build_regen_context

            pres_ctx = build_regen_context(session, presentational_comp.id)
            assert domain_target_comp.id in pres_ctx.domain_parent_fanins, (
                "presentational regen context missing fan-in entry "
                f"for domain parent {domain_target_comp.id}"
            )
            fanin_in_ctx = pres_ctx.domain_parent_fanins[domain_target_comp.id]
            assert fanin_in_ctx.lstrip().startswith("<fanin>"), (
                "domain_parent_fanins entry does not look like a "
                f"<fanin> block: {fanin_in_ctx[:100]!r}"
            )

            # And the formatted presenting block carries both the
            # pubapi (top-down intent) and the fan-in (built
            # reality) so the LLM can surface drift.
            from backend.graph.prompts.comparch import format_domain_parent_surface

            presenting_block = format_domain_parent_surface(
                pres_ctx.domain_parents,
                pres_ctx.domain_parent_techspecs,
                pres_ctx.domain_parent_pubapis,
                pres_ctx.domain_parent_fanins,
            )
            assert "top-down intent" in presenting_block
            assert "bottom-up fan-in synthesis" in presenting_block
            assert "public API for BillingDomain" in presenting_block
            assert "<fanin>" in presenting_block

            # And every subcomparch prompt for a sub OF the
            # presentational comp must carry the grandparent block.
            # At least one prompt per presentational subcomponent —
            # with Phase 9 fanout, sibling-dependency cascades can
            # trigger additional regens after first-pass approvals,
            # so the count is a lower bound, not an exact. The
            # per-prompt content invariant (every prompt has the
            # section and cites the domain parent) is what actually
            # matters. Subcomparch prompts for domain subs must NOT
            # carry the section.
            subcomparch_prompts = stub_cli["prompts"]["subcomparch"]
            presentational_subcomps = [
                sub for sub in subcomps if sub.parent_id == presentational_comp.id
            ]
            assert len(presentational_subcomps) == 2, (
                "expected the presentational top-level comp to have "
                "decomposed into two subcomponents; got "
                f"{len(presentational_subcomps)}"
            )
            prompts_with_grandparent = [
                p for p in subcomparch_prompts if "# Grandparent domain context" in p
            ]
            assert len(prompts_with_grandparent) >= len(presentational_subcomps), (
                f"expected at least {len(presentational_subcomps)} subcomparch "
                f"prompts with the grandparent section, got "
                f"{len(prompts_with_grandparent)}"
            )
            for p in prompts_with_grandparent:
                assert domain_target_comp.id in p
                assert "public API for BillingDomain" in p
        finally:
            session.close()

    def test_reference_tier_integrates_into_regen_context(self, shared_session_factory, stub_cli):
        """Phase 6.6 integration check.

        After the main bootstrap chain converges, seed a ``ref_*``
        node attached via a ``reference`` edge to a top-level comp,
        and verify:

        (a) ``build_regen_context`` on that comp populates
            ``referenced_content`` and the rendered
            ``referenced_content_summary`` carries the ref's body.

        (b) For the reverse walk (ref → comp), the ref's own
            ``referenced_content_for_node`` pulls the comp's
            ``pubapi`` fragment.

        This is the end-to-end integration the Phase 6.6 plan calls
        out — both directions of the walker dispatch, with live
        state produced by the actual bootstrap chain.
        """
        from backend.graph import events as ev
        from backend.graph.ids import Kind, mint
        from backend.graph.reducer import append_event
        from backend.graph.references import (
            format_referenced_content_summary,
            referenced_content_for_node,
        )
        from backend.graph.regen_context import (
            build_regen_context,
            format_regen_context,
        )

        factory = shared_session_factory
        project_id = _seed_project(factory)
        _kickoff_bootstrap(factory, project_id)
        asyncio.run(_drive_full_chain(factory, project_id))

        session = factory()
        try:
            top_comps = list(
                session.execute(
                    select(Node).where(
                        Node.project_id == project_id,
                        Node.tier == "comp",
                        Node.parent_id.is_(None),
                    )
                ).scalars()
            )
            assert top_comps, "bootstrap chain should have minted top-level comps"
            billing_domain = next(c for c in top_comps if c.name == "BillingDomainService")

            # Seed a ref node
            ref_id = mint(session, Kind.REF)
            ref_content = (
                "<reference>"
                "<title>Deployment Runbook</title>"
                "<body>Run kubectl apply. Then verify pods are healthy.</body>"
                "</reference>"
            )
            append_event(
                session,
                project_id,
                ev.NodeCreated(
                    node_id=ref_id,
                    tier="ref",
                    kind="domain",
                    parent_id=None,
                    name="Deployment Runbook",
                    content=ref_content,
                ),
            )
            # Direction 1: billing_domain --reference--> ref
            comp_to_ref_edge = mint(session, Kind.EDGE)
            append_event(
                session,
                project_id,
                ev.EdgeCreated(
                    edge_id=comp_to_ref_edge,
                    edge_type="reference",
                    source_id=billing_domain.id,
                    target_id=ref_id,
                ),
            )
            # Direction 2: ref --reference--> billing_domain (for the
            # reverse-walk assertion; the walker is source-tier-
            # agnostic so this works either direction).
            ref_to_comp_edge = mint(session, Kind.EDGE)
            append_event(
                session,
                project_id,
                ev.EdgeCreated(
                    edge_id=ref_to_comp_edge,
                    edge_type="reference",
                    source_id=ref_id,
                    target_id=billing_domain.id,
                ),
            )
            session.commit()

            # (a) comp's build_regen_context sees the ref's content
            ctx = build_regen_context(session, billing_domain.id)
            assert ref_id in ctx.referenced_content
            assert "kubectl apply" in ctx.referenced_content[ref_id]
            formatted = format_regen_context(ctx)
            assert "# References" in formatted["referenced_content_summary"]
            assert ref_id in formatted["referenced_content_summary"]
            assert "kubectl apply" in formatted["referenced_content_summary"]

            # (b) ref's walker pulls the comp's pubapi fragment, not
            # the node content (which is the raw comparch XML).
            reverse = referenced_content_for_node(session, project_id, ref_id)
            assert billing_domain.id in reverse
            # The comp's pubapi fragment was written by the comparch
            # pass; its content is the body of the <public-surface>
            # section the stub emitted. Assert it's the fragment
            # content and not the full node content (which would
            # start with "<comparch>").
            rendered = reverse[billing_domain.id]
            assert not rendered.lstrip().startswith("<comparch>")
            summary = format_referenced_content_summary(reverse)
            assert billing_domain.id in summary
        finally:
            session.close()
