"""Subcomponent architecture (subcomparch) generation handler.

Registered on the pipeline job queue as ``v2.generate_subcomparch``.
Payload: ``{"project_id": str, "component_id": str, "feedback": str | None}``.

Phase 5 counterpart to
:mod:`backend.graph.handlers.comparch_generation`. Same
three-phase shape:

1. **Gather inputs.** Resolve the target subcomponent, verify its
   parent top-level component has approved comparch content,
   assemble the tier-aware :class:`RegenContext` bundle via the
   stage 2 helper, read project settings for the CLI timeout.
2. **LLM call + parse-validate retry loop.** Delegate to
   ``run_parse_validate_loop`` with the subcomparch prompt and
   the sub arch-doc validator. The closures pass in the
   pre-formatted sub context kwargs and the two known-ID sets
   the validator needs (sibling sub aliases, parent-sibling
   comp IDs).
3. **Persist events + telemetry.** DraftDiscarded for any prior
   pending, DraftGenerated targeting the subcomponent's own
   ``comp_*`` node, one ``GenerationTelemetry`` row per attempt
   with ``section="subcomparch"``.

The subcomparch doc is stored as content on the subcomponent
``comp_*`` node itself — same pattern as comparch. On approval
the subcomparch mint handler projects the content into its four
fragments and emits dependency edges for the ``<dependencies>``
entries (mix of alias and real-id targets).

See ``docs/architecture/v2-roadmap.md`` Phase 5.
"""

from __future__ import annotations

import logging

from sqlalchemy import select

from backend.database import SessionLocal
from backend.graph.handlers._bootstrap_generation import (
    persist_draft,
    run_parse_validate_loop,
)
from backend.graph.parsers.validators import validate_sub_arch_doc
from backend.graph.prompts.subcomparch import SYSTEM_PROMPT, render_user_prompt
from backend.graph.regen_context import (
    build_regen_context,
    format_regen_context_for_sub,
)
from backend.models import Project
from backend.models.node import Draft, Node
from backend.pipeline import queue as pipeline_queue
from backend.projects.settings import get_project_settings

logger = logging.getLogger(__name__)

GENERATE_SUBCOMPARCH_JOB_TYPE = "v2.generate_subcomparch"


class SubcomparchHandlerError(RuntimeError):
    """Raised when the handler cannot proceed because of missing state."""


class SubcomparchPreconditionError(SubcomparchHandlerError):
    """Raised when the parent comparch hasn't been approved yet."""


class SubcomparchParseRetryExhausted(RuntimeError):
    """Raised when parse-validate retries are exhausted without success."""


