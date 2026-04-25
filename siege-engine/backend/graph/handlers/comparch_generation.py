"""Component architecture (comparch) generation handler.

Registered on the pipeline job queue as ``v2.generate_comparch``.
Payload: ``{"project_id": str, "component_id": str, "feedback": str | None}``.

Phase C migration: handler delegates to
:func:`backend.graph.handlers._tier_generation.run_tier_generation`.
The "subreqs approved" precondition lifts to the
:func:`parent_subreqs_approved` readiness predicate. Component
existence / tier / top-level checks stay in :func:`gather_comparch_state`
and raise :class:`ComparchHandlerError` directly.

The arch doc is stored as content on the comp_* node itself —
no new node kind. On approval the mint handler (stage 4)
projects the content into its five fragments, subcomponent
mints, component-local policy mints, and edge emissions.

See ``docs/architecture/v2-roadmap.md`` Phase 4.
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
    parent_subreqs_approved,
    top_level_comp_exists,
)
from backend.graph.handlers._tier_generation import (
    TierGenerationConfig,
    TierPreconditionError,
    TierState,
    run_tier_generation,
)
from backend.graph.parsers.validators import validate_arch_doc
from backend.graph.parsers.xml_sections import TagNode
from backend.graph.prompts.comparch import render_system_prompt, render_user_prompt
from backend.graph.regen_context import build_regen_context, format_regen_context
from backend.models import Project
from backend.models.node import Draft, Node
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


@dataclass
class ComparchState:
    """Per-tier state bundle for comparch generation."""

    # TierState protocol fields:
    node_id: str
    prior_approved: str | None
    prior_pending: str | None
    prior_pending_id: str | None
    cli_config: CliInvocationConfig
    system_prompt: str
    # Per-tier extras:
    context_kwargs: dict
    known_subresp_ids: set[str]
    known_sibling_comp_ids: set[str]
    known_resp_ids_for_policies: set[str]
    target_is_foundation: bool


def gather_comparch_state(
    db: Session, project_id: str, scope_ids: tuple[str, ...]
) -> ComparchState:
    if not scope_ids:
        raise ComparchHandlerError("generate_comparch payload missing component_id")
    component_id = scope_ids[0]

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

    pending = db.execute(
        select(Draft).where(
            Draft.project_id == project_id,
            Draft.target_type == "node",
            Draft.target_id == component_id,
            Draft.status == "pending",
        )
    ).scalar_one_or_none()

    regen_ctx = build_regen_context(db, component_id)
    context_kwargs = format_regen_context(regen_ctx)

    known_subresp_ids: set[str] = {r.id for r in regen_ctx.subresps}
    known_sibling_comp_ids: set[str] = set(regen_ctx.sibling_comp_ids)
    known_resp_ids_for_policies: set[str] = {
        r.id for r in regen_ctx.parent_resps
    } | known_subresp_ids
    target_is_foundation: bool = bool(comp_node.is_foundation)

    project_row = db.get(Project, project_id)
    assert project_row is not None
    settings = get_project_settings(project_row)

    return ComparchState(
        node_id=component_id,
        prior_approved=comp_node.content or None,
        prior_pending=pending.content if pending is not None else None,
        prior_pending_id=pending.id if pending is not None else None,
        cli_config=settings.to_cli_config(),
        system_prompt=render_system_prompt(),
        context_kwargs=context_kwargs,
        known_subresp_ids=known_subresp_ids,
        known_sibling_comp_ids=known_sibling_comp_ids,
        known_resp_ids_for_policies=known_resp_ids_for_policies,
        target_is_foundation=target_is_foundation,
    )


def _render_comparch_prompt(
    state: ComparchState,
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
        target_is_foundation=state.target_is_foundation,
        parse_error=parse_error,
    )


def _validate_comparch(tree: TagNode, _raw: str, state: ComparchState) -> None:
    validate_arch_doc(
        tree,
        known_subresp_ids=state.known_subresp_ids,
        known_sibling_comp_ids=state.known_sibling_comp_ids,
        known_resp_ids_for_policies=state.known_resp_ids_for_policies,
        target_is_foundation=state.target_is_foundation,
    )


COMPARCH_CONFIG: TierGenerationConfig = TierGenerationConfig(
    tier_name="comparch",
    generate_job_type=GENERATE_COMPARCH_JOB_TYPE,
    section="comparch",
    root_tag="comparch",
    exhausted_exception_cls=ComparchParseRetryExhausted,
    gather_state=gather_comparch_state,  # type: ignore[arg-type]
    render_prompt=_render_comparch_prompt,  # type: ignore[arg-type]
    validate=_validate_comparch,  # type: ignore[arg-type]
    review_job_type="v2.review_comparch",
    scope_payload_keys=("component_id",),
    max_auto_revisions=5,
    readiness_check=all_of(top_level_comp_exists, parent_subreqs_approved),
)


async def generate_comparch(payload: dict) -> None:
    """Job handler for ``v2.generate_comparch``.

    Phase C migration: delegates to :func:`run_tier_generation`. The
    thin wrapper converts driver-level errors into the tier-specific
    typed exceptions:

    - ``ValueError`` (payload-shape) → :class:`ComparchHandlerError`.
    - ``TierPreconditionError`` from ``parent_subreqs_approved`` —
      i.e. the message contains "has not been approved" or "blocked"
      — maps to :class:`ComparchPreconditionError`.
    - All other ``TierPreconditionError`` (component missing,
      wrong tier, subcomponent) maps to :class:`ComparchHandlerError`.

    Both subclasses preserve the test contract that asserted on
    ``ComparchHandlerError`` for the structural checks and
    ``ComparchPreconditionError`` for the upstream-readiness check.
    """
    try:
        await run_tier_generation(payload, COMPARCH_CONFIG)
    except TierPreconditionError as exc:
        msg = str(exc)
        if "has not been approved" in msg or "blocked" in msg:
            raise ComparchPreconditionError(msg) from exc
        raise ComparchHandlerError(msg) from exc
    except ValueError as exc:
        raise ComparchHandlerError(str(exc)) from exc


def register() -> None:
    """Register the handler with the pipeline job queue."""
    pipeline_queue.register_handler(GENERATE_COMPARCH_JOB_TYPE, generate_comparch)


_: type = TierState
