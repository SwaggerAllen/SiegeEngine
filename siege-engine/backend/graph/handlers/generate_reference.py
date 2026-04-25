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

Flow (matches ``feature_expansion.generate_feature_expansion``):

1. Open a session, load inputs (ref node, prior pending, feedback,
   seed description, referenced-content summary). Close the session
   before the LLM call.
2. Run the shared ``run_parse_validate_loop`` against the
   ``<reference>`` grammar.
3. On success, open a fresh session, discard any prior pending
   draft, append ``DraftGenerated`` with the validated content plus
   one ``GenerationTelemetry`` row per attempt. Commit.
"""

from __future__ import annotations

import logging
import secrets
import uuid

from sqlalchemy import select

from backend.database import SessionLocal
from backend.graph import events as ev
from backend.graph.handlers._bootstrap_generation import run_parse_validate_loop
from backend.graph.parsers.validators import validate_reference
from backend.graph.prompts.reference import SYSTEM_PROMPT, render_user_prompt
from backend.graph.reducer import append_event
from backend.graph.references import (
    reference_by_id,
    render_referenced_content_summary,
)
from backend.models import Project
from backend.models.node import Draft
from backend.models.telemetry import GenerationTelemetry
from backend.pipeline import queue as pipeline_queue
from backend.projects.settings import get_project_settings

logger = logging.getLogger(__name__)

GENERATE_REFERENCE_JOB_TYPE = "v2.generate_reference"


class ReferenceHandlerError(RuntimeError):
    """Raised when the handler cannot proceed because of missing state."""


class ReferenceParseRetryExhausted(RuntimeError):
    """Raised when parse-validate retries are exhausted without success."""


def _new_draft_id() -> str:
    return f"draft_{secrets.token_hex(8)}"


def _new_batch_id() -> str:
    return f"batch_{uuid.uuid4().hex[:16]}"


def _pending_ref_draft(session, project_id: str, ref_id: str) -> Draft | None:  # type: ignore[no-untyped-def]
    return session.execute(
        select(Draft).where(
            Draft.project_id == project_id,
            Draft.target_type == "node",
            Draft.target_id == ref_id,
            Draft.status == "pending",
        )
    ).scalar_one_or_none()


async def generate_reference(payload: dict) -> None:
    """Job handler for ``v2.generate_reference``.

    Payload shape: ``{"project_id": str, "ref_id": str,
    "feedback": str | None}``. The seed description the user
    supplied at create time is read off the ref node itself (its
    ``name`` plus the seed-XML body in ``content``), so it
    persists across regens without needing to ride in the payload.
    """
    project_id = payload.get("project_id")
    if not isinstance(project_id, str) or not project_id:
        raise ReferenceHandlerError("generate_reference payload missing project_id")
    ref_id = payload.get("ref_id")
    if not isinstance(ref_id, str) or not ref_id:
        raise ReferenceHandlerError("generate_reference payload missing ref_id")
    feedback: str | None = payload.get("feedback")
    prior_review: str | None = payload.get("prior_review_text") or None

    # ── Phase 1: gather inputs ──────────────────────────────────────
    db = SessionLocal()
    try:
        ref_node = reference_by_id(db, ref_id)
        if ref_node is None:
            raise ReferenceHandlerError(f"Reference {ref_id!r} not found in project {project_id!r}")
        if ref_node.project_id != project_id:
            raise ReferenceHandlerError(f"Reference {ref_id!r} belongs to a different project")
        # The ref's name is the canonical seed handle. The create
        # route writes a minimal ``<reference>`` shell to
        # Node.content carrying the user's seed_description; that
        # shell becomes ``prior_approved`` (since it sits in the
        # node's content), so the first regen sees the seed body
        # in the prior-approved section of the prompt.
        seed_description = ref_node.name
        prior_approved: str | None = ref_node.content or None

        pending = _pending_ref_draft(db, project_id, ref_id)
        prior_pending: str | None = pending.content if pending else None
        prior_pending_id: str | None = pending.id if pending else None

        referenced_content = render_referenced_content_summary(db, project_id, ref_id)

        project_row = db.get(Project, project_id)
        if project_row is None:
            raise ReferenceHandlerError(f"Project {project_id!r} not found")
        settings = get_project_settings(project_row)
        cli_config = settings.to_cli_config()
    finally:
        db.close()

    logger.info(
        "generate_reference project=%s ref_id=%s prior_pending=%s feedback=%s",
        project_id,
        ref_id,
        bool(prior_pending),
        bool(feedback),
    )

    def _render(*, prior_pending: str | None, parse_error: str | None) -> str:
        return render_user_prompt(
            seed_description=seed_description,
            referenced_content_summary=referenced_content,
            prior_approved=prior_approved,
            prior_pending=prior_pending,
            feedback=feedback,
            prior_review=prior_review,
            parse_error=parse_error,
        )

    def _validate(tree, raw_text) -> None:  # type: ignore[no-untyped-def]
        validate_reference(tree, raw_content=raw_text)

    validated_output, attempts = await run_parse_validate_loop(
        root_tag="reference",
        system_prompt=SYSTEM_PROMPT,
        cli_config=cli_config,
        prior_pending=prior_pending,
        render_prompt=_render,
        validate=_validate,
        exhausted_exception_cls=ReferenceParseRetryExhausted,
        log_handler_name="generate_reference",
    )

    # ── Phase 3: persist events + telemetry ─────────────────────────
    db = SessionLocal()
    try:
        if prior_pending_id is not None:
            append_event(
                db,
                project_id,
                ev.DraftDiscarded(draft_id=prior_pending_id, reason="user_regen"),
            )

        new_draft_id = _new_draft_id()
        new_batch_id = _new_batch_id()
        append_event(
            db,
            project_id,
            ev.DraftGenerated(
                draft_id=new_draft_id,
                target_type="node",
                target_id=ref_id,
                content=validated_output.text,
                batch_id=new_batch_id,
            ),
        )
        for attempt in attempts:
            db.add(
                GenerationTelemetry(
                    project_id=project_id,
                    node_id=ref_id,
                    section="reference",
                    model=attempt.model,
                    prompt_tokens=attempt.prompt_tokens,
                    completion_tokens=attempt.completion_tokens,
                )
            )
        db.commit()
        logger.info(
            "generate_reference project=%s ref_id=%s draft_id=%s committed "
            "(attempts=%d final_prompt=%d final_completion=%d model=%s)",
            project_id,
            ref_id,
            new_draft_id,
            len(attempts),
            validated_output.prompt_tokens,
            validated_output.completion_tokens,
            validated_output.model,
        )
    finally:
        db.close()


def register() -> None:
    """Register the handler with the pipeline job queue."""
    pipeline_queue.register_handler(
        GENERATE_REFERENCE_JOB_TYPE,
        generate_reference,
    )
