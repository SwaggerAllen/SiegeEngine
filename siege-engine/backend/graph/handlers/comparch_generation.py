"""Component architecture (comparch) generation handler.

Registered on the pipeline job queue as ``v2.generate_comparch``.
Payload: ``{"project_id": str, "component_id": str, "feedback": str | None}``.

Three-phase shape matching every other bootstrap generation handler:

1. **Gather inputs.** Resolve the target component, verify its
   owning subreqs is approved (non-empty content), assemble the
   full :class:`RegenContext` bundle via the shared stage 2
   helper, read project settings for the CLI timeout.
2. **LLM call + parse-validate retry loop.** Delegate to
   ``run_parse_validate_loop`` with the comparch prompt and the
   arch-doc validator. The closures pass in the pre-formatted
   context kwargs and the three known-ID sets the validator
   needs (subresps, sibling comps, policy-required resps).
3. **Persist events + telemetry.** DraftDiscarded for any prior
   pending, DraftGenerated targeting the comp_* node,
   one GenerationTelemetry row per attempt with
   ``section="comparch"``.

The arch doc is stored as content on the comp_* node itself —
no new node kind. On approval the mint handler (stage 4)
projects the content into its five fragments, subcomponent
mints, component-local policy mints, and edge emissions.

See ``docs/architecture/v2-roadmap.md`` Phase 4.
"""

from __future__ import annotations

import logging
import secrets
import uuid

from sqlalchemy import select

from backend.database import SessionLocal
from backend.graph import events as ev
from backend.graph.handlers._bootstrap_generation import run_parse_validate_loop
from backend.graph.parsers.validators import validate_arch_doc
from backend.graph.prompts.comparch import SYSTEM_PROMPT, render_user_prompt
from backend.graph.reducer import append_event
from backend.graph.regen_context import build_regen_context, format_regen_context
from backend.graph.subrequirements import get_subreqs_node
from backend.models import Project
from backend.models.node import Draft, Node
from backend.models.telemetry import GenerationTelemetry
from backend.pipeline import queue as pipeline_queue
from backend.projects.settings import get_project_settings

logger = logging.getLogger(__name__)

GENERATE_COMPARCH_JOB_TYPE = "v2.generate_comparch"


class ComparchHandlerError(RuntimeError):
    """Raised when the handler cannot proceed because of missing state."""


class ComparchPreconditionError(ComparchHandlerError):
    """Raised when the owning subreqs hasn't been approved yet."""


class ComparchParseRetryExhausted(RuntimeError):
    """Raised when parse-validate retries are exhausted without success."""


def _new_draft_id() -> str:
    return f"draft_{secrets.token_hex(8)}"


def _new_batch_id() -> str:
    return f"batch_{uuid.uuid4().hex[:16]}"


