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
from backend.graph.fragments import fragment_id
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
    # Per-tier fragment slots to clear on reset. Returns a list of
    # ``(owner_id, FragmentKind)`` pairs whose fragment row content
    # should be wiped via a ``FragmentUpdated`` event with
    # ``new_content=""``. Used by the layered-fragment model so a
    # comparch / subcomparch reset clears just the rich layer kinds
    # it owns (``comparch*`` / ``subcomparch*``) without touching
    # the lower-tier sysarch / comparch-mint skeletal seeds in the
    # legacy slots. See ``backend/graph/fragments.py``.
    # Signature: (db, project_id, *scope_ids) -> list[tuple[str, FragmentKind]]
    additional_fragment_kinds_to_clear: Callable[..., list] | None = None

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
            review_started_at,
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
        review_started_at = None
        review_current_attempt = None
        review_max_attempts = None

    # Phase 9 — staleness on the per-tier panel. The frontend
    # surfaces "upstream X changed, this tier is stale" above the
    # draft view so the user knows why the panel might re-regen.
    # Read from the ledger directly rather than going through the
    # bulk helper — one node lookup is cheaper than scanning the
    # whole project.
    staleness_rows = queries.staleness_entries_for(db, project_id, node.id)
    stale_reasons: list[str] = []
    for row in staleness_rows:
        if row.reason not in stale_reasons:
            stale_reasons.append(row.reason)

    # Phase 12 — regen-time diff "before" content. When the user
    # hits Reject & Regenerate, ``_apply_draft_discarded`` flips
    # the prior pending draft to ``status="discarded"`` without
    # deleting the row, so the most-recent-discarded content is
    # the natural "before" side of a pending-before-vs-pending-
    # after diff. On the very first regen after approval there is
    # no discarded draft yet and the frontend falls back to the
    # approved node content. Brand-new bootstraps have neither,
    # and the panel renders the raw draft.
    previous_draft_content = queries.most_recent_discarded_draft_content(
        db,
        project_id,
        node.id,
    )
    # Phase 12 auto-revision — intermediates produced by the AI-
    # driven revision loop, scoped to the current regen run. Empty
    # list on drafts generated before the loop shipped or when
    # auto_revisions_requested=0. The frontend renders these as
    # additional entries in the diff's "Compare against" dropdown
    # below the default "Pre-regen" baseline.
    intermediates = queries.auto_revision_intermediates(
        db,
        project_id,
        node.id,
    )

    # Doc-page header — "last regenerated" timestamps. The job summary
    # shows the latest generation job in its raw status (so cancelled
    # jobs surface as cancelled, not folded into idle), and the
    # content-updated timestamp is the most recent NodeContentUpdated
    # event so users can see when the content they're looking at
    # actually landed.
    last_job = queries.latest_generation_job_summary(
        db,
        project_id,
        config.generate_job_type,
        payload_filters=payload_filters if payload_filters else None,
    )
    last_content_updated_at = queries.last_node_content_updated_at(db, project_id, node.id)

    return {
        "node": config.serialize_node(node),
        "pending_draft": config.serialize_draft(draft) if draft else None,
        "previous_draft_content": previous_draft_content,
        "auto_revision_intermediates": [
            {
                "label": it.label,
                "content": it.content,
                "auto_revision_pass": it.auto_revision_pass,
                "change_summary": it.change_summary,
            }
            for it in intermediates
        ],
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
        "review_started_at": review_started_at,
        "review_current_attempt": review_current_attempt,
        "review_max_attempts": review_max_attempts,
        "is_stale": bool(stale_reasons),
        "staleness_reasons": stale_reasons,
        "last_generation_job": (
            {
                "status": last_job.status,
                "created_at": last_job.created_at,
                "completed_at": last_job.completed_at,
                "error_message": last_job.error_message,
            }
            if last_job is not None
            else None
        ),
        "last_content_updated_at": last_content_updated_at,
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
    *,
    auto_revisions_requested: int = 0,
) -> dict[str, str]:
    """Generic POST feedback handler.

    ``auto_revisions_requested`` (Phase 12) — forwarded verbatim
    into the generate job payload as ``auto_revisions_remaining``
    along with ``auto_revision_pass=0`` (user-initiated). Tiers
    that support the auto-revision loop read those fields and
    drive inline review passes from the handler. Tiers that don't
    yet react to the fields carry them harmlessly.
    """
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
    if auto_revisions_requested < 0:
        raise HTTPException(
            status_code=422,
            detail="auto_revisions_requested must be >= 0",
        )

    # Capture the currently-pending draft's review_text BEFORE the
    # clear below so the regen prompt can surface the AI critique
    # alongside any user feedback. Without this, the regen sees only
    # the prior draft content + user feedback, and the AI review's
    # recommendations stay trapped on the about-to-be-discarded draft
    # row — the model has no way to read them.
    current_pending = config.get_pending_draft(db, project_id, *scope_ids)
    prior_review_text = (
        (current_pending.review_text or "").strip() if current_pending is not None else ""
    )

    # Clear the currently-pending draft's review_text and cancel
    # any in-flight review job for it. The old review is about to
    # become a review of content no longer on the pending slot, so
    # surfacing it during the regen window is confusing — the user
    # sees critique that doesn't apply to the draft that will
    # actually land. ``persist_draft`` already cancels the stale
    # review job when it discards the prior pending draft; doing
    # it here too keeps the UI honest during the enqueue→commit
    # window. The captured ``prior_review_text`` above rides on
    # the regen payload, so clearing the row here doesn't lose it.
    if current_pending is not None and prior_review_text:
        append_event(
            db,
            project_id,
            ev.DraftReviewUpdated(
                draft_id=current_pending.id,
                node_id=node.id,
                review_text="",
            ),
        )
        if config.review_job_type:
            pipeline_queue.cancel_jobs_by_type(
                db,
                config.review_job_type,
                project_id=project_id,
                draft_id=current_pending.id,
            )
        commit_and_publish(db, project_id)

    feedback = (feedback_text or "").strip() or None
    payload = build_job_payload(
        project_id,
        scope_ids,
        feedback,
        scope_payload_keys=config.scope_payload_keys,
    )
    if prior_review_text:
        payload["prior_review_text"] = prior_review_text
    if auto_revisions_requested > 0:
        # Seed the auto-revision loop. Tiers that handle the fields
        # (requirements today) read them in their generate handler;
        # others carry them harmlessly.
        payload["auto_revision_pass"] = 0
        payload["auto_revisions_remaining"] = auto_revisions_requested
    job_id = pipeline_queue.enqueue(
        db,
        job_type=config.generate_job_type,
        payload=payload,
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
    append_event(
        db,
        project_id,
        ev.DraftDiscarded(draft_id=draft_id, reason="user_regen"),
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
        priority=pipeline_queue.REVIEW_JOB_PRIORITY,
    )
    return {"job_id": job_id}


def bootstrap_reset(
    db: Session,
    project_id: str,
    scope_ids: tuple[str, ...],
    config: BootstrapTierConfig,
    require_project: Callable,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """Generic POST reset handler.

    ``force=True`` skips the ``has_been_approved`` gate. The per-
    tier per-node Reset & Regenerate buttons run with the default
    ``force=False`` because their UI only mounts in the approved
    state, so the gate doubles as a defence-in-depth check. The
    bulk tier-ops sweep passes ``force=True`` because the operator
    intent is "wipe everything in this tier and regenerate" — a
    pending-draft-only node should still be discardable + regen-
    able, not 409 the whole sweep.
    """
    if config.collect_downstream_nodes is None:
        raise HTTPException(status_code=501, detail="Reset not supported for this tier")
    require_project(db, project_id)
    node = config.get_node(db, project_id, *scope_ids)
    if node is None:
        raise HTTPException(status_code=404, detail=f"{config.tier_name} node missing")
    if not force and config.has_been_approved is not None:
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
        append_event(
            db,
            project_id,
            ev.DraftDiscarded(draft_id=draft.id, reason="user_regen"),
        )
        drafts_discarded += 1
    if own_pending is not None:
        append_event(
            db,
            project_id,
            ev.DraftDiscarded(draft_id=own_pending.id, reason="user_regen"),
        )
        drafts_discarded += 1

    additional_drafts = (
        config.additional_drafts_to_discard(db, project_id, *scope_ids)
        if config.additional_drafts_to_discard
        else []
    )
    for maybe_draft in additional_drafts:
        if maybe_draft is not None:
            append_event(
                db,
                project_id,
                ev.DraftDiscarded(draft_id=maybe_draft.id, reason="user_regen"),
            )
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

    if config.additional_fragment_kinds_to_clear is not None:
        for owner_id, frag_kind in config.additional_fragment_kinds_to_clear(
            db, project_id, *scope_ids
        ):
            append_event(
                db,
                project_id,
                ev.FragmentUpdated(
                    fragment_id=fragment_id(owner_id, frag_kind),
                    owner_id=owner_id,
                    fragment_kind=frag_kind,
                    new_content="",
                ),
            )

    append_event(
        db,
        project_id,
        ev.BootstrapNodeContentCleared(node_id=node.id),
    )
    # Mark a cutoff so the Feedback History panel stops showing prose
    # feedback and AI review text from before this reset. The prior
    # entries remain in the immutable event log + Job/Draft rows, but
    # the read path filters them out past this timestamp.
    append_event(
        db,
        project_id,
        ev.FeedbackCleared(node_id=node.id),
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
    """Return the most recent *generation* telemetry row for a node.

    ``GenerationTelemetry`` rows are written by both the generation
    pass (``section=<tier>``: ``expansion`` / ``requirements`` /
    ``sysarch`` / etc.) and the AI self-review pass
    (``section="review"``). The review pass runs right after
    generation, so if the filter didn't exclude review rows the
    "Last gen" display would show review token counts instead of
    the real generation's counts. Explicitly skip review rows so
    the panel reports what the label claims.
    """
    from backend.models.telemetry import GenerationTelemetry

    row = (
        db.query(GenerationTelemetry)
        .filter(
            GenerationTelemetry.project_id == project_id,
            GenerationTelemetry.node_id == node_id,
            GenerationTelemetry.section != "review",
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
