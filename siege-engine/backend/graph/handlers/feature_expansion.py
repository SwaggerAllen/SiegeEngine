"""Feature-expansion generation handler.

Registered on the pipeline job queue as
``v2.generate_feature_expansion``. The payload is
``{"project_id": str, "feedback": str | None}``.

Flow:

1. Open a DB session, load inputs (project doc, expansion node,
   current pending draft if any, feedback). Close the session **before**
   calling the LLM so we don't hold a connection across a potentially
   long-running subprocess.
2. Call ``cli_manager.generate_with_usage`` with the rendered
   feature-expansion prompt. Parse and validate the output against
   the ``<features>`` grammar (see
   :mod:`backend.graph.parsers.xml_sections` and
   :func:`backend.graph.parsers.validators.validate_features`).
   On parse/validate failure, re-invoke the LLM up to
   ``MAX_PARSE_RETRIES`` times with the validation error fed back
   into the prompt. Every LLM call records a telemetry row so
   retry cost is visible.
3. If all retries fail, raise — the job queue catches it, marks
   the job ``failed``, and records the error.
4. On success, open a fresh session. If a pending draft existed on
   entry, append ``DraftDiscarded`` to clear the partial-unique-
   index slot. Then append ``DraftGenerated`` with the final
   validated content, a freshly minted draft id, and a batch id.
   Commit.

The handler never touches ``Node.content`` directly — that is the
reducer's job on ``DraftApproved``. The parse-validate loop lives
*here*, at generation time, so the user only ever sees drafts
that already parse and validate cleanly. Downstream consumers
(the feature-mint handler, later phases) can trust that any
approved expansion content is structurally valid.
"""

from __future__ import annotations

import asyncio
import logging
import secrets
import uuid

from backend.cli.manager import CliTransientError, cli_manager
from backend.database import SessionLocal
from backend.graph.expansion import get_expansion_node, pending_expansion_draft
from backend.graph.parsers.validators import (
    ValidationError,
    validate_features,
    validate_vocabulary,
)
from backend.graph.parsers.xml_sections import extract_tag_tree
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


def _new_draft_id() -> str:
    return f"draft_{secrets.token_hex(8)}"


def _new_batch_id() -> str:
    return f"batch_{uuid.uuid4().hex[:16]}"