async def generate_subcomparch(payload: dict) -> None:
    """Job handler for ``v2.generate_subcomparch``.

    Payload shape: ``{"project_id": str, "component_id": str,
    "feedback": str | None}``.
    """
    project_id = payload.get("project_id")
    component_id = payload.get("component_id")
    if not isinstance(project_id, str) or not project_id:
        raise SubcomparchHandlerError("generate_subcomparch payload missing project_id")
    if not isinstance(component_id, str) or not component_id:
        raise SubcomparchHandlerError("generate_subcomparch payload missing component_id")
    feedback: str | None = payload.get("feedback")

    # ── Phase 1: gather inputs ──────────────────────────────────────
    db = SessionLocal()
    try:
        sub_node = db.get(Node, component_id)
        if sub_node is None or sub_node.project_id != project_id:
            raise SubcomparchHandlerError(
                f"Component {component_id!r} not found in project {project_id!r}"
            )
        if sub_node.tier != "comp":
            raise SubcomparchHandlerError(
                f"Node {component_id!r} is not a comp_* node (tier={sub_node.tier!r})"
            )
        if sub_node.parent_id is None:
            raise SubcomparchHandlerError(
                f"Component {component_id!r} is a top-level component "
                "(parent_id is None). Subcomparch only runs on "
                "subcomponents; top-level comparch is Phase 4."
            )

        # Precondition: parent comparch approved (parent's content
        # is non-empty). Subcomparch needs the parent's techspec +
        # pubapi + privapi fragments to exist, which are only
        # populated by comparch_mint after DraftApproved lands the
        # arch doc content.
        parent_node = db.get(Node, sub_node.parent_id)
        if parent_node is None or parent_node.tier != "comp":
            raise SubcomparchHandlerError(
                f"Subcomponent {component_id!r} has parent_id "
                f"{sub_node.parent_id!r} which is not a comp_* node"
            )
        if not (parent_node.content or "").strip():
            raise SubcomparchPreconditionError(
                f"Subcomparch generation for {component_id!r} blocked "
                "— its parent component "
                f"{parent_node.id!r} has no approved comparch content. "
                "Approve the parent's architecture doc first; the "
                "comparch mint handler enqueues subcomparch "
                "generation automatically for every minted "
                "subcomponent post-commit."
            )

        # Prior approved / pending state.
        prior_approved: str | None = sub_node.content or None
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
        # build_regen_context auto-detects subcomponent tier from
        # parent_id and populates the sub-specific fields.
        regen_ctx = build_regen_context(db, component_id)
        context_kwargs = format_regen_context_for_sub(regen_ctx)

        # Validator-input ID sets:
        # - sibling sub IDs = real comp_* IDs of same-parent siblings
        # - parent-sibling comp IDs = ctx.sibling_comp_ids (for a
        #   subcomponent context, this already holds the parent's
        #   sibling top-level comp IDs, not the sub's own siblings)
        known_sibling_sub_ids: set[str] = set(regen_ctx.sibling_subcomp_ids)
        known_parent_sibling_comp_ids: set[str] = set(regen_ctx.sibling_comp_ids)

        project_row = db.get(Project, project_id)
        assert project_row is not None
        settings = get_project_settings(project_row)
        cli_config = settings.to_cli_config()
    finally:
        db.close()

    # ── Phase 2: LLM call + parse-validate retry loop ───────────────
    logger.info(
        "generate_subcomparch project=%s sub=%s parent=%s prior_pending=%s "
        "feedback=%s sibling_subs=%d parent_siblings=%d",
        project_id,
        component_id,
        parent_node.id,
        bool(prior_pending),
        bool(feedback),
        len(known_sibling_sub_ids),
        len(known_parent_sibling_comp_ids),
    )

    def _render(*, prior_pending: str | None, parse_error: str | None) -> str:
        return render_user_prompt(
            **context_kwargs,
            prior_approved=prior_approved,
            prior_pending=prior_pending,
            feedback=feedback,
            parse_error=parse_error,
        )

    def _validate(tree, _raw_text) -> None:  # type: ignore[no-untyped-def]
        validate_sub_arch_doc(
            tree,
            known_sibling_sub_ids=known_sibling_sub_ids,
            known_parent_sibling_comp_ids=known_parent_sibling_comp_ids,
        )

    validated_output, attempts = await run_parse_validate_loop(
        root_tag="subcomparch",
        system_prompt=SYSTEM_PROMPT,
        cli_config=cli_config,
        prior_pending=prior_pending,
        render_prompt=_render,
        validate=_validate,
        exhausted_exception_cls=SubcomparchParseRetryExhausted,
        log_handler_name="generate_subcomparch",
    )

    persist_draft(
        project_id=project_id,
        node_id=component_id,
        section="subcomparch",
        validated_output=validated_output,
        attempts=attempts,
        prior_pending_id=prior_pending_id,
        log_handler_name="generate_subcomparch",
        review_job_type="v2.review_subcomparch",
    )


def register() -> None:
    """Register the handler with the pipeline job queue."""
    pipeline_queue.register_handler(GENERATE_SUBCOMPARCH_JOB_TYPE, generate_subcomparch)
