"""Domain fan-in (fanin) generation handler.

Registered on the pipeline job queue as ``v2.generate_fanin``.
Payload: ``{"project_id": str, "owner_comp_id": str}``.

Phase 7 bottom-up counterpart to the architecture-doc handlers.
One fan-in node per fanned-out domain comp, minted as an empty
shell by ``comparch_mint``. The first descendant impl approval
enqueues this handler via the ``on_impl_approved`` hook on
``IMPL_CONFIG``; subsequent approvals re-enqueue with the same
payload, which the queue dedups.

Three-phase shape — mirrors the impl handler but without the
draft lifecycle:

1. **Gather inputs.** Resolve the owning comp, locate its
   ``tier="fanin"`` child, assemble the synthesis bundle via
   :func:`build_fanin_synthesis_context` (sub pubapi fragments
   + impl contents + vocab + referenced content).
2. **LLM call + parse-validate retry loop.** Delegate to
   ``run_parse_validate_loop`` with the fan-in prompt and the
   ``<fanin>`` validator.
3. **Persist content.** Emit ``FanInContentUpdated`` with the
   validated raw XML. No ``Draft`` row, no ``DraftApproved``
   event, no review step — the reducer overwrites the fan-in
   node's content directly. One ``GenerationTelemetry`` row per
   attempt with ``section="fanin"``.

Unlike reviewable tiers, fan-in has no approval gate. Real edits
happen at the impls below; fan-in regens mechanically on every
impl approval. See ``docs/architecture/v2-rearchitecture.md``
§Domain fan-in and ``docs/architecture/v2-roadmap.md`` Phase 7.
"""

from __future__ import annotations

import logging

from sqlalchemy import select

from backend.database import SessionLocal
from backend.graph.handlers._bootstrap_generation import run_parse_validate_loop
from backend.graph.parsers.validators import validate_fanin
from backend.graph.prompts.fanin import SYSTEM_PROMPT, render_user_prompt_with_retry
from backend.graph.regen_context import build_fanin_synthesis_context
from backend.models import Project
from backend.models.node import Node
from backend.pipeline import queue as pipeline_queue
from backend.projects.settings import get_project_settings

logger = logging.getLogger(__name__)

GENERATE_FANIN_JOB_TYPE = "v2.generate_fanin"

FANIN_TIER = "fanin"


class FanInHandlerError(RuntimeError):
    """Raised when the handler cannot proceed because of missing state."""


class FanInParseRetryExhausted(RuntimeError):
    """Raised when parse-validate retries are exhausted without success."""


def _find_fanin_for_owner(db, project_id: str, owner_comp_id: str) -> Node | None:  # type: ignore[no-untyped-def]
    """Return the ``fanin_*`` child of ``owner_comp_id``, or None.

    One fan-in per fanned-out domain comp — minted by
    ``comparch_mint`` if and only if ``comp.kind == "domain"``
    and the comp fanned out into subcomponents. Missing fan-in
    at this point is a precondition error, not a "generate a
    new one" case.
    """
    return db.execute(
        select(Node).where(
            Node.project_id == project_id,
            Node.tier == FANIN_TIER,
            Node.parent_id == owner_comp_id,
        )
    ).scalar_one_or_none()


