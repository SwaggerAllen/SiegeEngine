"""Requirements generation handler.

Registered on the pipeline job queue as
``v2.generate_requirements``. The payload is
``{"project_id": str, "feedback": str | None}``.

Shape is deliberately parallel to
:mod:`backend.graph.handlers.feature_expansion`:

1. Open a DB session, load inputs (reqs node, current pending
   draft if any, feedback, project settings, **the full list of
   approved ``feat_*`` nodes** formatted as the features summary
   the prompt needs). Close the session before the LLM call.
2. Run :func:`_call_cli_with_transient_retry` wrapped in the
   parse-validate retry loop from the feature-expansion flow,
   with the requirements-specific prompt + validator.
3. On success, open a fresh session, append ``DraftDiscarded``
   (if a prior pending existed) + ``DraftGenerated`` + per-call
   telemetry, and commit.

Parse-validate lives at generation time — as with expansion — so
the user only ever sees drafts that already parse and validate
cleanly, and downstream consumers (``v2.mint_requirements``) can
trust approved content.

Transient-CLI-error retry is shared with the feature-expansion
handler via ``_call_cli_with_transient_retry``. The parse-validate
retry budget and the transient-error retry budget are both
module-level constants on
:mod:`backend.graph.handlers.feature_expansion`; this handler
does not duplicate them.

See ``docs/architecture/v2-roadmap.md`` Phase 3.
"""

from __future__ import annotations

import logging

from backend.database import SessionLocal
from backend.graph.handlers._bootstrap_generation import (
    persist_draft,
    run_parse_validate_loop,
)
from backend.graph.parsers.review_xml import ParsedReview, ReviewXMLError, parse_review
from backend.graph.parsers.validators import ValidationError, validate_requirements
from backend.graph.prompts.requirements import (
    format_features_summary,
    render_system_prompt,
    render_user_prompt,
)
from backend.graph.requirements import (
    get_reqs_node,
    pending_reqs_draft,
)
from backend.models import Project
from backend.models.input_document import InputDocument
from backend.models.node import Draft, Node
from backend.pipeline import queue as pipeline_queue
from backend.projects.settings import get_project_settings

logger = logging.getLogger(__name__)

GENERATE_REQUIREMENTS_JOB_TYPE = "v2.generate_requirements"
REVIEW_REQUIREMENTS_JOB_TYPE = "v2.review_requirements"

# Phase 12 auto-revision — hard cap on how many AI-driven revision
# passes a single user Reject & Regenerate can trigger. Prevents
# runaway loops from a user input that overflows the UI stepper.
MAX_AUTO_REVISIONS = 5


class RequirementsHandlerError(RuntimeError):
    """Raised when the handler cannot proceed because of missing state."""


class RequirementsParseRetryExhausted(RuntimeError):
    """Raised when parse-validate retries are exhausted without success."""


