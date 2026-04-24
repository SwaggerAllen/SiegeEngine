"""Subrequirements generation handler.

Registered on the pipeline job queue as
``v2.generate_subrequirements``. The payload is
``{"project_id": str, "component_id": str, "feedback": str | None}``.

Per-component variant of the requirements_generation handler.
Gathers inputs scoped to the given component:

- The component's sysarch-time metadata (name, role from
  ``comp_X_techspec`` fragment, api-intent from
  ``comp_X_pubapi`` fragment).
- The top-level ``resp_*`` nodes assigned to this component via
  the ``decomposition`` edges minted at sysarch approval.
- Prior pending draft for this component's subreqs node (if any).

Validator takes ``known_parent_resp_ids`` — the set of top-level
resp IDs assigned to this component — and enforces that every
``<derived-from>`` reference stays within that set. Cross-
component leaks become parse errors that feed the retry loop.

See ``docs/architecture/v2-roadmap.md`` Phase 3 stage 3 and
``docs/architecture/v2-rearchitecture.md`` §Subrequirements
decomposition.
"""

from __future__ import annotations

import logging

from backend.database import SessionLocal
from backend.graph.handlers._bootstrap_generation import (
    persist_draft,
    run_parse_validate_loop,
)
from backend.graph.parsers.validators import validate_subrequirements
from backend.graph.prompts.subrequirements import (
    render_system_prompt,
    render_user_prompt,
)
from backend.models import Project
from backend.pipeline import queue as pipeline_queue
from backend.projects.settings import get_project_settings

logger = logging.getLogger(__name__)

GENERATE_SUBREQS_JOB_TYPE = "v2.generate_subrequirements"


class SubreqsHandlerError(RuntimeError):
    """Raised when the handler cannot proceed."""


class SubreqsParseRetryExhausted(RuntimeError):
    """Raised when parse-validate retries are exhausted."""


async def generate_subreqs(payload: dict) -> None:
    """Job handler for ``v2.generate_subrequirements``.

    Payload shape: ``{"project_id": str, "component_id": str,
    "feedback": str | None}``.
    """
    project_id = payload.get("project_id")
    component_id = payload.get("component_id")
    if not isinstance(project_id, str) or not project_id:
        raise SubreqsHandlerError("generate_subreqs payload missing project_id")
    if not isinstance(component_id, str) or not component_id:
        raise SubreqsHandlerError("generate_subreqs payload missing component_id")
    feedback: str | None = payload.get("feedback")

    # ── Phase 1: gather inputs ──────────────────────────────────────
    db = SessionLocal()
    try:
        from backend.graph.review_context.subreqs import gather_subreqs_context

        try:
            ctx = gather_subreqs_context(db, project_id, component_id)
        except ValueError as exc:
            raise SubreqsHandlerError(str(exc)) from exc

        subreqs_node_id = ctx.subreqs_node_id
        prior_approved = ctx.prior_approved
        prior_pending = ctx.prior_pending
        prior_pending_id = ctx.prior_pending_id
        component_summary = ctx.component_summary
        parent_resps_summary = ctx.parent_resps_summary
        known_parent_resp_ids = ctx.known_parent_resp_ids
        domain_parent_context = ctx.domain_parent_context
        sibling_dep_context = ctx.sibling_dep_context
        vocab_summary = ctx.vocab_summary
        referenced_content_summary = ctx.referenced_content_summary
        parent_resp_count = len(known_parent_resp_ids)

        project_row = db.get(Project, project_id)
        assert project_row is not None
        settings = get_project_settings(project_row)
        cli_timeout_seconds = settings.generation_timeout_seconds
        cli_max_budget_usd = settings.cli_max_budget_usd
        cli_max_output_tokens = settings.cli_max_output_tokens
        system_prompt = render_system_prompt()
    finally:
        db.close()

    # ── Phase 2: LLM call + parse-validate retry loop ───────────────
    logger.info(
        "generate_subreqs project=%s comp=%s prior_pending=%s feedback=%s parents=%d",
        project_id,
        component_id,
        bool(prior_pending),
        bool(feedback),
        parent_resp_count,
    )

    def _render(*, prior_pending: str | None, parse_error: str | None) -> str:
        return render_user_prompt(
            component_summary=component_summary,
            parent_resps_summary=parent_resps_summary,
            domain_parent_context=domain_parent_context,
            sibling_dep_context=sibling_dep_context,
            prior_approved=prior_approved,
            prior_pending=prior_pending,
            feedback=feedback,
            parse_error=parse_error,
            vocab_summary=vocab_summary,
            referenced_content_summary=referenced_content_summary,
        )

    def _validate(tree, _raw_text) -> None:  # type: ignore[no-untyped-def]
        validate_subrequirements(tree, known_parent_resp_ids=known_parent_resp_ids)

    validated_output, attempts = await run_parse_validate_loop(
        root_tag="subrequirements",
        system_prompt=system_prompt,
        cli_timeout_seconds=cli_timeout_seconds,
        cli_max_budget_usd=cli_max_budget_usd,
        cli_max_output_tokens=cli_max_output_tokens,
        prior_pending=prior_pending,
        render_prompt=_render,
        validate=_validate,
        exhausted_exception_cls=SubreqsParseRetryExhausted,
        log_handler_name="generate_subreqs",
    )

    persist_draft(
        project_id=project_id,
        node_id=subreqs_node_id,
        section="subrequirements",
        validated_output=validated_output,
        attempts=attempts,
        prior_pending_id=prior_pending_id,
        log_handler_name="generate_subreqs",
        review_job_type="v2.review_subreqs",
    )


def register() -> None:
    """Register the handler with the pipeline job queue."""
    pipeline_queue.register_handler(GENERATE_SUBREQS_JOB_TYPE, generate_subreqs)
