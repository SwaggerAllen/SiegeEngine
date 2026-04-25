"""Sysarch generation handler.

Registered on the pipeline job queue as ``v2.generate_sysarch``.
The payload is ``{"project_id": str, "feedback": str | None}``.

Phase C migration: handler delegates to
:func:`backend.graph.handlers._tier_generation.run_tier_generation`.
The zero-resp fail-fast that used to live inline in this handler
moves to :func:`backend.graph.handlers._readiness.sysarch_has_top_level_resps`
and is wired via ``readiness_check`` on ``SYSARCH_CONFIG`` —
the driver fails fast before the LLM call instead of after gathering
inputs.

See ``docs/architecture/v2-roadmap.md`` Phase 3 stage 2 and
``docs/architecture/v2-rearchitecture.md`` §Generation order.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy.orm import Session

from backend.cli.config import CliInvocationConfig
from backend.database import SessionLocal  # noqa: F401  (chain test patches this attr)
from backend.graph.handlers._readiness import (
    all_of,
    sysarch_has_top_level_resps,
    sysarch_node_exists,
)
from backend.graph.handlers._tier_generation import (
    TierGenerationConfig,
    TierPreconditionError,
    TierState,
    run_tier_generation,
)
from backend.graph.parsers.validators import ValidationError, validate_sysarch
from backend.graph.parsers.xml_sections import TagNode
from backend.graph.prompts.requirements import format_features_summary
from backend.graph.prompts.sysarch import (
    format_reqs_summary,
    render_system_prompt,
    render_user_prompt,
)
from backend.graph.sysarch import get_sysarch_node, pending_sysarch_draft
from backend.models import Project
from backend.models.input_document import InputDocument
from backend.models.node import Node
from backend.pipeline import queue as pipeline_queue
from backend.projects.settings import get_project_settings

logger = logging.getLogger(__name__)

GENERATE_SYSARCH_JOB_TYPE = "v2.generate_sysarch"


class SysarchHandlerError(RuntimeError):
    """Raised when the handler cannot proceed because of missing state."""


class SysarchParseRetryExhausted(RuntimeError):
    """Raised when parse-validate retries are exhausted without success."""


@dataclass
class SysarchState:
    """Per-tier state bundle for sysarch generation."""

    # TierState protocol fields:
    node_id: str
    prior_approved: str | None
    prior_pending: str | None
    prior_pending_id: str | None
    cli_config: CliInvocationConfig
    system_prompt: str
    # Per-tier extras:
    features_summary: str
    reqs_summary: str
    known_top_level_resp_ids: set[str]
    vocab_summary: str
    referenced_content_summary: str
    input_doc: str


def gather_sysarch_state(db: Session, project_id: str, _scope_ids: tuple[str, ...]) -> SysarchState:
    from backend.graph.references import render_referenced_content_summary
    from backend.graph.vocabulary import render_vocab_summary_all

    node = get_sysarch_node(db, project_id)
    if node is None:
        raise SysarchHandlerError(
            f"Project {project_id!r} has no sysarch node; "
            "was bootstrap_sysarch_node called at mint_requirements time?"
        )
    pending = pending_sysarch_draft(db, project_id)

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

    resp_rows = (
        db.query(Node)
        .filter(
            Node.project_id == project_id,
            Node.tier == "resp",
            Node.parent_id.is_(None),
        )
        .order_by(Node.display_order, Node.created_at)
        .all()
    )
    reqs_summary = format_reqs_summary(
        [{"id": r.id, "name": r.name, "content": r.content} for r in resp_rows]
    )
    known_top_level_resp_ids: set[str] = {r.id for r in resp_rows}

    project_row = db.get(Project, project_id)
    assert project_row is not None
    settings = get_project_settings(project_row)

    input_doc_row = (
        db.query(InputDocument)
        .filter(
            InputDocument.project_id == project_id,
            InputDocument.doc_type == "project_doc",
        )
        .order_by(InputDocument.created_at.desc())
        .first()
    )

    return SysarchState(
        node_id=node.id,
        prior_approved=node.content or None,
        prior_pending=pending.content if pending else None,
        prior_pending_id=pending.id if pending else None,
        cli_config=settings.to_cli_config(thinking_effort="max"),
        system_prompt=render_system_prompt(),
        features_summary=features_summary,
        reqs_summary=reqs_summary,
        known_top_level_resp_ids=known_top_level_resp_ids,
        vocab_summary=render_vocab_summary_all(db, project_id),
        referenced_content_summary=render_referenced_content_summary(db, project_id, node.id),
        input_doc=(input_doc_row.content or "") if input_doc_row else "",
    )


def _render_sysarch_prompt(
    state: SysarchState,
    *,
    prior_pending: str | None,
    parse_error: str | None,
    feedback: str | None,
    prior_review: str | None,
) -> str:
    return render_user_prompt(
        features_summary=state.features_summary,
        reqs_summary=state.reqs_summary,
        prior_approved=state.prior_approved,
        prior_pending=prior_pending,
        feedback=feedback,
        prior_review=prior_review,
        parse_error=parse_error,
        vocab_summary=state.vocab_summary,
        input_doc=state.input_doc,
        referenced_content_summary=state.referenced_content_summary,
    )


def _validate_sysarch(tree: TagNode, raw_text: str, state: SysarchState) -> None:
    if "<introduction" not in raw_text:
        raise ValidationError(
            "Output is missing the required <introduction> block. "
            "Every sysarch draft must open with a short prose "
            "<introduction> capturing the initial component-boundary "
            "thinking. Put it before the <sysarch> block."
        )
    validate_sysarch(tree, known_top_level_resp_ids=state.known_top_level_resp_ids)


SYSARCH_CONFIG: TierGenerationConfig = TierGenerationConfig(
    tier_name="sysarch",
    generate_job_type=GENERATE_SYSARCH_JOB_TYPE,
    section="sysarch",
    root_tag="sysarch",
    exhausted_exception_cls=SysarchParseRetryExhausted,
    gather_state=gather_sysarch_state,  # type: ignore[arg-type]
    render_prompt=_render_sysarch_prompt,  # type: ignore[arg-type]
    validate=_validate_sysarch,  # type: ignore[arg-type]
    review_job_type="v2.review_sysarch",
    scope_payload_keys=(),
    thinking_effort="max",
    readiness_check=all_of(sysarch_node_exists, sysarch_has_top_level_resps),
)


async def generate_sysarch(payload: dict) -> None:
    """Job handler for ``v2.generate_sysarch``.

    Phase C migration: delegates to :func:`run_tier_generation`. The
    thin wrapper converts the driver's ``ValueError`` (payload shape)
    and ``TierPreconditionError`` (zero-resp readiness fail) into
    :class:`SysarchHandlerError` so existing tests asserting on the
    typed exception continue to pass.
    """
    try:
        await run_tier_generation(payload, SYSARCH_CONFIG)
    except (ValueError, TierPreconditionError) as exc:
        raise SysarchHandlerError(str(exc)) from exc


def register() -> None:
    """Register the handler with the pipeline job queue."""
    pipeline_queue.register_handler(GENERATE_SYSARCH_JOB_TYPE, generate_sysarch)


_: type = TierState