async def generate_requirements(payload: dict) -> None:
    """Job handler for ``v2.generate_requirements``.

    Payload shape:
    ``{
        "project_id": str,
        "feedback": str | None,
        "auto_revision_pass": int | None,         # default 0
        "auto_revisions_remaining": int | None,   # default 0
    }``.

    ``auto_revision_pass`` is the 0-indexed position of this pass
    within the current run. ``0`` is user-initiated (the prior
    pending draft is a user-visible baseline that should be
    discarded with ``reason="user_regen"``). ``>0`` is an
    auto-revision intermediate landing on top of another
    auto-revision intermediate, discarded with
    ``reason="auto_revision"``.

    ``auto_revisions_remaining`` is the count of additional passes
    the user asked for. When this pass lands and remaining is
    ``>0``, the handler runs an inline AI review against the new
    draft, formats the findings as feedback, and enqueues the next
    generate job with ``auto_revisions_remaining - 1``. When
    remaining is ``0`` the handler takes the default path and
    enqueues the async review job; the user sees the pending draft
    and reviews it.
    """
    project_id = payload.get("project_id")
    if not isinstance(project_id, str) or not project_id:
        raise RequirementsHandlerError("generate_requirements payload missing project_id")
    feedback: str | None = payload.get("feedback")
    auto_revision_pass = int(payload.get("auto_revision_pass") or 0)
    auto_revisions_remaining = int(payload.get("auto_revisions_remaining") or 0)
    # Clamp to the hard cap — defends against a bad payload that
    # slipped past the route layer's input validation.
    if auto_revisions_remaining > MAX_AUTO_REVISIONS:
        auto_revisions_remaining = MAX_AUTO_REVISIONS

    # ── Phase 1: gather inputs ──────────────────────────────────────
    db = SessionLocal()
    try:
        node = get_reqs_node(db, project_id)
        if node is None:
            raise RequirementsHandlerError(
                f"Project {project_id!r} has no reqs node; "
                "was bootstrap_reqs_node called at mint_features time?"
            )
        reqs_node_id: str = node.id
        prior_approved: str | None = node.content or None

        pending = pending_reqs_draft(db, project_id)
        prior_pending: str | None = pending.content if pending else None
        prior_pending_id: str | None = pending.id if pending else None

        # The features the LLM will read out of the prompt. Ordered
        # by display_order so it mirrors the frontend's rendering.
        # Phase-11 followup B7: filter out deferred features so
        # requirements doesn't design structure for capabilities
        # the user has parked.
        feature_rows = (
            db.query(Node)
            .filter(
                Node.project_id == project_id,
                Node.tier == "feat",
                Node.is_deferred.is_(False),
            )
            .order_by(Node.display_order, Node.created_at)
            .all()
        )
        features_summary = format_features_summary(
            [
                {
                    "id": f.id,
                    "name": f.name,
                    "content": f.content,
                    "group_label": f.group_label,
                    "is_implicit": f.is_implicit,
                }
                for f in feature_rows
            ]
        )
        # The validator needs to check <covers> references against
        # the actual mint state, not what the prompt happened to
        # list. Handlers collect these once up front and pass them
        # through the parse-validate retry loop.
        known_feature_ids: set[str] = {f.id for f in feature_rows}

        # Project vocabulary context — always included. Requirements
        # regen reasons across the whole feature set at once, so
        # it should see every defined term regardless of which
        # feature owns it.
        from backend.graph.vocabulary import render_vocab_summary_all

        vocab_summary = render_vocab_summary_all(db, project_id)

        # Referenced content — any ``reference`` edges the reqs node
        # has pointing outward. Empty in the common case; plumbed so
        # users can attach standalone refs to the reqs tier.
        from backend.graph.references import render_referenced_content_summary

        referenced_content_summary = render_referenced_content_summary(db, project_id, reqs_node_id)

        # Project input document — fed unconditionally on every
        # requirements generation. This handler never runs against
        # approved state (the route at
        # ``POST /api/projects/{id}/requirements/generate`` blocks
        # with 409 once the reqs node is approved — see
        # ``backend/graph/routes.py``), so every invocation is
        # either an initial generation or a pre-approval feedback
        # iteration on a pending draft. Both need the original
        # framing: the initial pass to shape character from scratch,
        # later iterations to avoid drifting away from the source
        # of truth as the user refines the draft.
        input_doc_row = (
            db.query(InputDocument)
            .filter(
                InputDocument.project_id == project_id,
                InputDocument.doc_type == "project_doc",
            )
            .order_by(InputDocument.created_at.desc())
            .first()
        )
        input_doc = (input_doc_row.content or "") if input_doc_row else ""

        project_row = db.get(Project, project_id)
        assert project_row is not None
        settings = get_project_settings(project_row)
        cli_timeout_seconds = settings.generation_timeout_seconds
        cli_max_budget_usd = settings.cli_max_budget_usd
        system_prompt = render_system_prompt()
    finally:
        db.close()

    # ── Phase 2: LLM call + parse-validate retry loop ───────────────
    logger.info(
        "generate_requirements project=%s prior_pending=%s feedback=%s features=%d",
        project_id,
        bool(prior_pending),
        bool(feedback),
        len(feature_rows),
    )

    def _render(*, prior_pending: str | None, parse_error: str | None) -> str:
        return render_user_prompt(
            features_summary=features_summary,
            prior_approved=prior_approved,
            prior_pending=prior_pending,
            feedback=feedback,
            parse_error=parse_error,
            vocab_summary=vocab_summary,
            input_doc=input_doc,
            referenced_content_summary=referenced_content_summary,
        )

    def _validate(tree, raw_text) -> None:  # type: ignore[no-untyped-def]
        # Phase-11 followup B4: <introduction> sibling block is
        # required so subsequent regens have the tier's own initial
        # thinking available via prior_pending / prior_approved.
        if "<introduction" not in raw_text:
            raise ValidationError(
                "Output is missing the required <introduction> block. "
                "Every requirements draft must open with a short prose "
                "<introduction> capturing the initial decomposition "
                "thinking. Put it before the <requirements> block."
            )
        validate_requirements(tree, known_feature_ids=known_feature_ids)

    validated_output, attempts = await run_parse_validate_loop(
        root_tag="requirements",
        system_prompt=system_prompt,
        cli_timeout_seconds=cli_timeout_seconds,
        cli_max_budget_usd=cli_max_budget_usd,
        prior_pending=prior_pending,
        render_prompt=_render,
        validate=_validate,
        exhausted_exception_cls=RequirementsParseRetryExhausted,
        log_handler_name="generate_requirements",
        # B6 — top-of-chain tier runs at max thinking effort.
        thinking_effort="max",
    )

    new_draft_id = persist_draft(
        project_id=project_id,
        node_id=reqs_node_id,
        section="requirements",
        validated_output=validated_output,
        attempts=attempts,
        prior_pending_id=prior_pending_id,
        log_handler_name="generate_requirements",
        review_job_type=REVIEW_REQUIREMENTS_JOB_TYPE,
        # Auto-revision intermediates get tagged so the regen-time
        # diff skips them as "before" baselines — the user's
        # pre-regen view stays anchored to the last user-visible
        # pending draft, not to each mid-loop pass.
        prior_discard_reason=("auto_revision" if auto_revision_pass > 0 else "user_regen"),
        # Skip the async review when more passes are coming — the
        # inline review below produces the feedback that feeds the
        # next generate, and the final pass (remaining == 0) is
        # the one that enqueues the standard async review.
        enqueue_async_review=(auto_revisions_remaining == 0),
    )

    # Phase 12 — auto-revision loop. Run a review inline against
    # the just-persisted draft, format its findings as feedback,
    # and enqueue the next generate pass. Errors / empty findings
    # collapse the loop and enqueue the async review so the user
    # still gets the normal review experience for this draft.
    if auto_revisions_remaining > 0:
        await _run_auto_revision_pass(
            project_id=project_id,
            node_id=reqs_node_id,
            draft_id=new_draft_id,
            current_pass=auto_revision_pass,
            remaining=auto_revisions_remaining,
        )


