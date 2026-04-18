"""Generic route handlers for bootstrap-tier CRUD operations.

Every bootstrap tier (expansion, requirements, sysarch, subreqs,
comparch, subcomparch) follows the same five-operation lifecycle:
GET state, POST feedback, POST approve, POST discard, POST cancel.
Some tiers additionally support POST reset and POST prompt-preview.

This module provides generic implementations of each operation,
parameterized by a :class:`BootstrapTierConfig` that captures
the per-tier variation (node getter, draft getter, job types,
serializer, etc.). The ``routes.py`` module registers the concrete
FastAPI endpoints — it still owns the ``@router`` decorators
(needed for FastAPI path-param inspection) — but each endpoint is
a one-liner that delegates here.

The goal is that adding a new bootstrap tier requires adding one
:class:`BootstrapTierConfig` instance and a handful of route
decorators, not copy-pasting 200 lines of handler logic.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable

from fastapi import HTTPException
from sqlalchemy.orm import Session

from backend.graph import events as ev
from backend.graph import queries
from backend.graph.broadcast import commit_and_publish
from backend.graph.reducer import append_event
from backend.models.node import Draft
from backend.pipeline import queue as pipeline_queue

logger = logging.getLogger(__name__)


@dataclass
class BootstrapTierConfig:
    """Per-tier configuration for the generic bootstrap route handlers.

    Each bootstrap tier registers one of these with its specific
    functions and constants. The generic handlers read these to
    dispatch the right DB queries, job types, and serializers.
    """

    tier_name: str

    # ── Node resolution ────────────────────────────────────────────
    # Returns the tier's node, or None if it doesn't exist.
    # Signature: (db, project_id, *scope_ids) -> Node | None
    get_node: Callable[..., Any]

    # ── Draft resolution ───────────────────────────────────────────
    # Returns the pending draft for this tier, or None.
    # Signature: (db, project_id, *scope_ids) -> Draft | None
    get_pending_draft: Callable[..., Any]

    # ── Approval check ─────────────────────────────────────────────
    # Returns True if the tier's node has approved content. Used to
    # gate feedback (bootstrap tiers are read-only after approval).
    # None means the tier doesn't have an approval gate (comparch/
    # subcomparch can always be regenerated).
    # Signature: (db, project_id, *scope_ids) -> bool
    has_been_approved: Callable[..., bool] | None = None

    # ── Lazy bootstrap ─────────────────────────────────────────────
    # If the node doesn't exist on GET, call this to mint one.
    # None means no lazy bootstrap (404 instead).
    # Signature: (db, project_id, *scope_ids) -> str  (returns node_id)
    bootstrap_node: Callable[..., str] | None = None

    # ── Job types ──────────────────────────────────────────────────
    generate_job_type: str = ""
    mint_job_type: str = ""

    # ── Serializers ────────────────────────────────────────────────
    # Converts a Node to the response dict shape.
    serialize_node: Callable[..., Any] = lambda n: None
    # Converts a Draft to the response draft dict shape.
    serialize_draft: Callable[..., Any] = lambda d: None

    # ── Feedback read-only message ─────────────────────────────────
    feedback_readonly_detail: str = ""

    # ── Reset support ──────────────────────────────────────────────
    # If set, the tier supports destructive reset.
    collect_downstream_nodes: Callable[..., list] | None = None
    collect_pending_drafts_for_nodes: Callable[..., list] | None = None
    downstream_job_types: tuple[str, ...] = ()
    # Additional singleton nodes whose content should be cleared
    # on reset (e.g. expansion reset clears reqs + sysarch content).
    additional_nodes_to_clear: Callable[..., list] | None = None
    # Additional singleton pending drafts to discard on reset.
    additional_drafts_to_discard: Callable[..., list] | None = None

    # ── Prompt preview ─────────────────────────────────────────────
    # Gathers context and renders system + user prompts.
    # Signature: (db, project_id, *scope_ids, feedback) -> (sys, user)
    render_prompt_preview: Callable[..., tuple[str, str]] | None = None

    # ── Job payload key names ──────────────────────────────────────
    # The keys the generation / mint handlers expect for each scope
    # id in the job payload. Defaults match the bootstrap chain
    # (component_id for the first scope, sub_id for the second).
    # Tiers with different payload conventions (e.g. refs use
    # ``ref_id``) override this.
    scope_payload_keys: tuple[str, ...] = ("component_id", "sub_id")

    # ── Post-approval hook ─────────────────────────────────────────
    # Optional callable invoked by ``bootstrap_approve`` after the
    # reducer commits the ``DraftApproved`` event and the node has
    # been refreshed. Used by the impl tier to walk up to the
    # owning domain comp and enqueue fan-in regeneration (Phase 7
    # ``on_impl_approved``). Errors in the hook are logged and
    # swallowed — the approval itself has already committed.
    # Signature: (db, project_id, node, scope_ids) -> None
    on_approve: Callable[..., None] | None = None

    # ── Phase 8: AI self-review job type ─────────────────────────────
    # If set, ``persist_draft`` / ``persist_fanin_content``
    # enqueues this job after committing the generation so the
    # reviewer can critique the generated output. Empty string
    # disables reviews for this tier (useful during chain tests).
    # Signature of the review handler matches the other pipeline
    # handlers — ``async def(payload: dict) -> None``.
    review_job_type: str = ""


def build_job_payload(
    project_id: str,
    scope_ids: tuple[str, ...],
    feedback: str | None = None,
    *,
    scope_payload_keys: tuple[str, ...] = ("component_id", "sub_id"),
) -> dict[str, Any]:
    """Build a job payload dict with the right scope keys."""
    payload: dict[str, Any] = {"project_id": project_id, "feedback": feedback}
    for idx, sid in enumerate(scope_ids):
        if idx >= len(scope_payload_keys):
            raise ValueError(
                f"build_job_payload: scope_ids has {len(scope_ids)} entries "
                f"but only {len(scope_payload_keys)} payload keys configured"
            )
        payload[scope_payload_keys[idx]] = sid
    return payload


def bootstrap_get_state(
    db: Session,
    project_id: str,
    scope_ids: tuple[str, ...],
    config: BootstrapTierConfig,
    require_project: Callable,
) -> dict[str, Any]:
    """Generic GET state handler for any bootstrap tier."""
    require_project(db, project_id)
    node = config.get_node(db, project_id, *scope_ids)
    if node is None:
        if config.bootstrap_node is not None:
            logger.warning(
                "%s node missing for project %s; lazy-bootstrapping",
                config.tier_name,
                project_id,
            )
            config.bootstrap_node(db, project_id, *scope_ids)
            commit_and_publish(db, project_id)
            pipeline_queue.enqueue(
                db,
                job_type=config.generate_job_type,
                payload=build_job_payload(
                    project_id,
                    scope_ids,
                    scope_payload_keys=config.scope_payload_keys,
                ),
            )
            node = config.get_node(db, project_id, *scope_ids)
            assert node is not None
        else:
            raise HTTPException(
                status_code=404,
                detail=f"{config.tier_name} node missing",
            )
    draft = config.get_pending_draft(db, project_id, *scope_ids)
    payload_filters: dict[str, Any] = {}
    for idx, sid in enumerate(scope_ids):
        if idx < len(config.scope_payload_keys):
            payload_filters[config.scope_payload_keys[idx]] = sid
    (
        status,
        last_error,
        started_at,
        current_attempt,
        max_attempts,
        failed_raw_output,
    ) = queries.latest_generation_status(
        db,
        project_id,
        config.generate_job_type,
        payload_filters=payload_filters if payload_filters else None,
    )
    telemetry = _latest_telemetry(db, project_id, node.id)

    # Phase 8: AI self-review fields — populated when the tier
    # has a configured ``review_job_type``. Skipped otherwise
    # (empty strings / nulls), so tiers without review support
    # serialize the same shape without changing the response
    # schema. Review jobs always carry ``node_id`` explicitly,
    # which project-uniquely identifies the tier node being
    # reviewed — cleaner filter than reusing the scope payload
    # keys (which vary per tier).
    review_text = _resolve_review_text(draft, node) if config.review_job_type else ""
    if config.review_job_type:
        (
            review_status,
            review_last_error,
            _review_started_at,
            review_current_attempt,
            review_max_attempts,
            _review_raw_output,
        ) = queries.latest_generation_status(
            db,
            project_id,
            config.review_job_type,
            payload_filters={"node_id": node.id},
        )
    else:
        review_status = "idle"
        review_last_error = None
        review_current_attempt = None
        review_max_attempts = None

    return {
        "node": config.serialize_node(node),
        "pending_draft": config.serialize_draft(draft) if draft else None,
        "generation_status": status,
        "last_error": last_error,
        "latest_telemetry": telemetry,
        "generation_started_at": started_at,
        "current_attempt": current_attempt,
        "max_attempts": max_attempts,
        "failed_raw_output": failed_raw_output,
        "review_text": review_text,
        "review_status": review_status,
        "review_last_error": review_last_error,
        "review_current_attempt": review_current_attempt,
        "review_max_attempts": review_max_attempts,
    }


def _resolve_review_text(draft: Draft | None, node) -> str:
    """Return the current review_text for this tier.

    For tiers with a pending draft, the review lives on the draft
    row. For fanin (no draft lifecycle), it lives on the node row.
    Approved / no-pending-draft state shows the last-known review
    lifted from the node if the tier stashes one there (fanin);
    otherwise empty string.
    """
    if draft is not None:
        return draft.review_text or ""
    return (node.review_text or "") if hasattr(node, "review_text") else ""


def bootstrap_feedback(
    db: Session,
    project_id: str,
    scope_ids: tuple[str, ...],
    feedback_text: str,
    config: BootstrapTierConfig,
    require_project: Callable,
) -> dict[str, str]:
    """Generic POST feedback handler."""
    require_project(db, project_id)
    node = config.get_node(db, project_id, *scope_ids)
    if node is None:
        raise HTTPException(
            status_code=404,
            detail=f"{config.tier_name} node missing",
        )
    if config.has_been_approved is not None and config.has_been_approved(
        db, project_id, *scope_ids
    ):
        raise HTTPException(status_code=409, detail=config.feedback_readonly_detail)
    feedback = (feedback_text or "").strip() or None
    job_id = pipeline_queue.enqueue(
        db,
        job_type=config.generate_job_type,
        payload=build_job_payload(
            project_id,
            scope_ids,
            feedback,
            scope_payload_keys=config.scope_payload_keys,
        ),
    )
    return {"job_id": job_id}


def bootstrap_approve(
    db: Session,
    project_id: str,
    scope_ids: tuple[str, ...],
    draft_id: str,
    config: BootstrapTierConfig,
    require_project: Callable,
) -> dict[str, Any]:
    """Generic POST approve handler."""
    require_project(db, project_id)
    node = config.get_node(db, project_id, *scope_ids)
    if node is None:
        raise HTTPException(
            status_code=404,
            detail=f"{config.tier_name} node missing",
        )
    draft = db.get(Draft, draft_id)
    if (
        draft is None
        or draft.project_id != project_id
        or draft.target_type != "node"
        or draft.target_id != node.id
    ):
        raise HTTPException(
            status_code=404,
            detail=f"Draft not found for {config.tier_name}",
        )
    if draft.status != "pending":
        raise HTTPException(
            status_code=409,
            detail=f"Draft is {draft.status!r}, not pending",
        )
    append_event(db, project_id, ev.DraftApproved(draft_id=draft_id))
    commit_and_publish(db, project_id)
    db.refresh(node)
    if config.mint_job_type:
        mint_payload: dict[str, Any] = {"project_id": project_id}
        for idx, sid in enumerate(scope_ids):
            if idx < len(config.scope_payload_keys):
                mint_payload[config.scope_payload_keys[idx]] = sid
        pipeline_queue.enqueue(
            db,
            job_type=config.mint_job_type,
            payload=mint_payload,
        )
    # Phase 7: post-approval hook for side-effects that shouldn't
    # roll back the approval if they fail. Currently used by the
    # impl tier to walk up to the owning domain comp and enqueue
    # fan-in regeneration.
    if config.on_approve is not None:
        try:
            config.on_approve(db, project_id, node, scope_ids)
        except Exception:
            logger.exception(
                "%s on_approve hook failed for node %s — approval already committed, swallowing",
                config.tier_name,
                node.id,
            )
    return {"node": config.serialize_node(node)}


def bootstrap_discard(
    db: Session,
    project_id: str,
    scope_ids: tuple[str, ...],
    draft_id: str,
    config: BootstrapTierConfig,
    require_project: Callable,
) -> dict[str, bool]:
    """Generic POST discard handler."""
    require_project(db, project_id)
    node = config.get_node(db, project_id, *scope_ids)
    if node is None:
        raise HTTPException(
            status_code=404,
            detail=f"{config.tier_name} node missing",
        )
    draft = db.get(Draft, draft_id)
    if (
        draft is None
        or draft.project_id != project_id
        or draft.target_type != "node"
        or draft.target_id != node.id
    ):
        raise HTTPException(
            status_code=404,
            detail=f"Draft not found for {config.tier_name}",
        )
    if draft.status != "pending":
        raise HTTPException(
            status_code=409,
            detail=f"Draft is {draft.status!r}, not pending",
        )
    append_event(db, project_id, ev.DraftDiscarded(draft_id=draft_id))
    commit_and_publish(db, project_id)
    pipeline_queue.enqueue(
        db,
        job_type=config.generate_job_type,
        payload=build_job_payload(
            project_id,
            scope_ids,
            scope_payload_keys=config.scope_payload_keys,
        ),
    )
    return {"ok": True}


def bootstrap_cancel(
    db: Session,
    project_id: str,
    scope_ids: tuple[str, ...],
    config: BootstrapTierConfig,
    require_project: Callable,
) -> dict[str, bool]:
    """Generic POST cancel handler."""
    require_project(db, project_id)
    payload_filters: dict[str, Any] = {"project_id": project_id}
    for idx, sid in enumerate(scope_ids):
        if idx < len(config.scope_payload_keys):
            payload_filters[config.scope_payload_keys[idx]] = sid
    job = pipeline_queue.find_active_job(
        db,
        config.generate_job_type,
        payload_filters=payload_filters,
    )
    if job is None:
        return {"cancelled": False}
    ok = pipeline_queue.cancel_job(db, job.id)
    return {"cancelled": ok}


def bootstrap_retry_review(
    db: Session,
    project_id: str,
    scope_ids: tuple[str, ...],
    config: BootstrapTierConfig,
    require_project: Callable,
) -> dict[str, str]:
    """Manually re-enqueue the AI self-review for this tier's node.

    Called from the per-tier "Retry review" button when the
    previous review job marked itself ``failed`` and the user
    wants another pass. Cancels any currently-stuck review job
    for this node, then enqueues a fresh one.

    Review jobs key on ``node_id`` (the tier node being
    reviewed) — plus ``draft_id`` for draft-bearing tiers or
    ``None`` for fanin. The review handler reassembles context
    from the DB state at run time, so no payload fields need to
    change between retries.

    Raises 404 if the tier has no configured review, or if the
    target node is missing. Raises 409 if there's no draft /
    fanin content to review yet.
    """
    if not config.review_job_type:
        raise HTTPException(
            status_code=404,
            detail=f"{config.tier_name} does not support AI review",
        )
    require_project(db, project_id)
    node = config.get_node(db, project_id, *scope_ids)
    if node is None:
        raise HTTPException(status_code=404, detail=f"{config.tier_name} node missing")

    # Resolve the target of the review: pending draft if one
    # exists, else the node itself (fanin-style). Skip if there's
    # nothing to review yet — avoids firing a review against an
    # empty scope.
    draft = config.get_pending_draft(db, project_id, *scope_ids)
    draft_id: str | None = draft.id if draft is not None else None
    if draft is None and not (node.content or "").strip():
        raise HTTPException(
            status_code=409,
            detail=f"{config.tier_name} has no content to review yet",
        )

    # Cancel any stuck review job for this node before re-enqueueing.
    pipeline_queue.cancel_jobs_by_type(
        db,
        config.review_job_type,
        project_id=project_id,
        node_id=node.id,
    )
    job_id = pipeline_queue.enqueue(
        db,
        job_type=config.review_job_type,
        payload={
            "project_id": project_id,
            "node_id": node.id,
            "draft_id": draft_id,
        },
    )
    return {"job_id": job_id}


def bootstrap_reset(
    db: Session,
    project_id: str,
    scope_ids: tuple[str, ...],
    config: BootstrapTierConfig,
    require_project: Callable,
) -> dict[str, Any]:
    """Generic POST reset handler."""
    if config.collect_downstream_nodes is None:
        raise HTTPException(status_code=501, detail="Reset not supported for this tier")
    require_project(db, project_id)
    node = config.get_node(db, project_id, *scope_ids)
    if node is None:
        raise HTTPException(status_code=404, detail=f"{config.tier_name} node missing")
    if config.has_been_approved is not None:
        if not config.has_been_approved(db, project_id, *scope_ids):
            raise HTTPException(
                status_code=409,
                detail=f"{config.tier_name} is not in approved state",
            )

    jobs_cancelled = 0
    for jt in config.downstream_job_types:
        jobs_cancelled += pipeline_queue.cancel_jobs_by_type(
            db,
            jt,
            project_id=project_id,
        )

    downstream_nodes = config.collect_downstream_nodes(db, project_id, *scope_ids)
    downstream_ids = [n.id for n in downstream_nodes]
    assert config.collect_pending_drafts_for_nodes is not None
    pending_drafts = config.collect_pending_drafts_for_nodes(
        db,
        project_id,
        downstream_ids,
    )
    own_pending = config.get_pending_draft(db, project_id, *scope_ids)

    drafts_discarded = 0
    for draft in pending_drafts:
        append_event(db, project_id, ev.DraftDiscarded(draft_id=draft.id))
        drafts_discarded += 1
    if own_pending is not None:
        append_event(db, project_id, ev.DraftDiscarded(draft_id=own_pending.id))
        drafts_discarded += 1

    additional_drafts = (
        config.additional_drafts_to_discard(db, project_id, *scope_ids)
        if config.additional_drafts_to_discard
        else []
    )
    for maybe_draft in additional_drafts:
        if maybe_draft is not None:
            append_event(db, project_id, ev.DraftDiscarded(draft_id=maybe_draft.id))
            drafts_discarded += 1

    for dn in downstream_nodes:
        append_event(db, project_id, ev.NodeDeleted(node_id=dn.id))

    additional_to_clear = (
        config.additional_nodes_to_clear(db, project_id, *scope_ids)
        if config.additional_nodes_to_clear
        else []
    )
    for clear_node in additional_to_clear:
        if clear_node is not None and clear_node.content:
            append_event(
                db,
                project_id,
                ev.BootstrapNodeContentCleared(node_id=clear_node.id),
            )

    append_event(
        db,
        project_id,
        ev.BootstrapNodeContentCleared(node_id=node.id),
    )
    commit_and_publish(db, project_id)

    pipeline_queue.enqueue(
        db,
        job_type=config.generate_job_type,
        payload=build_job_payload(
            project_id,
            scope_ids,
            scope_payload_keys=config.scope_payload_keys,
        ),
    )
    return {
        "ok": True,
        "nodes_deleted": len(downstream_nodes),
        "drafts_discarded": drafts_discarded,
        "jobs_cancelled": jobs_cancelled,
    }


def bootstrap_prompt_preview(
    db: Session,
    project_id: str,
    scope_ids: tuple[str, ...],
    feedback_text: str,
    config: BootstrapTierConfig,
    require_project: Callable,
) -> dict[str, str]:
    """Generic POST prompt-preview handler."""
    if config.render_prompt_preview is None:
        raise HTTPException(
            status_code=501,
            detail="Prompt preview not supported for this tier",
        )
    require_project(db, project_id)
    node = config.get_node(db, project_id, *scope_ids)
    if node is None:
        raise HTTPException(
            status_code=404,
            detail=f"{config.tier_name} node missing",
        )
    sys_prompt, user_prompt = config.render_prompt_preview(
        db,
        project_id,
        *scope_ids,
        feedback_text,
    )
    return {"system_prompt": sys_prompt, "user_prompt": user_prompt}


# ── Shared helpers ───────────────────────────────────────────────────


def _latest_telemetry(
    db: Session,
    project_id: str,
    node_id: str,
) -> dict[str, Any] | None:
    """Return the most recent telemetry row for a node, or None."""
    from backend.models.telemetry import GenerationTelemetry

    row = (
        db.query(GenerationTelemetry)
        .filter(
            GenerationTelemetry.project_id == project_id,
            GenerationTelemetry.node_id == node_id,
        )
        .order_by(GenerationTelemetry.created_at.desc())
        .first()
    )
    if row is None:
        return None
    return {
        "prompt_tokens": row.prompt_tokens,
        "completion_tokens": row.completion_tokens,
        "model": row.model,
        "created_at": row.created_at.isoformat() if row.created_at else "",
    }
