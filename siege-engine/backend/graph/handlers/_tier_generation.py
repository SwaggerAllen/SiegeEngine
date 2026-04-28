"""Shared driver + config dataclass for the eight draft-cycle tier generation handlers.

Phase A foundation: this module is purely additive — none of the
existing per-tier handlers call into it yet. Phase B and C migrate
tiers one by one. See ``/root/.claude/plans/let-s-plan-phase-11-enchanted-book.md``
for the consolidation plan.

What lives here:

* :class:`TierGenerationConfig` — frozen dataclass holding every
  tier-specific knob the driver needs.
* :class:`TierState` — protocol the per-tier ``gather_state`` callable
  returns. Each tier subclasses with its own typed bundle.
* :func:`run_tier_generation` — async driver that owns the pipeline:
  validate payload → fail fast on readiness → gather state → render →
  parse-validate loop → persist → fire post-persist hooks → maybe
  re-enqueue for next auto-revision pass.
* :func:`is_ready_to_generate` — uniform predicate dispatching to the
  config's bespoke ``readiness_check`` (or returning ``True`` when
  none is set).
* :func:`_run_auto_revision_pass`, :func:`_format_findings_as_feedback`,
  :func:`_enqueue_async_review_retroactively` — lifted from
  ``requirements_generation.py`` so any tier can opt into the inline
  review-then-regen loop via ``max_auto_revisions: int``.
* :class:`TierPreconditionError` — raised by the driver when readiness
  fails and the failure should mark the job failed.
* :class:`TierDeferredError` — Phase F: raised when the work should
  retry once readiness flips true (e.g. comparch waiting on a dep
  comparch's regen). The worker catches this and completes the job
  cleanly without recording a failure; a wakeup hook re-enqueues.

The driver delegates the parse-validate retry loop to
:func:`backend.graph.handlers._bootstrap_generation.run_parse_validate_loop`
and the persist transaction to
:func:`backend.graph.handlers._bootstrap_generation.persist_draft`,
both of which already factor the heavy machinery shared across tiers.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, Protocol

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from backend.cli.manager import CliInvocationConfig
    from backend.graph.parsers.review_xml import ParsedReview
    from backend.graph.parsers.xml_sections import TagNode

logger = logging.getLogger(__name__)


# Hard cap on auto-revision passes. Lifted from
# ``requirements_generation.py`` so every tier opting into the loop
# shares a single ceiling.
MAX_AUTO_REVISIONS = 5


ScopeIds = tuple[str, ...]


class TierPreconditionError(RuntimeError):
    """Readiness predicate returned ``(False, ...)`` and the job should fail.

    Used for hard preconditions that won't flip true on their own
    (e.g. sysarch with zero approved resps — the upstream tier needs
    user attention before the regen can usefully run). The worker
    marks the job failed with this error's message.
    """


class TierDeferredError(RuntimeError):
    """Readiness predicate returned ``(False, ...)`` but should retry later.

    Phase F: comparch waiting on a dep comparch's in-flight regen
    raises this. The worker completes the job cleanly (no failure
    recorded), the staleness ledger row stays, and a wakeup hook
    re-enqueues when the dependency settles.
    """


class TierState(Protocol):
    """Protocol for the per-tier state bundle returned by ``gather_state``.

    Each tier defines its own dataclass (e.g. ``SysarchState``) that
    satisfies this protocol plus its own per-tier fields. The driver
    only reads the protocol fields; the per-tier ``render_prompt`` and
    ``validate`` callables read the full bundle.
    """

    node_id: str
    prior_approved: str | None
    prior_pending: str | None
    prior_pending_id: str | None
    cli_config: CliInvocationConfig
    system_prompt: str


@dataclass(frozen=True)
class PostPersistContext:
    """Lifecycle metadata passed to ``post_persist_hooks``.

    ``is_terminal`` is ``True`` when this persist is the final
    write for the user-facing regen — either auto-revision is
    disabled (``max_auto_revisions=0``), or this is the last pass
    of the auto-revision loop (``auto_revisions_remaining == 0``).
    Hooks that should only fire once per user-visible regen (e.g.
    Phase F's comparch wakeup, which would otherwise re-fire on
    every auto-revision intermediate) should gate on this.

    Hooks that should fire on every persist (e.g. impl-approval
    fan-in enqueue, if it ever migrates here) ignore the field.
    """

    auto_revision_pass: int
    auto_revisions_remaining: int
    is_terminal: bool


# Type aliases for the per-tier callables. Defined at module scope so
# the dataclass field annotations stay readable.
GatherStateFn = Callable[["Session", str, ScopeIds], TierState]
RenderPromptFn = Callable[..., str]
ValidateFn = Callable[["TagNode", str, TierState], None]
ReadinessCheckFn = Callable[["Session", str, ScopeIds], tuple[bool, str]]
PostPersistHookFn = Callable[["Session", str, str, ScopeIds, PostPersistContext], None]


@dataclass(frozen=True)
class TierGenerationConfig:
    """Per-tier configuration for the shared generation driver.

    See module docstring for the full picture. Required fields are
    declared first; optional fields with defaults follow.
    """

    tier_name: str
    generate_job_type: str
    section: str
    root_tag: str
    exhausted_exception_cls: type[Exception]
    gather_state: GatherStateFn
    render_prompt: RenderPromptFn
    validate: ValidateFn
    review_job_type: str = ""
    scope_payload_keys: tuple[str, ...] = ()
    thinking_effort: Literal["max"] | None = None
    max_auto_revisions: int = 0
    readiness_check: ReadinessCheckFn | None = None
    post_persist_hooks: tuple[PostPersistHookFn, ...] = ()


def is_ready_to_generate(
    config: TierGenerationConfig,
    db: "Session",
    project_id: str,
    scope_ids: ScopeIds,
) -> tuple[bool, str]:
    """Uniform readiness check.

    Delegates to the config's bespoke ``readiness_check`` when set;
    otherwise returns ``(True, "")`` and the driver proceeds. The
    bespoke predicate decides between "fail fast" (raise
    :class:`TierPreconditionError`) and "defer for later"
    (raise :class:`TierDeferredError`) by signaling through the
    reason string — see :func:`run_tier_generation` for the dispatch.
    """
    if config.readiness_check is None:
        return (True, "")
    return config.readiness_check(db, project_id, scope_ids)


async def run_tier_generation(
    payload: dict[str, Any],
    config: TierGenerationConfig,
) -> None:
    """Async driver for one tier-generation pass.

    Phase A: this driver is shipped but not yet wired into any
    handler. Phase B/C migrate handlers in to call it.

    Pipeline phases:

    1. Parse payload (project_id, scope_ids, feedback, prior_review,
       auto-revision counters).
    2. Readiness gate via :func:`is_ready_to_generate`. Bespoke
       predicates raise :class:`TierPreconditionError` (fail) or
       :class:`TierDeferredError` (retry later) by raising directly,
       OR the predicate returns ``(False, reason)`` and the driver
       converts it to ``TierPreconditionError``. Phase F's readiness
       checks raise the typed errors directly when they want the
       deferred-retry semantics.
    3. Gather state via the config's ``gather_state`` callable. Runs
       in its own session that closes before the LLM call so the
       session isn't held across the network round-trip.
    4. Run the parse-validate retry loop via the existing shared
       ``run_parse_validate_loop`` helper.
    5. Persist via the existing shared ``persist_draft`` helper. The
       driver tags ``prior_discard_reason="auto_revision"`` when
       this pass is itself an auto-revision intermediate, and
       suppresses the async review enqueue while the inline loop is
       still running.
    6. Fire the config's ``post_persist_hooks`` in declared order.
       Hook errors are logged + swallowed so a faulty hook doesn't
       fail the whole job. Hooks run before the auto-revision check
       so a hook that mutates state (e.g. impl approval enqueueing
       fan-in) runs even on auto-revision intermediates.
    7. Auto-revision continuation: when ``max_auto_revisions > 0``
       and ``auto_revisions_remaining > 0``, run one inline review
       pass and (if it surfaces findings) re-enqueue the next
       generate.
    """
    from backend.database import SessionLocal
    from backend.graph.handlers._bootstrap_generation import (
        persist_draft,
        run_parse_validate_loop,
    )

    project_id, scope_ids, feedback, prior_review, auto_pass, auto_remaining = _parse_payload(
        payload, config
    )
    auto_remaining = min(auto_remaining, MAX_AUTO_REVISIONS)

    # Phase 1: readiness gate.
    db = SessionLocal()
    try:
        ready, reason = is_ready_to_generate(config, db, project_id, scope_ids)
    finally:
        db.close()
    if not ready:
        # Phase F: predicates that want the retry-later semantics
        # produce a reason string starting with "deferred —". The
        # driver maps that to :class:`TierDeferredError` so the
        # worker completes cleanly and a wakeup hook re-enqueues.
        # Everything else maps to :class:`TierPreconditionError`
        # (hard fail; the row records a failure).
        if reason.lstrip().startswith("deferred"):
            raise TierDeferredError(f"{config.tier_name}: {reason}")
        raise TierPreconditionError(f"{config.tier_name}: {reason}")

    # Phase 2: gather state. Closes before the LLM call.
    db = SessionLocal()
    try:
        state = config.gather_state(db, project_id, scope_ids)
    finally:
        db.close()

    logger.info(
        "%s project=%s scope=%s prior_pending=%s feedback=%s "
        "prior_review=%s auto_pass=%d auto_remaining=%d",
        f"generate_{config.tier_name}",
        project_id,
        scope_ids,
        bool(state.prior_pending),
        bool(feedback),
        bool(prior_review),
        auto_pass,
        auto_remaining,
    )

    # Phase 3: parse-validate loop.
    def _render(*, prior_pending: str | None, parse_error: str | None) -> str:
        return config.render_prompt(
            state,
            prior_pending=prior_pending,
            parse_error=parse_error,
            feedback=feedback,
            prior_review=prior_review,
        )

    def _validate(tree: "TagNode", raw: str) -> None:
        config.validate(tree, raw, state)

    validated, attempts = await run_parse_validate_loop(
        root_tag=config.root_tag,
        system_prompt=state.system_prompt,
        cli_config=state.cli_config,
        prior_pending=state.prior_pending,
        render_prompt=_render,
        validate=_validate,
        exhausted_exception_cls=config.exhausted_exception_cls,
        log_handler_name=f"generate_{config.tier_name}",
    )

    # Phase 4: persist + telemetry. ``persist_draft`` opens its own
    # session and returns the new draft id.
    new_draft_id = persist_draft(
        project_id=project_id,
        node_id=state.node_id,
        section=config.section,
        validated_output=validated,
        attempts=attempts,
        prior_pending_id=state.prior_pending_id,
        log_handler_name=f"generate_{config.tier_name}",
        review_job_type=config.review_job_type,
        prior_discard_reason="auto_revision" if auto_pass > 0 else "user_regen",
        enqueue_async_review=(auto_remaining == 0),
    )

    # Phase 5: post-persist hooks. Errors logged + swallowed.
    if config.post_persist_hooks:
        # ``is_terminal`` is True when auto-revision is disabled
        # OR this pass is the final pass of the loop. Hooks that
        # should only fire once per user-visible regen (Phase F's
        # comparch wakeup is the load-bearing example) gate on it.
        post_ctx = PostPersistContext(
            auto_revision_pass=auto_pass,
            auto_revisions_remaining=auto_remaining,
            is_terminal=(auto_remaining == 0),
        )
        db = SessionLocal()
        try:
            for hook in config.post_persist_hooks:
                try:
                    hook(db, project_id, new_draft_id, scope_ids, post_ctx)
                except Exception:  # noqa: BLE001 — hook isolation
                    logger.exception(
                        "post_persist_hook failed for tier=%s draft=%s",
                        config.tier_name,
                        new_draft_id,
                    )
        finally:
            db.close()

    # Phase 6: auto-revision continuation.
    if config.max_auto_revisions > 0 and auto_remaining > 0:
        await _run_auto_revision_pass(
            config=config,
            project_id=project_id,
            scope_ids=scope_ids,
            node_id=state.node_id,
            draft_id=new_draft_id,
            current_pass=auto_pass,
            remaining=auto_remaining,
        )


def _parse_payload(
    payload: dict[str, Any],
    config: TierGenerationConfig,
) -> tuple[str, ScopeIds, str | None, str | None, int, int]:
    """Pull the standard fields out of a generation job payload."""
    project_id = payload.get("project_id")
    if not isinstance(project_id, str) or not project_id:
        raise ValueError(f"{config.generate_job_type} payload missing project_id")
    scope_ids: list[str] = []
    for key in config.scope_payload_keys:
        value = payload.get(key)
        if not isinstance(value, str) or not value:
            raise ValueError(f"{config.generate_job_type} payload missing {key}")
        scope_ids.append(value)
    feedback = payload.get("feedback")
    if feedback is not None and not isinstance(feedback, str):
        feedback = None
    prior_review = payload.get("prior_review_text")
    if not isinstance(prior_review, str) or not prior_review.strip():
        prior_review = None
    auto_pass = int(payload.get("auto_revision_pass") or 0)
    auto_remaining = int(payload.get("auto_revisions_remaining") or 0)
    return project_id, tuple(scope_ids), feedback, prior_review, auto_pass, auto_remaining


async def _run_auto_revision_pass(
    *,
    config: TierGenerationConfig,
    project_id: str,
    scope_ids: ScopeIds,
    node_id: str,
    draft_id: str,
    current_pass: int,
    remaining: int,
) -> None:
    """Run one inline AI review and enqueue the next generate pass.

    Lifted verbatim from ``requirements_generation._run_auto_revision_pass``,
    generalized over ``config`` so any tier with a registered
    ``review_job_type`` and ``max_auto_revisions > 0`` can opt in.

    Stop conditions (each falls back to enqueueing the standard
    async review so the user still sees a reviewed draft):

    * No ``review_job_type`` registered — nothing to call inline.
    * Review handler raises — log and bail to async review.
    * Review parses but has zero findings — chain is done.
    * Findings exist — format as feedback, enqueue next generate
      with ``auto_revisions_remaining - 1`` and
      ``auto_revision_pass = current_pass + 1``.
    """
    from backend.database import SessionLocal
    from backend.graph.parsers.review_xml import (
        ReviewXMLError,
        parse_review,
    )
    from backend.models.node import Draft
    from backend.pipeline import queue as pipeline_queue

    if not config.review_job_type:
        # Tier opted into auto-revision but has no review handler —
        # configuration bug. Log + bail; persist_draft already
        # suppressed the async review enqueue thinking the inline
        # path would handle it, so we don't have a path to recover.
        logger.error(
            "%s: max_auto_revisions=%d but review_job_type is unset; skipping auto-revision pass",
            config.tier_name,
            config.max_auto_revisions,
        )
        return

    inline_review = pipeline_queue._JOB_HANDLERS.get(config.review_job_type)
    if inline_review is None:
        logger.error(
            "%s: review_job_type=%s not registered; cannot run auto-revision inline review",
            config.tier_name,
            config.review_job_type,
        )
        _enqueue_async_review_retroactively(project_id, node_id, draft_id, config.review_job_type)
        return

    try:
        await inline_review(
            {
                "project_id": project_id,
                "node_id": node_id,
                "draft_id": draft_id,
            }
        )
    except Exception:  # noqa: BLE001 — collapse chain on any review failure
        logger.exception(
            "Inline auto-revision review failed for tier=%s project=%s draft=%s; "
            "collapsing revision chain and enqueueing async review",
            config.tier_name,
            project_id,
            draft_id,
        )
        _enqueue_async_review_retroactively(project_id, node_id, draft_id, config.review_job_type)
        return

    # Fetch the review_text the inline review just committed.
    db = SessionLocal()
    try:
        draft = db.get(Draft, draft_id)
        review_text = draft.review_text if draft is not None else ""
    finally:
        db.close()

    if not review_text or not review_text.strip():
        logger.info(
            "Auto-revision review produced no text for tier=%s; stopping chain "
            "(project=%s draft=%s)",
            config.tier_name,
            project_id,
            draft_id,
        )
        return

    try:
        parsed = parse_review(review_text)
    except ReviewXMLError:
        logger.exception(
            "Auto-revision review failed to parse for tier=%s; stopping chain "
            "(project=%s draft=%s)",
            config.tier_name,
            project_id,
            draft_id,
        )
        return

    all_findings = list(parsed.handles_structure) + list(parsed.architectural_decisions)
    if not all_findings:
        logger.info(
            "Auto-revision review has no findings for tier=%s; stopping chain "
            "(project=%s draft=%s)",
            config.tier_name,
            project_id,
            draft_id,
        )
        return

    formatted = _format_findings_as_feedback(parsed)
    next_payload: dict[str, Any] = {
        "project_id": project_id,
        "feedback": formatted,
        "auto_revision_pass": current_pass + 1,
        "auto_revisions_remaining": remaining - 1,
    }
    # Re-thread the scope payload keys so per-component / per-owner
    # tiers re-enqueue against the same scope.
    for key, value in zip(config.scope_payload_keys, scope_ids, strict=True):
        next_payload[key] = value

    db = SessionLocal()
    try:
        pipeline_queue.enqueue(
            db,
            job_type=config.generate_job_type,
            payload=next_payload,
        )
        db.commit()
    finally:
        db.close()
    logger.info(
        "Auto-revision pass %d enqueued for tier=%s project=%s (remaining=%d)",
        current_pass + 1,
        config.tier_name,
        project_id,
        remaining - 1,
    )


def _enqueue_async_review_retroactively(
    project_id: str,
    node_id: str,
    draft_id: str,
    review_job_type: str,
) -> None:
    """Enqueue a regular async review against ``draft_id``.

    Used by the auto-revision collapse path when the inline review
    errored — ``persist_draft`` suppressed the async review enqueue
    on the assumption the inline path would own reviewing this
    draft. When that assumption falls through, we still want the
    user to see a reviewed draft, so re-enqueue here.
    """
    import os

    if os.environ.get("SIEGE_DISABLE_AI_REVIEW") == "1":
        return
    from backend.database import SessionLocal
    from backend.pipeline import queue as pipeline_queue

    db = SessionLocal()
    try:
        pipeline_queue.enqueue(
            db,
            job_type=review_job_type,
            payload={
                "project_id": project_id,
                "node_id": node_id,
                "draft_id": draft_id,
            },
            priority=pipeline_queue.REVIEW_JOB_PRIORITY,
        )
        db.commit()
    finally:
        db.close()


def _format_findings_as_feedback(parsed: "ParsedReview") -> str:
    """Turn a parsed review into prose the generator prompt consumes.

    Mirrors the frontend's ``formatSelectedAsFeedback`` (lib/
    reviewXml.ts): grouped per section with a bulleted finding
    list, sections separated by blank lines. Every finding is
    included — the auto-revision loop trusts the review's critique
    in aggregate rather than picking among individual findings (the
    user's "Apply selected" UI path is orthogonal and feeds user-
    initiated regens, not auto-revisions).
    """
    lines: list[str] = []
    if parsed.handles_structure:
        lines.append("Handles & structure:")
        for f in parsed.handles_structure:
            lines.append(f"- {f.text}")
        lines.append("")
    if parsed.architectural_decisions:
        lines.append("Architectural decisions:")
        for f in parsed.architectural_decisions:
            lines.append(f"- {f.text}")
        lines.append("")
    return "\n".join(lines).rstrip()