async def _run_auto_revision_pass(
    *,
    project_id: str,
    node_id: str,
    draft_id: str,
    current_pass: int,
    remaining: int,
) -> None:
    """Run one inline AI review and enqueue the next generate pass.

    Stop conditions (each falls back to enqueueing the standard
    async review so the user still sees a reviewed draft):

    * Review CLI failure / empty output — log and bail.
    * Review parses but has zero findings — nothing to revise
      against, so the chain is done.
    * Findings exist — format as feedback, enqueue next generate
      with ``auto_revisions_remaining - 1`` and
      ``auto_revision_pass = current_pass + 1``.
    """
    from backend.graph.handlers.review_requirements import review_requirements

    try:
        await review_requirements(
            {
                "project_id": project_id,
                "node_id": node_id,
                "draft_id": draft_id,
            }
        )
    except Exception:
        logger.exception(
            "Inline auto-revision review failed for project=%s draft=%s; "
            "collapsing revision chain and enqueueing async review",
            project_id,
            draft_id,
        )
        _enqueue_async_review_retroactively(project_id, node_id, draft_id)
        return

    # Fetch the review_text the inline review just committed.
    db = SessionLocal()
    try:
        draft = db.get(Draft, draft_id)
        review_text = draft.review_text if draft is not None else ""
    finally:
        db.close()

    if not review_text.strip():
        # Shouldn't happen — ``run_review`` raises on empty CLI
        # output — but guard anyway so the chain collapses cleanly.
        logger.info(
            "Auto-revision review produced no text; stopping chain (project=%s draft=%s)",
            project_id,
            draft_id,
        )
        return

    try:
        parsed = parse_review(review_text)
    except ReviewXMLError:
        logger.exception(
            "Auto-revision review failed to parse; stopping chain (project=%s draft=%s)",
            project_id,
            draft_id,
        )
        return

    all_findings = list(parsed.handles_structure) + list(parsed.architectural_decisions)
    if not all_findings:
        logger.info(
            "Auto-revision review has no findings; stopping chain (project=%s draft=%s)",
            project_id,
            draft_id,
        )
        return

    formatted = _format_findings_as_feedback(parsed)
    db = SessionLocal()
    try:
        pipeline_queue.enqueue(
            db,
            job_type=GENERATE_REQUIREMENTS_JOB_TYPE,
            payload={
                "project_id": project_id,
                "feedback": formatted,
                "auto_revision_pass": current_pass + 1,
                "auto_revisions_remaining": remaining - 1,
            },
        )
        db.commit()
    finally:
        db.close()
    logger.info(
        "Auto-revision pass %d enqueued for project=%s (remaining=%d)",
        current_pass + 1,
        project_id,
        remaining - 1,
    )


