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

Phase B migration: this handler is the first pilot of the
:mod:`backend.graph.handlers._tier_generation` driver. The handler
body is now a thin wrapper around
:func:`backend.graph.handlers._tier_generation.run_tier_generation`
plus a per-tier :class:`SubreqsState` bundle and config.

See ``docs/architecture/v2-roadmap.md`` Phase 3 stage 3 and
``docs/architecture/v2-rearchitecture.md`` §Subrequirements
decomposition.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy.orm import Session

from backend.cli.config import CliInvocationConfig
from backend.database import SessionLocal  # noqa: F401  (chain test patches this attr)
from backend.graph.handlers._tier_generation import (
    TierGenerationConfig,
    TierState,
    run_tier_generation,
)
from backend.graph.parsers.validators import (
    ValidationError,
    validate_subrequirements,
)
from backend.graph.parsers.xml_sections import TagNode
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


@dataclass
class SubreqsState:
    """Per-tier state bundle returned by :func:`gather_subreqs_state`.

    Implements :class:`TierState` (the driver-readable fields) plus
    the per-tier extras the subreqs prompt + validator need.
    """

    # TierState protocol fields:
    node_id: str
    prior_approved: str | None
    prior_pending: str | None
    prior_pending_id: str | None
    cli_config: CliInvocationConfig
    system_prompt: str
    # Per-tier extras:
    component_summary: str
    parent_resps_summary: str
    in_scope_feats_summary: str
    known_parent_resp_ids: set[str]
    known_feat_ids: set[str]
    domain_parent_context: str | None
    sibling_dep_context: str | None
    vocab_summary: str
    referenced_content_summary: str


def gather_subreqs_state(db: Session, project_id: str, scope_ids: tuple[str, ...]) -> SubreqsState:
    """Build a :class:`SubreqsState` from the projection.

    Wraps :func:`backend.graph.review_context.subreqs.gather_subreqs_context`
    — the existing factored context-gather — and adds the cli_config
    + system_prompt the driver needs. Raises
    :class:`SubreqsHandlerError` when the component is missing or
    has no assigned resps (preserves the original handler's
    behaviour so existing tests pass).
    """
    from backend.graph.review_context.subreqs import gather_subreqs_context

    if not scope_ids:
        raise SubreqsHandlerError("generate_subreqs payload missing component_id")
    component_id = scope_ids[0]

    try:
        ctx = gather_subreqs_context(db, project_id, component_id)
    except ValueError as exc:
        raise SubreqsHandlerError(str(exc)) from exc

    project_row = db.get(Project, project_id)
    assert project_row is not None
    settings = get_project_settings(project_row)
    cli_config = settings.to_cli_config()

    return SubreqsState(
        node_id=ctx.subreqs_node_id,
        prior_approved=ctx.prior_approved,
        prior_pending=ctx.prior_pending,
        prior_pending_id=ctx.prior_pending_id,
        cli_config=cli_config,
        system_prompt=render_system_prompt(),
        component_summary=ctx.component_summary,
        parent_resps_summary=ctx.parent_resps_summary,
        in_scope_feats_summary=ctx.in_scope_feats_summary,
        known_parent_resp_ids=ctx.known_parent_resp_ids,
        known_feat_ids=ctx.known_feat_ids,
        domain_parent_context=ctx.domain_parent_context,
        sibling_dep_context=ctx.sibling_dep_context,
        vocab_summary=ctx.vocab_summary,
        referenced_content_summary=ctx.referenced_content_summary,
    )


def _render_subreqs_prompt(
    state: SubreqsState,
    *,
    prior_pending: str | None,
    parse_error: str | None,
    feedback: str | None,
    prior_review: str | None,
) -> str:
    return render_user_prompt(
        component_summary=state.component_summary,
        parent_resps_summary=state.parent_resps_summary,
        in_scope_feats_summary=state.in_scope_feats_summary,
        domain_parent_context=state.domain_parent_context,
        sibling_dep_context=state.sibling_dep_context,
        prior_approved=state.prior_approved,
        prior_pending=prior_pending,
        feedback=feedback,
        prior_review=prior_review,
        parse_error=parse_error,
        vocab_summary=state.vocab_summary,
        referenced_content_summary=state.referenced_content_summary,
    )


def _validate_subreqs(tree: TagNode, raw_text: str, state: SubreqsState) -> None:
    # Mirror the requirements / sysarch / feature_expansion validators:
    # the <introduction> sibling block carries this pass's initial
    # thinking forward into later regens via prior_pending /
    # prior_approved. Without it the subreqs Document tab has no
    # preamble for the user to read alongside the subresp list.
    if "<introduction" not in raw_text:
        raise ValidationError(
            "Output is missing the required <introduction> block. "
            "Every subrequirements draft must open with a short prose "
            "<introduction> capturing the initial decomposition "
            "thinking — which parent resps cluster, where boundaries "
            "fall. Put it before the <subrequirements> block."
        )
    validate_subrequirements(
        tree,
        known_parent_resp_ids=state.known_parent_resp_ids,
        known_feat_ids=state.known_feat_ids,
    )


# Cast through TierState for the dataclass-as-protocol contract.
SUBREQS_CONFIG: TierGenerationConfig = TierGenerationConfig(
    tier_name="subrequirements",
    generate_job_type=GENERATE_SUBREQS_JOB_TYPE,
    section="subrequirements",
    root_tag="subrequirements",
    exhausted_exception_cls=SubreqsParseRetryExhausted,
    gather_state=gather_subreqs_state,  # type: ignore[arg-type]
    render_prompt=_render_subreqs_prompt,  # type: ignore[arg-type]
    validate=_validate_subreqs,  # type: ignore[arg-type]
    review_job_type="v2.review_subreqs",
    scope_payload_keys=("component_id",),
    max_auto_revisions=5,
)


async def generate_subreqs(payload: dict) -> None:
    """Job handler for ``v2.generate_subrequirements``.

    Payload shape: ``{"project_id": str, "component_id": str,
    "feedback": str | None}``. Phase B migration delegates the full
    pipeline to :func:`run_tier_generation`. The thin wrapper
    converts the driver's payload-shape ``ValueError`` into the
    tier-specific :class:`SubreqsHandlerError` so existing tests
    that assert on the typed exception continue to pass.
    """
    try:
        await run_tier_generation(payload, SUBREQS_CONFIG)
    except ValueError as exc:
        raise SubreqsHandlerError(str(exc)) from exc


def register() -> None:
    """Register the handler with the pipeline job queue."""
    pipeline_queue.register_handler(GENERATE_SUBREQS_JOB_TYPE, generate_subreqs)


# Keep a reference to TierState so static analysis is happy with
# the SubreqsState-implements-TierState relationship even though
# Protocol satisfaction is structural.
_: type = TierState
