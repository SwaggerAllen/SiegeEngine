"""Requirements generation handler.

Registered on the pipeline job queue as
``v2.generate_requirements``. The payload is
``{"project_id": str, "feedback": str | None,
"auto_revision_pass": int | None,
"auto_revisions_remaining": int | None}``.

Phase C migration: the auto-revision loop has been lifted from this
module into
:mod:`backend.graph.handlers._tier_generation` so every bootstrap
tier can opt in via ``max_auto_revisions``. Requirements remains
the first tier with the loop turned on (``max_auto_revisions=5``);
Phase D enables it on the rest. The handler body is now a thin
wrapper around :func:`run_tier_generation` plus a per-tier
:class:`RequirementsState` bundle and config.

See ``docs/architecture/v2-roadmap.md`` Phase 3.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy.orm import Session

from backend.cli.config import CliInvocationConfig
from backend.database import SessionLocal  # noqa: F401  (chain test patches this attr)
from backend.graph.handlers._tier_generation import (
    MAX_AUTO_REVISIONS as _DRIVER_MAX_AUTO_REVISIONS,
)
from backend.graph.handlers._tier_generation import (
    TierGenerationConfig,
    TierState,
    run_tier_generation,
)
from backend.graph.parsers.validators import ValidationError, validate_requirements
from backend.graph.parsers.xml_sections import TagNode
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
from backend.models.node import Node
from backend.pipeline import queue as pipeline_queue
from backend.projects.settings import get_project_settings

logger = logging.getLogger(__name__)

GENERATE_REQUIREMENTS_JOB_TYPE = "v2.generate_requirements"
REVIEW_REQUIREMENTS_JOB_TYPE = "v2.review_requirements"

# Backward-compat re-export — tests + route layer import this name
# from here. The canonical value lives on _tier_generation.
MAX_AUTO_REVISIONS = _DRIVER_MAX_AUTO_REVISIONS


class RequirementsHandlerError(RuntimeError):
    """Raised when the handler cannot proceed because of missing state."""


class RequirementsParseRetryExhausted(RuntimeError):
    """Raised when parse-validate retries are exhausted without success."""


@dataclass
class RequirementsState:
    """Per-tier state bundle for requirements generation."""

    # TierState protocol fields:
    node_id: str
    prior_approved: str | None
    prior_pending: str | None
    prior_pending_id: str | None
    cli_config: CliInvocationConfig
    system_prompt: str
    # Per-tier extras:
    features_summary: str
    known_feature_ids: set[str]
    vocab_summary: str
    referenced_content_summary: str
    input_doc: str


def gather_requirements_state(
    db: Session, project_id: str, _scope_ids: tuple[str, ...]
) -> RequirementsState:
    from backend.graph.references import render_referenced_content_summary
    from backend.graph.vocabulary import render_vocab_summary_all

    node = get_reqs_node(db, project_id)
    if node is None:
        raise RequirementsHandlerError(
            f"Project {project_id!r} has no reqs node; "
            "was bootstrap_reqs_node called at mint_features time?"
        )
    pending = pending_reqs_draft(db, project_id)

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
    known_feature_ids: set[str] = {f.id for f in feature_rows}

    input_doc_row = (
        db.query(InputDocument)
        .filter(
            InputDocument.project_id == project_id,
            InputDocument.doc_type == "project_doc",
        )
        .order_by(InputDocument.created_at.desc())
        .first()
    )
    project_row = db.get(Project, project_id)
    assert project_row is not None
    settings = get_project_settings(project_row)

    return RequirementsState(
        node_id=node.id,
        prior_approved=node.content or None,
        prior_pending=pending.content if pending else None,
        prior_pending_id=pending.id if pending else None,
        cli_config=settings.to_cli_config(thinking_effort="max"),
        system_prompt=render_system_prompt(),
        features_summary=features_summary,
        known_feature_ids=known_feature_ids,
        vocab_summary=render_vocab_summary_all(db, project_id),
        referenced_content_summary=render_referenced_content_summary(db, project_id, node.id),
        input_doc=(input_doc_row.content or "") if input_doc_row else "",
    )


def _render_requirements_prompt(
    state: RequirementsState,
    *,
    prior_pending: str | None,
    parse_error: str | None,
    feedback: str | None,
    prior_review: str | None,
) -> str:
    return render_user_prompt(
        features_summary=state.features_summary,
        prior_approved=state.prior_approved,
        prior_pending=prior_pending,
        feedback=feedback,
        prior_review=prior_review,
        parse_error=parse_error,
        vocab_summary=state.vocab_summary,
        input_doc=state.input_doc,
        referenced_content_summary=state.referenced_content_summary,
    )


def _validate_requirements(tree: TagNode, raw_text: str, state: RequirementsState) -> None:
    if "<introduction" not in raw_text:
        raise ValidationError(
            "Output is missing the required <introduction> block. "
            "Every requirements draft must open with a short prose "
            "<introduction> capturing the initial decomposition "
            "thinking. Put it before the <requirements> block."
        )
    validate_requirements(tree, known_feature_ids=state.known_feature_ids)


REQUIREMENTS_CONFIG: TierGenerationConfig = TierGenerationConfig(
    tier_name="requirements",
    generate_job_type=GENERATE_REQUIREMENTS_JOB_TYPE,
    section="requirements",
    root_tag="requirements",
    exhausted_exception_cls=RequirementsParseRetryExhausted,
    gather_state=gather_requirements_state,  # type: ignore[arg-type]
    render_prompt=_render_requirements_prompt,  # type: ignore[arg-type]
    validate=_validate_requirements,  # type: ignore[arg-type]
    review_job_type=REVIEW_REQUIREMENTS_JOB_TYPE,
    scope_payload_keys=(),
    thinking_effort="max",
    max_auto_revisions=MAX_AUTO_REVISIONS,
)


async def generate_requirements(payload: dict) -> None:
    """Job handler for ``v2.generate_requirements``.

    Phase C migration: the full pipeline (parse-validate loop,
    persist, auto-revision continuation) lives in
    :func:`run_tier_generation`. The thin wrapper converts the
    driver's payload-shape ``ValueError`` into the tier-specific
    :class:`RequirementsHandlerError`.
    """
    try:
        await run_tier_generation(payload, REQUIREMENTS_CONFIG)
    except ValueError as exc:
        raise RequirementsHandlerError(str(exc)) from exc


def register() -> None:
    """Register the handler with the pipeline job queue."""
    pipeline_queue.register_handler(
        GENERATE_REQUIREMENTS_JOB_TYPE,
        generate_requirements,
    )


_: type = TierState
