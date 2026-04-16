"""Sysarch generation handler.

Registered on the pipeline job queue as ``v2.generate_sysarch``.
The payload is ``{"project_id": str, "feedback": str | None}``.

Shape is parallel to the other bootstrap generation handlers
(feature_expansion, requirements_generation): three phases —
gather inputs, run the parse-validate retry loop, persist
events + telemetry — but with the sysarch prompt and validator
bound into the closures the shared helper takes.

Unlike the previous stages, sysarch consumes *two* upstream sets:
the minted ``feat_*`` nodes (for user-intent context) and the
minted top-level ``resp_*`` nodes (the primary input the prompt
decomposes into components). Both are collected from the DB at
the start of phase 1 and formatted into the prompt body; the
top-level resp IDs also become the ``known_top_level_resp_ids``
set the validator cross-checks against.

Parse-validate and transient-CLI-error retry come from
:mod:`backend.graph.handlers._bootstrap_generation` and
:mod:`backend.graph.handlers.feature_expansion` respectively —
this handler does not duplicate that machinery.

See ``docs/architecture/v2-roadmap.md`` Phase 3 stage 2 and
``docs/architecture/v2-rearchitecture.md`` §Generation order.
"""

from __future__ import annotations

import logging
import secrets
import uuid

from backend.database import SessionLocal
from backend.graph import events as ev
from backend.graph.handlers._bootstrap_generation import run_parse_validate_loop
from backend.graph.parsers.validators import validate_sysarch
from backend.graph.prompts.requirements import format_features_summary
from backend.graph.prompts.sysarch import (
    format_reqs_summary,
    render_system_prompt,
    render_user_prompt,
)
from backend.graph.reducer import append_event
from backend.graph.sysarch import get_sysarch_node, pending_sysarch_draft
from backend.models import Project
from backend.models.input_document import InputDocument
from backend.models.node import Node
from backend.models.telemetry import GenerationTelemetry
from backend.pipeline import queue as pipeline_queue
from backend.projects.settings import get_project_settings

logger = logging.getLogger(__name__)

GENERATE_SYSARCH_JOB_TYPE = "v2.generate_sysarch"


class SysarchHandlerError(RuntimeError):
    """Raised when the handler cannot proceed because of missing state."""


class SysarchParseRetryExhausted(RuntimeError):
    """Raised when parse-validate retries are exhausted without success."""


def _new_draft_id() -> str:
    return f"draft_{secrets.token_hex(8)}"


def _new_batch_id() -> str:
    return f"batch_{uuid.uuid4().hex[:16]}"


async def generate_sysarch(payload: dict) -> None:
    """Job handler for ``v2.generate_sysarch``.

    Payload shape: ``{"project_id": str, "feedback": str | None}``.
    """
    project_id = payload.get("project_id")
    if not isinstance(project_id, str) or not project_id:
        raise SysarchHandlerError("generate_sysarch payload missing project_id")
    feedback: str | None = payload.get("feedback")

    # ── Phase 1: gather inputs ──────────────────────────────────────
    db = SessionLocal()
    try:
        node = get_sysarch_node(db, project_id)
        if node is None:
            raise SysarchHandlerError(
                f"Project {project_id!r} has no sysarch node; "
                "was bootstrap_sysarch_node called at mint_requirements time?"
            )
        sysarch_node_id: str = node.id
        prior_approved: str | None = node.content or None

        pending = pending_sysarch_draft(db, project_id)
        prior_pending: str | None = pending.content if pending else None
        prior_pending_id: str | None = pending.id if pending else None

        # Features summary — context only, the LLM reads them for
        # user-intent grounding but doesn't decompose them directly
        # (reqs already did that).
        feature_rows = (
            db.query(Node)
            .filter(Node.project_id == project_id, Node.tier == "feat")
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

        # Top-level resps — the primary input the LLM decomposes
        # into components. Ordered by display_order to match the
        # minted order and stabilize the prompt.
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
        cli_timeout_seconds = settings.generation_timeout_seconds
        system_prompt = render_system_prompt()

        # Project vocabulary context — sysarch reasons across the
        # full component graph, so every defined term should be
        # in context regardless of feature scope.
        from backend.graph.vocabulary import render_vocab_summary_all

        vocab_summary = render_vocab_summary_all(db, project_id)

        # Project input document — fed unconditionally on every
        # sysarch generation. Same reasoning as
        # ``requirements_generation.py``: the route blocks regen
        # with 409 once sysarch is approved, so every invocation
        # is either an initial pass or a pre-approval feedback
        # iteration, and both benefit from seeing the original
        # framing.
        input_doc_row = (
            db.query(InputDocument)
            .filter(
                InputDocument.project_id == project_id,
                InputDocument.doc_type == "project_doc",
            )
            .order_by(InputDocument.created_at.desc())
            .first()
        )
        input_doc = (input_doc_row.content or "") if input_doc_row else ""
    finally:
        db.close()

    # ── Phase 2: LLM call + parse-validate retry loop ───────────────
    logger.info(
        "generate_sysarch project=%s prior_pending=%s feedback=%s features=%d resps=%d",
        project_id,
        bool(prior_pending),
        bool(feedback),
        len(feature_rows),
        len(resp_rows),
    )

    def _render(*, prior_pending: str | None, parse_error: str | None) -> str:
        return render_user_prompt(
            features_summary=features_summary,
            reqs_summary=reqs_summary,
            prior_approved=prior_approved,
            prior_pending=prior_pending,
            feedback=feedback,
            parse_error=parse_error,
            vocab_summary=vocab_summary,
            input_doc=input_doc,
        )

    def _validate(tree, _raw_text) -> None:  # type: ignore[no-untyped-def]
        validate_sysarch(tree, known_top_level_resp_ids=known_top_level_resp_ids)

    validated_output, attempts = await run_parse_validate_loop(
        root_tag="sysarch",
        system_prompt=system_prompt,
        cli_timeout_seconds=cli_timeout_seconds,
        prior_pending=prior_pending,
        render_prompt=_render,
        validate=_validate,
        exhausted_exception_cls=SysarchParseRetryExhausted,
        log_handler_name="generate_sysarch",
    )

    # ── Phase 3: persist events + telemetry ─────────────────────────
    db = SessionLocal()
    try:
        if prior_pending_id is not None:
            append_event(
                db,
                project_id,
                ev.DraftDiscarded(draft_id=prior_pending_id),
            )

        new_draft_id = _new_draft_id()
        new_batch_id = _new_batch_id()
        append_event(
            db,
            project_id,
            ev.DraftGenerated(
                draft_id=new_draft_id,
                target_type="node",
                target_id=sysarch_node_id,
                content=validated_output.text,
                batch_id=new_batch_id,
            ),
        )
        for attempt in attempts:
            db.add(
                GenerationTelemetry(
                    project_id=project_id,
                    node_id=sysarch_node_id,
                    section="sysarch",
                    model=attempt.model,
                    prompt_tokens=attempt.prompt_tokens,
                    completion_tokens=attempt.completion_tokens,
                )
            )
        db.commit()
        logger.info(
            "generate_sysarch project=%s draft_id=%s committed "
            "(attempts=%d final_prompt=%d final_completion=%d model=%s)",
            project_id,
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
    pipeline_queue.register_handler(GENERATE_SYSARCH_JOB_TYPE, generate_sysarch)
