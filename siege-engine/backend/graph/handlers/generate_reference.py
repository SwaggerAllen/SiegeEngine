"""Reference generation handler.

Registered on the pipeline job queue as ``v2.generate_reference``.
Payload: ``{"project_id": str, "ref_id": str, "feedback": str | None}``.

The bootstrap-style routes in ``backend.graph.routes`` build this
payload via ``BootstrapTierConfig.scope_payload_keys=("ref_id",)``,
so the only fields the handler needs to read off the payload are
``project_id``, ``ref_id``, and ``feedback``. The seed description
the user supplied at create time is preserved on the ref node's
``content`` field (as a minimal ``<reference>`` shell), so the
handler reuses ``ref.name`` as the prompt's seed handle on every
regen — no separate ``seed_description`` payload key needed.

Unlike the bootstrap tiers (expansion / reqs / sysarch / subreqs),
references are **not** frozen after approval — ``UpdateReference``
re-enters this handler regardless of the ref's current approval
state. The route layer enforces that by leaving
``has_been_approved=None`` on ``REFERENCE_CONFIG``. The rationale
(see ``docs/architecture/v2-rearchitecture.md`` §Project
references): refs don't mint children, so there's no downstream
desync to guard against after approval.

Phase B migration: this handler is the second pilot of the shared
:func:`backend.graph.handlers._tier_generation.run_tier_generation`
driver. The handler body is now a thin wrapper around the driver
plus a per-tier :class:`ReferenceState` bundle and config.
Migrating reference also unifies its persist path onto
``persist_draft``, which gives reference change-summary extraction
for free (the prompt already instructs the LLM to emit a
``<change-summary>`` block; the prior bespoke persist path stored
that block unstripped in draft content).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.cli.config import CliInvocationConfig
from backend.database import SessionLocal  # noqa: F401  (chain test patches this attr)
from backend.graph.handlers._tier_generation import (
    TierGenerationConfig,
    TierState,
    run_tier_generation,
)
from backend.graph.parsers.validators import validate_reference
from backend.graph.parsers.xml_sections import TagNode
from backend.graph.prompts.reference import SYSTEM_PROMPT, render_user_prompt
from backend.graph.references import (
    reference_by_id,
    render_referenced_content_summary,
)
from backend.models import Project
from backend.models.node import Draft
from backend.pipeline import queue as pipeline_queue
from backend.projects.settings import get_project_settings

logger = logging.getLogger(__name__)

GENERATE_REFERENCE_JOB_TYPE = "v2.generate_reference"


class ReferenceHandlerError(RuntimeError):
    """Raised when the handler cannot proceed because of missing state."""


class ReferenceParseRetryExhausted(RuntimeError):
    """Raised when parse-validate retries are exhausted without success."""


@dataclass
class ReferenceState:
    """Per-tier state bundle returned by :func:`gather_reference_state`."""

    # TierState protocol fields:
    node_id: str
    prior_approved: str | None
    prior_pending: str | None
    prior_pending_id: str | None
    cli_config: CliInvocationConfig
    system_prompt: str
    # Per-tier extras:
    seed_description: str
    referenced_content_summary: str


def _pending_ref_draft(session: Session, project_id: str, ref_id: str) -> Draft | None:
    return session.execute(
        select(Draft).where(
            Draft.project_id == project_id,
            Draft.target_type == "node",
            Draft.target_id == ref_id,
            Draft.status == "pending",
        )
    ).scalar_one_or_none()


def gather_reference_state(
    db: Session, project_id: str, scope_ids: tuple[str, ...]
) -> ReferenceState:
    """Build a :class:`ReferenceState` from the projection."""
    if not scope_ids:
        raise ReferenceHandlerError("generate_reference payload missing ref_id")
    ref_id = scope_ids[0]
    ref_node = reference_by_id(db, ref_id)
    if ref_node is None:
        raise ReferenceHandlerError(f"Reference {ref_id!r} not found in project {project_id!r}")
    if ref_node.project_id != project_id:
        raise ReferenceHandlerError(f"Reference {ref_id!r} belongs to a different project")
    pending = _pending_ref_draft(db, project_id, ref_id)
    project_row = db.get(Project, project_id)
    if project_row is None:
        raise ReferenceHandlerError(f"Project {project_id!r} not found")
    settings = get_project_settings(project_row)
    return ReferenceState(
        node_id=ref_id,
        prior_approved=ref_node.content or None,
        prior_pending=pending.content if pending else None,
        prior_pending_id=pending.id if pending else None,
        cli_config=settings.to_cli_config(),
        system_prompt=SYSTEM_PROMPT,
        seed_description=ref_node.name,
        referenced_content_summary=render_referenced_content_summary(db, project_id, ref_id),
    )


def _render_reference_prompt(
    state: ReferenceState,
    *,
    prior_pending: str | None,
    parse_error: str | None,
    feedback: str | None,
    prior_review: str | None,
) -> str:
    return render_user_prompt(
        seed_description=state.seed_description,
        referenced_content_summary=state.referenced_content_summary,
        prior_approved=state.prior_approved,
        prior_pending=prior_pending,
        feedback=feedback,
        prior_review=prior_review,
        parse_error=parse_error,
    )


def _validate_reference(tree: TagNode, raw: str, _state: ReferenceState) -> None:
    validate_reference(tree, raw_content=raw)


REFERENCE_CONFIG: TierGenerationConfig = TierGenerationConfig(
    tier_name="reference",
    generate_job_type=GENERATE_REFERENCE_JOB_TYPE,
    section="reference",
    root_tag="reference",
    exhausted_exception_cls=ReferenceParseRetryExhausted,
    gather_state=gather_reference_state,  # type: ignore[arg-type]
    render_prompt=_render_reference_prompt,  # type: ignore[arg-type]
    validate=_validate_reference,  # type: ignore[arg-type]
    review_job_type="",  # references have no review handler
    scope_payload_keys=("ref_id",),
)


async def generate_reference(payload: dict) -> None:
    """Job handler for ``v2.generate_reference``.

    Payload shape: ``{"project_id": str, "ref_id": str,
    "feedback": str | None}``. Phase B migration delegates the full
    pipeline to :func:`run_tier_generation`. The thin wrapper
    converts the driver's payload-shape ``ValueError`` into the
    tier-specific :class:`ReferenceHandlerError` so existing tests
    that assert on the typed exception continue to pass.
    """
    try:
        await run_tier_generation(payload, REFERENCE_CONFIG)
    except ValueError as exc:
        raise ReferenceHandlerError(str(exc)) from exc


def register() -> None:
    """Register the handler with the pipeline job queue."""
    pipeline_queue.register_handler(
        GENERATE_REFERENCE_JOB_TYPE,
        generate_reference,
    )


_: type = TierState
