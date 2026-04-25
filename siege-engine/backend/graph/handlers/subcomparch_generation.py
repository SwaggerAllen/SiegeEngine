"""Subcomponent architecture (subcomparch) generation handler.

Registered on the pipeline job queue as ``v2.generate_subcomparch``.
Payload: ``{"project_id": str, "component_id": str, "feedback": str | None}``.

Phase C migration: handler delegates to
:func:`backend.graph.handlers._tier_generation.run_tier_generation`.
The structural checks (subcomp exists, comp tier, has comp parent)
move to :func:`subcomp_node_exists`; the parent-approval check
moves to :func:`parent_comparch_approved`. Both compose via
:func:`all_of` on ``SUBCOMPARCH_CONFIG.readiness_check``.

The subcomparch doc is stored as content on the subcomponent
``comp_*`` node itself — same pattern as comparch. On approval
the subcomparch mint handler projects the content into its four
fragments and emits dependency edges.

See ``docs/architecture/v2-roadmap.md`` Phase 5.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.cli.config import CliInvocationConfig
from backend.database import SessionLocal  # noqa: F401  (chain test patches this attr)
from backend.graph.handlers._readiness import (
    all_of,
    parent_comparch_approved,
    subcomp_node_exists,
)
from backend.graph.handlers._tier_generation import (
    TierGenerationConfig,
    TierPreconditionError,
    TierState,
    run_tier_generation,
)
from backend.graph.parsers.validators import validate_sub_arch_doc
from backend.graph.parsers.xml_sections import TagNode
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


@dataclass
class SubcomparchState:
    """Per-tier state bundle for subcomparch generation."""

    # TierState protocol fields:
    node_id: str
    prior_approved: str | None
    prior_pending: str | None
    prior_pending_id: str | None
    cli_config: CliInvocationConfig
    system_prompt: str
    # Per-tier extras:
    context_kwargs: dict
    known_sibling_sub_ids: set[str]
    known_parent_sibling_comp_ids: set[str]


def gather_subcomparch_state(
    db: Session, project_id: str, scope_ids: tuple[str, ...]
) -> SubcomparchState:
    if not scope_ids:
        raise SubcomparchHandlerError("generate_subcomparch payload missing component_id")
    component_id = scope_ids[0]

    sub_node = db.get(Node, component_id)
    # Defensive — readiness predicate already gates these. Keep
    # explicit checks for the Phase A shipping safety net.
    if sub_node is None or sub_node.project_id != project_id:
        raise SubcomparchHandlerError(
            f"Component {component_id!r} not found in project {project_id!r}"
        )

    pending = db.execute(
        select(Draft).where(
            Draft.project_id == project_id,
            Draft.target_type == "node",
            Draft.target_id == component_id,
            Draft.status == "pending",
        )
    ).scalar_one_or_none()

    regen_ctx = build_regen_context(db, component_id)
    context_kwargs = format_regen_context_for_sub(regen_ctx)

    known_sibling_sub_ids: set[str] = set(regen_ctx.sibling_subcomp_ids)
    known_parent_sibling_comp_ids: set[str] = set(regen_ctx.sibling_comp_ids)

    project_row = db.get(Project, project_id)
    assert project_row is not None
    settings = get_project_settings(project_row)

    return SubcomparchState(
        node_id=component_id,
        prior_approved=sub_node.content or None,
        prior_pending=pending.content if pending is not None else None,
        prior_pending_id=pending.id if pending is not None else None,
        cli_config=settings.to_cli_config(),
        system_prompt=SYSTEM_PROMPT,
        context_kwargs=context_kwargs,
        known_sibling_sub_ids=known_sibling_sub_ids,
        known_parent_sibling_comp_ids=known_parent_sibling_comp_ids,
    )


def _render_subcomparch_prompt(
    state: SubcomparchState,
    *,
    prior_pending: str | None,
    parse_error: str | None,
    feedback: str | None,
    prior_review: str | None,
) -> str:
    return render_user_prompt(
        **state.context_kwargs,
        prior_approved=state.prior_approved,
        prior_pending=prior_pending,
        feedback=feedback,
        prior_review=prior_review,
        parse_error=parse_error,
    )


def _validate_subcomparch(tree: TagNode, _raw: str, state: SubcomparchState) -> None:
    validate_sub_arch_doc(
        tree,
        known_sibling_sub_ids=state.known_sibling_sub_ids,
        known_parent_sibling_comp_ids=state.known_parent_sibling_comp_ids,
    )


SUBCOMPARCH_CONFIG: TierGenerationConfig = TierGenerationConfig(
    tier_name="subcomparch",
    generate_job_type=GENERATE_SUBCOMPARCH_JOB_TYPE,
    section="subcomparch",
    root_tag="subcomparch",
    exhausted_exception_cls=SubcomparchParseRetryExhausted,
    gather_state=gather_subcomparch_state,  # type: ignore[arg-type]
    render_prompt=_render_subcomparch_prompt,  # type: ignore[arg-type]
    validate=_validate_subcomparch,  # type: ignore[arg-type]
    review_job_type="v2.review_subcomparch",
    scope_payload_keys=("component_id",),
    max_auto_revisions=5,
    readiness_check=all_of(subcomp_node_exists, parent_comparch_approved),
)


async def generate_subcomparch(payload: dict) -> None:
    """Job handler for ``v2.generate_subcomparch``.

    Phase C migration: delegates to :func:`run_tier_generation`. The
    thin wrapper converts driver-level errors into typed exceptions:

    - ``ValueError`` (payload-shape) → :class:`SubcomparchHandlerError`.
    - ``TierPreconditionError`` from ``parent_comparch_approved``
      (message contains "no approved comparch content" or "blocked")
      → :class:`SubcomparchPreconditionError`.
    - All other ``TierPreconditionError`` (structural — node missing,
      wrong tier, top-level) → :class:`SubcomparchHandlerError`.
    """
    try:
        await run_tier_generation(payload, SUBCOMPARCH_CONFIG)
    except TierPreconditionError as exc:
        msg = str(exc)
        if "no approved comparch content" in msg or "blocked" in msg:
            raise SubcomparchPreconditionError(msg) from exc
        raise SubcomparchHandlerError(msg) from exc
    except ValueError as exc:
        raise SubcomparchHandlerError(str(exc)) from exc


def register() -> None:
    """Register the handler with the pipeline job queue."""
    pipeline_queue.register_handler(GENERATE_SUBCOMPARCH_JOB_TYPE, generate_subcomparch)


_: type = TierState