async def generate_comparch(payload: dict) -> None:
    """Job handler for ``v2.generate_comparch``.

    Payload shape: ``{"project_id": str, "component_id": str,
    "feedback": str | None}``.
    """
    project_id = payload.get("project_id")
    component_id = payload.get("component_id")
    if not isinstance(project_id, str) or not project_id:
        raise ComparchHandlerError("generate_comparch payload missing project_id")
    if not isinstance(component_id, str) or not component_id:
        raise ComparchHandlerError("generate_comparch payload missing component_id")
    feedback: str | None = payload.get("feedback")

    # ── Phase 1: gather inputs ──────────────────────────────────────
    db = SessionLocal()
    try:
        comp_node = db.get(Node, component_id)
        if comp_node is None or comp_node.project_id != project_id:
            raise ComparchHandlerError(
                f"Component {component_id!r} not found in project {project_id!r}"
            )
        if comp_node.tier != "comp":
            raise ComparchHandlerError(
                f"Node {component_id!r} is not a comp_* node (tier={comp_node.tier!r})"
            )
        if comp_node.parent_id is not None:
            raise ComparchHandlerError(
                f"Component {component_id!r} is a subcomponent "
                f"(parent_id={comp_node.parent_id!r}). Comparch only "
                "runs on top-level components; subcomponent arch docs "
                "are Phase 5."
            )

        # Precondition: subreqs approved for this component.
        # subreqs node has non-empty content only after DraftApproved
        # has landed, so "content is non-empty" == "approved".
        subreqs_node = get_subreqs_node(db, project_id, component_id)
        if subreqs_node is None or not (subreqs_node.content or "").strip():
            raise ComparchPreconditionError(
                f"Comparch generation for {component_id!r} blocked — its "
                "owning subreqs_* has not been approved yet. Approve the "
                "component's subrequirements first, which will enqueue "
                "comparch generation automatically via subreqs_mint."
            )

        # Prior approved / pending state.
        prior_approved: str | None = comp_node.content or None
        pending = db.execute(
            select(Draft).where(
                Draft.project_id == project_id,
                Draft.target_type == "node",
                Draft.target_id == component_id,
                Draft.status == "pending",
            )
        ).scalar_one_or_none()
        prior_pending: str | None = pending.content if pending is not None else None
        prior_pending_id: str | None = pending.id if pending is not None else None

        # Assemble the regen context via the stage 2 helper.
        regen_ctx = build_regen_context(db, component_id)
        context_kwargs = format_regen_context(regen_ctx)

        # Validator-input ID sets derived from the same context.
        # Pre-minted subresps from subreqs:
        known_subresp_ids: set[str] = {r.id for r in regen_ctx.subresps}
        # Sibling top-level comps:
        known_sibling_comp_ids: set[str] = set(regen_ctx.sibling_comp_ids)
        # Policy-required resps: union of parent resps + subresps
        # (top-level resps assigned to this component plus its
        # pre-minted subresps). Cross-component resps are not
        # allowed as policy <required> targets — that would be
        # a leak into another component's scope.
        known_resp_ids_for_policies: set[str] = {
            r.id for r in regen_ctx.parent_resps
        } | known_subresp_ids

        project_row = db.get(Project, project_id)
        assert project_row is not None
        settings = get_project_settings(project_row)
        cli_timeout_seconds = settings.generation_timeout_seconds
    finally:
        db.close()

    # ── Phase 2: LLM call + parse-validate retry loop ───────────────
    logger.info(
        "generate_comparch project=%s comp=%s prior_pending=%s feedback=%s "
        "subresps=%d siblings=%d policy_candidates=%d",
        project_id,
        component_id,
        bool(prior_pending),
        bool(feedback),
        len(known_subresp_ids),
        len(known_sibling_comp_ids),
        len(regen_ctx.top_level_policy_candidates),
    )

    def _render(*, prior_pending: str | None, parse_error: str | None) -> str:
        return render_user_prompt(
            **context_kwargs,
            prior_approved=prior_approved,
            prior_pending=prior_pending,
            feedback=feedback,
            parse_error=parse_error,
        )

    def _validate(tree) -> None:  # type: ignore[no-untyped-def]
        validate_arch_doc(
            tree,
            known_subresp_ids=known_subresp_ids,
            known_sibling_comp_ids=known_sibling_comp_ids,
            known_resp_ids_for_policies=known_resp_ids_for_policies,
        )

    validated_output, attempts = await run_parse_validate_loop(
        root_tag="comparch",
        system_prompt=SYSTEM_PROMPT,
        cli_timeout_seconds=cli_timeout_seconds,
        prior_pending=prior_pending,
        render_prompt=_render,
        validate=_validate,
        exhausted_exception_cls=ComparchParseRetryExhausted,
        log_handler_name="generate_comparch",
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
                target_id=component_id,
                content=validated_output.text,
                batch_id=new_batch_id,
            ),
        )
        for attempt in attempts:
            db.add(
                GenerationTelemetry(
                    project_id=project_id,
                    node_id=component_id,
                    section="comparch",
                    model=attempt.model,
                    prompt_tokens=attempt.prompt_tokens,
                    completion_tokens=attempt.completion_tokens,
                )
            )
        db.commit()
        logger.info(
            "generate_comparch project=%s comp=%s draft_id=%s committed "
            "(attempts=%d final_prompt=%d final_completion=%d)",
            project_id,
            component_id,
            new_draft_id,
            len(attempts),
            validated_output.prompt_tokens,
            validated_output.completion_tokens,
        )
    finally:
        db.close()


def register() -> None:
    """Register the handler with the pipeline job queue."""
    pipeline_queue.register_handler(GENERATE_COMPARCH_JOB_TYPE, generate_comparch)