async def generate_feature_expansion(payload: dict) -> None:
    """Job handler for ``v2.generate_feature_expansion``.

    Payload shape: ``{"project_id": str, "feedback": str | None}``.
    """
    project_id = payload.get("project_id")
    if not isinstance(project_id, str) or not project_id:
        raise FeatureExpansionHandlerError("generate_feature_expansion payload missing project_id")
    feedback: str | None = payload.get("feedback")

    # ── Phase 1: gather inputs ──────────────────────────────────────
    db = SessionLocal()
    try:
        node = get_expansion_node(db, project_id)
        if node is None:
            raise FeatureExpansionHandlerError(
                f"Project {project_id!r} has no expansion node; "
                "was bootstrap_expansion_node called on creation?"
            )
        exp_node_id: str = node.id
        prior_approved: str | None = node.content or None

        pending = pending_expansion_draft(db, project_id)
        prior_pending: str | None = pending.content if pending else None
        prior_pending_id: str | None = pending.id if pending else None

        input_doc_row = (
            db.query(InputDocument)
            .filter(
                InputDocument.project_id == project_id,
                InputDocument.doc_type == "project_doc",
            )
            .order_by(InputDocument.created_at.desc())
            .first()
        )
        input_doc = input_doc_row.content if input_doc_row else ""

        # Per-project settings: generation timeout in particular.
        # Defaults if unset; see backend.projects.settings.
        project_row = db.get(Project, project_id)
        assert project_row is not None  # expansion node existed, so does the project
        settings = get_project_settings(project_row)
        cli_timeout_seconds = settings.generation_timeout_seconds
        cli_max_budget_usd = settings.cli_max_budget_usd
        cli_max_output_tokens = settings.cli_max_output_tokens
        system_prompt = render_system_prompt()
    finally:
        db.close()

    # ── Phase 2: LLM call + parse-validate retry loop ───────────────
    # The session is closed across all LLM calls and only reopened
    # after we have validated content to commit. Each LLM call's
    # telemetry is buffered and written alongside the
    # DraftGenerated event on success. The retry loop itself lives
    # in ``_bootstrap_generation.run_parse_validate_loop``; we bind
    # our tier-specific prompt + validator into closures here.
    logger.info(
        "generate_feature_expansion project=%s prior_pending=%s feedback=%s",
        project_id,
        bool(prior_pending),
        bool(feedback),
    )

    def _render(*, prior_pending: str | None, parse_error: str | None) -> str:
        return render_user_prompt(
            input_doc=input_doc,
            prior_approved=prior_approved,
            prior_pending=prior_pending,
            feedback=feedback,
            parse_error=parse_error,
        )

    def _validate(tree, raw_text) -> None:  # type: ignore[no-untyped-def]
        features = validate_features(tree)
        # Phase-11 followup B4: the <introduction> sibling block is
        # required. It carries this pass's initial thinking forward
        # into later regenerations (prior_pending / prior_approved)
        # so subsequent feedback iterations don't restate framing
        # from scratch.
        if "<introduction" not in raw_text:
            raise ValidationError(
                "Output is missing the required <introduction> block. "
                "Every feature expansion must open with a short prose "
                "<introduction> that captures the initial thinking. "
                "Put it before the <features> block."
            )
        # The <vocabulary> sibling block is optional. If the LLM
        # emitted one, validate it — cross-references against the
        # feature name set resolve feature-name= attributes, and
        # only name-form refs are accepted at cold-start time since
        # referenced terms are being minted in the same pass and
        # have no IDs yet. Absence is fine; the user can view the
        # pending block on the Vocabulary page and approve it to
        # populate the projection.
        if "<vocabulary" not in raw_text:
            return
        vocab_tree = extract_tag_tree(raw_text, "vocabulary")
        known_feature_names = {f.name for f in features}
        validate_vocabulary(
            vocab_tree,
            known_feature_names=known_feature_names,
            allow_id_refs=False,
        )

    from backend.graph.handlers._bootstrap_generation import (
        persist_draft,
        run_parse_validate_loop,
    )

    validated_output, attempts = await run_parse_validate_loop(
        root_tag="features",
        system_prompt=system_prompt,
        cli_timeout_seconds=cli_timeout_seconds,
        cli_max_budget_usd=cli_max_budget_usd,
        cli_max_output_tokens=cli_max_output_tokens,
        prior_pending=prior_pending,
        render_prompt=_render,
        validate=_validate,
        exhausted_exception_cls=FeatureExpansionParseRetryExhausted,
        log_handler_name="generate_feature_expansion",
        # Phase-11 followup B6: the three top-of-chain tiers run at
        # max thinking effort because their output quality shapes
        # every downstream tier. Propagation tiers stay on default.
        thinking_effort="max",
    )

    persist_draft(
        project_id=project_id,
        node_id=exp_node_id,
        section="expansion",
        validated_output=validated_output,
        attempts=attempts,
        prior_pending_id=prior_pending_id,
        log_handler_name="generate_feature_expansion",
        review_job_type="v2.review_expansion",
    )


async def _call_cli_with_transient_retry(**kwargs):  # type: ignore[no-untyped-def]
    """Invoke ``cli_manager.generate_with_usage`` with retry on transient errors.

    CLI failures are classified in
    :func:`backend.cli.manager._classify_cli_failure` into typed
    subclasses of :class:`backend.cli.manager.CliError`. This
    wrapper retries **only** :class:`CliTransientError` — upstream
    5xx / 529 overload, rate limits, connection resets, and
    unexpected CLI process crashes — up to
    :data:`CLI_MAX_TRANSIENT_RETRIES` times with an exponential
    backoff schedule.

    Fatal subclasses (``CliBudgetExceededError``,
    ``CliContextWindowError``, ``CliAuthError``,
    ``CliContentPolicyError``, ``CliInvalidArgumentError``) are
    re-raised immediately — retrying either burns budget for no
    chance of success or requires user action the retry can't
    perform.

    Parse / validation errors have their own retry loop in
    :func:`backend.graph.handlers._bootstrap_generation.run_parse_validate_loop`;
    this helper only handles the "never got usable output at all"
    failure mode.

    ``TimeoutError`` is **not** retried — the CLI already has its own
    timeout budget and three back-to-back timeout hangs is worse than
    failing fast. Any other exception type propagates unchanged.
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
    """Register the handler with the pipeline job queue.

    Called at import time from ``backend.graph.__init__`` so the
    pipeline worker always has a handler for the job type.
    """
    pipeline_queue.register_handler(
        GENERATE_FEATURE_EXPANSION_JOB_TYPE,
        generate_feature_expansion,
    )