async def generate_fanin(payload: dict) -> None:
    """Job handler for ``v2.generate_fanin``.

    Payload shape: ``{"project_id": str, "owner_comp_id": str}``.
    ``owner_comp_id`` is the top-level domain comp whose subs'
    impls are being synthesized. The fan-in node itself lives as
    that comp's ``tier="fanin"`` child.
    """
    project_id = payload.get("project_id")
    owner_comp_id = payload.get("owner_comp_id")
    if not isinstance(project_id, str) or not project_id:
        raise FanInHandlerError("generate_fanin payload missing project_id")
    if not isinstance(owner_comp_id, str) or not owner_comp_id:
        raise FanInHandlerError("generate_fanin payload missing owner_comp_id")

    # ── Phase 1: gather inputs ──────────────────────────────────────
    db = SessionLocal()
    try:
        owner = db.get(Node, owner_comp_id)
        if owner is None or owner.project_id != project_id:
            raise FanInHandlerError(
                f"Owner comp {owner_comp_id!r} not found in project {project_id!r}"
            )
        if owner.tier != "comp":
            raise FanInHandlerError(
                f"Owner {owner_comp_id!r} is not a comp_* node (tier={owner.tier!r})"
            )
        fanin_node = _find_fanin_for_owner(db, project_id, owner_comp_id)
        if fanin_node is None:
            raise FanInHandlerError(
                f"Owner comp {owner_comp_id!r} has no fanin_* child. "
                "comparch_mint is responsible for minting one fan-in "
                "shell per fanned-out domain comp; this handler "
                "should only run after that mint."
            )
        fanin_node_id = fanin_node.id

        synthesis_ctx = build_fanin_synthesis_context(db, owner_comp_id)

        project_row = db.get(Project, project_id)
        assert project_row is not None
        settings = get_project_settings(project_row)
        cli_config = settings.to_cli_config()
    finally:
        db.close()

    # ── Phase 2: LLM call + parse-validate retry loop ───────────────
    logger.info(
        "generate_fanin project=%s owner=%s fanin=%s subs=%d impls=%d",
        project_id,
        owner_comp_id,
        fanin_node_id,
        len(synthesis_ctx.get("sub_pubapi_fragments", [])),  # type: ignore[arg-type]
        len(synthesis_ctx.get("impl_contents", [])),  # type: ignore[arg-type]
    )

    def _render(*, prior_pending: str | None, parse_error: str | None) -> str:
        # Fan-in has no draft lifecycle, so prior_pending is
        # ignored on the first attempt. The parse-validate loop
        # still passes previous raw text on retry — we feed that
        # through as implicit context via the parse_error hint.
        _ = prior_pending  # unused — fan-in has no prior draft
        return render_user_prompt_with_retry(
            owner_summary=str(synthesis_ctx["owner_summary"]),
            sub_pubapi_fragments=synthesis_ctx["sub_pubapi_fragments"],  # type: ignore[arg-type]
            impl_contents=synthesis_ctx["impl_contents"],  # type: ignore[arg-type]
            vocab_summary=str(synthesis_ctx["vocab_summary"]),
            referenced_content_summary=str(synthesis_ctx["referenced_content_summary"]),
            parse_error=parse_error,
        )

    def _validate(tree, raw_text) -> None:  # type: ignore[no-untyped-def]
        validate_fanin(tree, raw_content=raw_text)

    validated_output, attempts = await run_parse_validate_loop(
        root_tag="fanin",
        system_prompt=SYSTEM_PROMPT,
        cli_config=cli_config,
        prior_pending=None,
        render_prompt=_render,
        validate=_validate,
        exhausted_exception_cls=FanInParseRetryExhausted,
        log_handler_name="generate_fanin",
    )

    # ── Phase 3: persist content (no draft lifecycle) ───────────────
    persist_fanin_content(
        project_id=project_id,
        node_id=fanin_node_id,
        validated_output=validated_output,
        attempts=attempts,
        log_handler_name="generate_fanin",
    )