def _enqueue_async_review_retroactively(
    project_id: str,
    node_id: str,
    draft_id: str,
) -> None:
    """Enqueue a regular async review against ``draft_id``.

    Used by the auto-revision collapse path when the inline review
    errored — we suppressed the async review enqueue during
    ``persist_draft`` on the assumption the inline path would own
    reviewing this draft. When that assumption falls through, we
    still want the user to see a reviewed draft, so re-enqueue
    here via the normal job pipeline.
    """
    import os

    if os.environ.get("SIEGE_DISABLE_AI_REVIEW") == "1":
        return
    db = SessionLocal()
    try:
        pipeline_queue.enqueue(
            db,
            job_type=REVIEW_REQUIREMENTS_JOB_TYPE,
            payload={
                "project_id": project_id,
                "node_id": node_id,
                "draft_id": draft_id,
            },
        )
        db.commit()
    finally:
        db.close()


def _format_findings_as_feedback(parsed: ParsedReview) -> str:
    """Turn a parsed review into prose the generator prompt consumes.

    Mirrors the frontend's ``formatSelectedAsFeedback`` (lib/
    reviewXml.ts): grouped per section with a bulleted finding
    list, sections separated by blank lines. Every finding is
    included — the auto-revision loop trusts the review's
    critique in aggregate rather than picking among individual
    findings (the user's "Apply selected" UI path is orthogonal
    and feeds user-initiated regens, not auto-revisions).
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
    return "\n".join(lines).strip()


def register() -> None:
    """Register the handler with the pipeline job queue.

    Called at import time so the pipeline worker always has a
    handler for the job type.
    """
    pipeline_queue.register_handler(
        GENERATE_REQUIREMENTS_JOB_TYPE,
        generate_requirements,
    )
