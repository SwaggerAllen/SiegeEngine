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
import secrets
import uuid

from backend.database import SessionLocal
from backend.graph import events as ev
from backend.graph.handlers._bootstrap_generation import run_parse_validate_loop
from backend.graph.parsers.validators import validate_requirements
from backend.graph.prompts.requirements import (
    format_features_summary,
    render_system_prompt,
    render_user_prompt,
)
from backend.graph.reducer import append_event
from backend.graph.requirements import (
    get_reqs_node,
    pending_reqs_draft,
)
from backend.models import Project
from backend.models.node import Node
from backend.models.telemetry import GenerationTelemetry
from backend.pipeline import queue as pipeline_queue
from backend.projects.settings import get_project_settings

logger = logging.getLogger(__name__)

GENERATE_REQUIREMENTS_JOB_TYPE = "v2.generate_requirements"


class RequirementsHandlerError(RuntimeError):
    """Raised when the handler cannot proceed because of missing state."""


class RequirementsParseRetryExhausted(RuntimeError):
    """Raised when parse-validate retries are exhausted without success."""


def _new_draft_id() -> str:
    return f"draft_{secrets.token_hex(8)}"


def _new_batch_id() -> str:
    return f"batch_{uuid.uuid4().hex[:16]}"


async def generate_requirements(payload: dict) -> None:
    """Job handler for ``v2.generate_requirements``.

    Payload shape: ``{"project_id": str, "feedback": str | None}``.
    """
    project_id = payload.get("project_id")
    if not isinstance(project_id, str) or not project_id:
        raise RequirementsHandlerError("generate_requirements payload missing project_id")
    feedback: str | None = payload.get("feedback")

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
        feature_rows = (
            db.query(Node)
            .filter(Node.project_id == project_id, Node.tier == "feat")
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

        project_row = db.get(Project, project_id)
        assert project_row is not None
        settings = get_project_settings(project_row)
        cli_timeout_seconds = settings.generation_timeout_seconds
        system_prompt = render_system_prompt(settings.top_level_responsibilities)
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
        )

    def _validate(tree, _raw_text) -> None:  # type: ignore[no-untyped-def]
        validate_requirements(tree, known_feature_ids=known_feature_ids)

    validated_output, attempts = await run_parse_validate_loop(
        root_tag="requirements",
        system_prompt=system_prompt,
        cli_timeout_seconds=cli_timeout_seconds,
        prior_pending=prior_pending,
        render_prompt=_render,
        validate=_validate,
        exhausted_exception_cls=RequirementsParseRetryExhausted,
        log_handler_name="generate_requirements",
    )

    # ── Phase 3: persist events + telemetry ─────────────────────────
    db = SessionLocal()
    try:
        if prior_pending_id is not None:
            append_event(
                db,
                project_id,
                ev.DraftDiscarded(draft_id=prior_pending_id),
            )

        new_draft_id = _new_draft_id()
        new_batch_id = _new_batch_id()
        append_event(
            db,
            project_id,
            ev.DraftGenerated(
                draft_id=new_draft_id,
                target_type="node",
                target_id=reqs_node_id,
                content=validated_output.text,
                batch_id=new_batch_id,
            ),
        )
        for attempt in attempts:
            db.add(
                GenerationTelemetry(
                    project_id=project_id,
                    node_id=reqs_node_id,
                    section="requirements",
                    model=attempt.model,
                    prompt_tokens=attempt.prompt_tokens,
                    completion_tokens=attempt.completion_tokens,
                )
            )
        db.commit()
        logger.info(
            "generate_requirements project=%s draft_id=%s committed "
            "(attempts=%d final_prompt=%d final_completion=%d model=%s)",
            project_id,
            new_draft_id,
            len(attempts),
            validated_output.prompt_tokens,
            validated_output.completion_tokens,
            validated_output.model,
        )
    finally:
        db.close()


def register() -> None:
    """Register the handler with the pipeline job queue.

    Called at import time so the pipeline worker always has a
    handler for the job type.
    """
    pipeline_queue.register_handler(
        GENERATE_REQUIREMENTS_JOB_TYPE,
        generate_requirements,
    )
