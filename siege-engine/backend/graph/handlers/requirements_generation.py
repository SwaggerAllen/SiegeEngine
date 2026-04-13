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
from backend.graph.handlers.feature_expansion import (
    CLI_MAX_BUDGET_USD,
    CLI_TOOLS,
    MAX_PARSE_RETRIES,
    _call_cli_with_transient_retry,
)
from backend.graph.parsers.validators import (
    ValidationError,
    validate_requirements,
)
from backend.graph.parsers.xml_sections import ParseError, extract_tag_tree
from backend.graph.prompts.requirements import (
    SYSTEM_PROMPT,
    format_features_summary,
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
                    "name": f.name,
                    "content": f.content,
                    "group_label": f.group_label,
                    "is_implicit": f.is_implicit,
                }
                for f in feature_rows
            ]
        )

        project_row = db.get(Project, project_id)
        assert project_row is not None
        settings = get_project_settings(project_row)
        cli_timeout_seconds = settings.generation_timeout_seconds
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
    validated_output, attempts = await _generate_with_parse_validate(
        features_summary=features_summary,
        prior_approved=prior_approved,
        prior_pending=prior_pending,
        feedback=feedback,
        cli_timeout_seconds=cli_timeout_seconds,
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


async def _generate_with_parse_validate(
    *,
    features_summary: str,
    prior_approved: str | None,
    prior_pending: str | None,
    feedback: str | None,
    cli_timeout_seconds: int,
):  # type: ignore[no-untyped-def]
    """Run the requirements LLM call with a parse-validate retry loop.

    Same shape as
    :func:`backend.graph.handlers.feature_expansion._generate_with_parse_validate`
    but with the requirements prompt and validator. Shares the
    ``MAX_PARSE_RETRIES`` budget so both handlers stay symmetric.
    """
    attempts: list = []  # list[GenerationResult]
    parse_error: str | None = None

    for attempt_idx in range(MAX_PARSE_RETRIES + 1):
        effective_prior_pending = attempts[-1].text if attempt_idx > 0 else prior_pending

        user_prompt = render_user_prompt(
            features_summary=features_summary,
            prior_approved=prior_approved,
            prior_pending=effective_prior_pending,
            feedback=feedback,
            parse_error=parse_error,
        )
        result = await _call_cli_with_transient_retry(
            prompt=user_prompt,
            system_prompt=SYSTEM_PROMPT,
            tools=CLI_TOOLS,
            timeout=cli_timeout_seconds,
            max_budget_usd=CLI_MAX_BUDGET_USD,
        )
        attempts.append(result)

        try:
            tree = extract_tag_tree(result.text, "requirements")
            validate_requirements(tree)
        except (ParseError, ValidationError) as exc:
            parse_error = str(exc)
            logger.warning(
                "generate_requirements attempt %d/%d failed parse-validate: %s",
                attempt_idx + 1,
                MAX_PARSE_RETRIES + 1,
                parse_error,
            )
            continue

        return result, attempts

    raise RequirementsParseRetryExhausted(
        f"Requirements failed parse-validate after "
        f"{MAX_PARSE_RETRIES + 1} attempts. Final error: {parse_error}"
    )


def register() -> None:
    """Register the handler with the pipeline job queue.

    Called at import time so the pipeline worker always has a
    handler for the job type.
    """
    pipeline_queue.register_handler(
        GENERATE_REQUIREMENTS_JOB_TYPE,
        generate_requirements,
    )
