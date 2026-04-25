"""Feature-expansion generation handler.

Registered on the pipeline job queue as
``v2.generate_feature_expansion``. The payload is
``{"project_id": str, "feedback": str | None}``.

Phase C migration: this handler delegates the full pipeline to
:func:`backend.graph.handlers._tier_generation.run_tier_generation`.
The module also keeps the CLI retry helpers (``CLI_TOOLS``,
``MAX_PARSE_RETRIES``, ``_call_cli_with_transient_retry``) since
``_bootstrap_generation.run_parse_validate_loop`` imports them from
here. Those are factored as module-level utilities; the handler
body is just a thin driver wrapper.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from sqlalchemy.orm import Session

from backend.cli.config import CliInvocationConfig
from backend.cli.manager import CliTransientError, cli_manager
from backend.database import SessionLocal  # noqa: F401  (chain test patches this attr)
from backend.graph.expansion import get_expansion_node, pending_expansion_draft
from backend.graph.handlers._tier_generation import (
    TierGenerationConfig,
    TierState,
    run_tier_generation,
)
from backend.graph.parsers.validators import (
    ValidationError,
    validate_features,
    validate_vocabulary,
)
from backend.graph.parsers.xml_sections import TagNode, extract_tag_tree
from backend.graph.prompts.feature_expansion import (
    render_system_prompt,
    render_user_prompt,
)
from backend.models import Project
from backend.models.input_document import InputDocument
from backend.pipeline import queue as pipeline_queue
from backend.projects.settings import get_project_settings

logger = logging.getLogger(__name__)

GENERATE_FEATURE_EXPANSION_JOB_TYPE = "v2.generate_feature_expansion"

# Disable all CLI tools — this is pure text generation, no file I/O.
CLI_TOOLS = '""'

# Parse-validate retry budget. The first attempt plus this many
# additional retries means up to MAX_PARSE_RETRIES + 1 total LLM
# calls per user-requested generation. Keep small so runaway
# broken output doesn't silently blow the token budget.
MAX_PARSE_RETRIES = 3

# Transient-CLI-error retry budget. Separate from the parse-validate
# loop: this retries when the CLI itself fails (upstream Anthropic
# 5xx, process crash, etc.) — i.e. we never got usable output. The
# first attempt plus this many retries means up to
# ``CLI_MAX_TRANSIENT_RETRIES + 1`` total CLI invocations per
# parse-validate attempt. Backoff is exponential.
CLI_MAX_TRANSIENT_RETRIES = 3
CLI_RETRY_BACKOFF_SECONDS: tuple[float, ...] = (2.0, 4.0, 8.0)


class FeatureExpansionHandlerError(RuntimeError):
    """Raised when the handler cannot proceed because of missing state."""


class FeatureExpansionParseRetryExhausted(RuntimeError):
    """Raised when parse-validate retries are exhausted without success.

    Carries the final parse/validation error so the job queue can
    surface it in the failed-job row.
    """


@dataclass
class FeatureExpansionState:
    """Per-tier state bundle for feature_expansion generation."""

    # TierState protocol fields:
    node_id: str
    prior_approved: str | None
    prior_pending: str | None
    prior_pending_id: str | None
    cli_config: CliInvocationConfig
    system_prompt: str
    # Per-tier extras:
    input_doc: str


def gather_feature_expansion_state(
    db: Session, project_id: str, _scope_ids: tuple[str, ...]
) -> FeatureExpansionState:
    node = get_expansion_node(db, project_id)
    if node is None:
        raise FeatureExpansionHandlerError(
            f"Project {project_id!r} has no expansion node; "
            "was bootstrap_expansion_node called on creation?"
        )
    pending = pending_expansion_draft(db, project_id)
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
    return FeatureExpansionState(
        node_id=node.id,
        prior_approved=node.content or None,
        prior_pending=pending.content if pending else None,
        prior_pending_id=pending.id if pending else None,
        cli_config=settings.to_cli_config(thinking_effort="max"),
        system_prompt=render_system_prompt(),
        input_doc=input_doc_row.content if input_doc_row else "",
    )


def _render_feature_expansion_prompt(
    state: FeatureExpansionState,
    *,
    prior_pending: str | None,
    parse_error: str | None,
    feedback: str | None,
    prior_review: str | None,
) -> str:
    return render_user_prompt(
        input_doc=state.input_doc,
        prior_approved=state.prior_approved,
        prior_pending=prior_pending,
        feedback=feedback,
        prior_review=prior_review,
        parse_error=parse_error,
    )


def _validate_feature_expansion(
    tree: TagNode, raw_text: str, _state: FeatureExpansionState
) -> None:
    features = validate_features(tree)
    # Phase-11 followup B4: the <introduction> sibling block is
    # required so subsequent regens have the tier's own initial
    # thinking available.
    if "<introduction" not in raw_text:
        raise ValidationError(
            "Output is missing the required <introduction> block. "
            "Every feature expansion must open with a short prose "
            "<introduction> that captures the initial thinking. "
            "Put it before the <features> block."
        )
    # Optional <vocabulary> sibling block — validate when present.
    if "<vocabulary" not in raw_text:
        return
    vocab_tree = extract_tag_tree(raw_text, "vocabulary")
    known_feature_names = {f.name for f in features}
    validate_vocabulary(
        vocab_tree,
        known_feature_names=known_feature_names,
        allow_id_refs=False,
    )


FEATURE_EXPANSION_CONFIG: TierGenerationConfig = TierGenerationConfig(
    tier_name="feature_expansion",
    generate_job_type=GENERATE_FEATURE_EXPANSION_JOB_TYPE,
    section="expansion",
    root_tag="features",
    exhausted_exception_cls=FeatureExpansionParseRetryExhausted,
    gather_state=gather_feature_expansion_state,  # type: ignore[arg-type]
    render_prompt=_render_feature_expansion_prompt,  # type: ignore[arg-type]
    validate=_validate_feature_expansion,  # type: ignore[arg-type]
    review_job_type="v2.review_expansion",
    scope_payload_keys=(),
    thinking_effort="max",
)


async def generate_feature_expansion(payload: dict) -> None:
    """Job handler for ``v2.generate_feature_expansion``.

    Payload shape: ``{"project_id": str, "feedback": str | None}``.
    Phase C migration delegates to :func:`run_tier_generation`. The
    thin wrapper converts the driver's payload-shape ``ValueError``
    into the tier-specific :class:`FeatureExpansionHandlerError`.
    """
    try:
        await run_tier_generation(payload, FEATURE_EXPANSION_CONFIG)
    except ValueError as exc:
        raise FeatureExpansionHandlerError(str(exc)) from exc


async def _call_cli_with_transient_retry(**kwargs):  # type: ignore[no-untyped-def]
    """Invoke ``cli_manager.generate_with_usage`` with retry on transient errors.

    This helper stays in feature_expansion (rather than moving to
    ``_tier_generation``) because ``_bootstrap_generation.run_parse_validate_loop``
    imports it from here. Moving it would create circular imports
    (``_tier_generation`` calls ``_bootstrap_generation``, which
    would then need to call back into ``_tier_generation``).

    CLI failures are classified in
    :func:`backend.cli.manager._classify_cli_failure` into typed
    subclasses of :class:`backend.cli.manager.CliError`. This
    wrapper retries **only** :class:`CliTransientError` — upstream
    5xx / 529 overload, rate limits, connection resets, and
    unexpected CLI process crashes — up to
    :data:`CLI_MAX_TRANSIENT_RETRIES` times with an exponential
    backoff schedule.
    """
    last_exc: CliTransientError | None = None
    for attempt_idx in range(CLI_MAX_TRANSIENT_RETRIES + 1):
        try:
            return await cli_manager.generate_with_usage(**kwargs)
        except CliTransientError as exc:
            last_exc = exc
            if attempt_idx >= CLI_MAX_TRANSIENT_RETRIES:
                break
            backoff = CLI_RETRY_BACKOFF_SECONDS[attempt_idx]
            logger.warning(
                "CLI call failed transiently on attempt %d/%d, retrying in %.1fs: %s",
                attempt_idx + 1,
                CLI_MAX_TRANSIENT_RETRIES + 1,
                backoff,
                str(exc)[:500],
            )
            await asyncio.sleep(backoff)
    assert last_exc is not None
    raise last_exc


def register() -> None:
    """Register the handler with the pipeline job queue."""
    pipeline_queue.register_handler(
        GENERATE_FEATURE_EXPANSION_JOB_TYPE,
        generate_feature_expansion,
    )


_: type = TierState