def persist_fanin_content(
    project_id: str,
    node_id: str,
    validated_output,  # type: ignore[no-untyped-def]
    attempts,  # type: ignore[no-untyped-def]
    log_handler_name: str,
) -> None:
    """Persist the validated fan-in synthesis + telemetry.

    Fan-in counterpart to
    :func:`backend.graph.handlers._bootstrap_generation.persist_draft`,
    but simpler: no draft row, no ``DraftGenerated`` event, no
    ``DraftApproved`` step. Just one ``FanInContentUpdated``
    event that overwrites ``Node.content`` and one telemetry row
    per attempt.
    """
    from backend.graph import events as ev
    from backend.graph.reducer import append_event
    from backend.models.telemetry import GenerationTelemetry

    db = SessionLocal()
    try:
        append_event(
            db,
            project_id,
            ev.FanInContentUpdated(
                node_id=node_id,
                new_content=validated_output.text,
            ),
        )
        for attempt in attempts:
            db.add(
                GenerationTelemetry(
                    project_id=project_id,
                    node_id=node_id,
                    section="fanin",
                    model=attempt.model,
                    prompt_tokens=attempt.prompt_tokens,
                    completion_tokens=attempt.completion_tokens,
                )
            )
        db.commit()
        # Post-commit: unblock any presentational children whose
        # domain-parent fan-ins are now all populated. Replaces the
        # comparch_mint-time walk that gated on approved comparch.
        _unblock_presentationals_on_fanin_commit(db, project_id, node_id)
        logger.info(
            "%s project=%s node=%s committed "
            "(attempts=%d final_prompt=%d final_completion=%d model=%s)",
            log_handler_name,
            project_id,
            node_id,
            len(attempts),
            validated_output.prompt_tokens,
            validated_output.completion_tokens,
            validated_output.model,
        )
        # Phase 8: enqueue AI self-review against the fresh fanin
        # content (Node-backed, no draft). Review handler emits
        # ``DraftReviewUpdated`` with ``draft_id=None`` + node_id
        # set to this fanin node. Opt-out via
        # ``SIEGE_DISABLE_AI_REVIEW=1``.
        import os as _os

        from backend.pipeline import queue as _pipeline_queue

        if _os.environ.get("SIEGE_DISABLE_AI_REVIEW") != "1":
            _pipeline_queue.enqueue(
                db,
                job_type="v2.review_fanin",
                payload={
                    "project_id": project_id,
                    "node_id": node_id,
                    "draft_id": None,
                },
            )
    finally:
        db.close()


def _unblock_presentationals_on_fanin_commit(
    db,  # type: ignore[no-untyped-def]
    project_id: str,
    fanin_node_id: str,
) -> None:
    """Post-fan-in-commit hook: enqueue ready presentational comparch jobs.

    When a domain component's fan-in content lands, walk every
    presentational comp that declares the owning domain comp as a
    ``domain_parent`` and check readiness. A presentational is
    "ready" when every one of its domain parents (including the
    one that just landed) has a populated fan-in. The ready set
    gets ``v2.generate_comparch`` enqueued.

    Errors are logged and swallowed: a failure to unblock here
    must not roll back the fan-in content commit.
    """
    from backend.graph.queries import (
        all_domain_parents_have_populated_fanin,
        presentational_children_of,
    )
    from backend.models.node import Node

    try:
        fanin_node = db.get(Node, fanin_node_id)
        if fanin_node is None or fanin_node.tier != "fanin":
            return
        owner_comp_id = fanin_node.parent_id
        if owner_comp_id is None:
            return

        presentational_children = presentational_children_of(db, owner_comp_id)
        for child in presentational_children:
            if not all_domain_parents_have_populated_fanin(db, child.id):
                continue
            pipeline_queue.enqueue(
                db,
                job_type="v2.generate_comparch",
                payload={
                    "project_id": project_id,
                    "component_id": child.id,
                    "feedback": None,
                },
            )
            logger.info(
                "fanin-commit project=%s owner=%s unblocked presentational "
                "child %s — enqueued its comparch",
                project_id,
                owner_comp_id,
                child.id,
            )
    except Exception:
        logger.exception(
            "fanin-commit project=%s node=%s unblock walk failed",
            project_id,
            fanin_node_id,
        )


def register() -> None:
    """Register the handler with the pipeline job queue."""
    pipeline_queue.register_handler(GENERATE_FANIN_JOB_TYPE, generate_fanin)
