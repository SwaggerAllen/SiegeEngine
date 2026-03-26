"""Pure reducer function for pipeline event sourcing.

apply_event(snapshot_dict, event) -> snapshot_dict

No DB access. No side effects. Deterministic state transitions.
"""

from __future__ import annotations

import copy
from typing import Any

from backend.pipeline.events import (
    AI_REVIEW_COMPLETED,
    AI_REVIEW_STARTED,
    ARTIFACT_COMMITTED,
    ARTIFACT_PRUNED,
    ARTIFACT_REVISED,
    AWAITING_HUMAN_REVIEW,
    CARRIED_OVER,
    CASCADE_COMPLETED,
    CASCADE_STARTED,
    COMMENT_ADDED,
    FEEDBACK_SAVED,
    GENERATION_COMPLETED,
    GENERATION_PROGRESS,
    HUMAN_APPROVED,
    HUMAN_REJECTED,
    PIPELINE_PAUSED,
    PIPELINE_RESET,
    PIPELINE_RESUMED,
    RUN_COMPLETED,
    RUN_CREATED,
    STAGE_FAILED,
    STAGE_QUEUED,
    STAGE_RETRIED,
    STAGE_SKIPPED,
    STAGE_STARTED,
    STALE_RESOLVED,
    STALENESS_PROPAGATED,
)


def empty_snapshot() -> dict[str, Any]:
    """Return a fresh, empty snapshot dict."""
    return {
        "last_sequence": 0,
        "run_status": {},
        "stage_statuses": {},
        "artifact_statuses": {},
        "is_running": False,
        "is_paused": False,
        "paused_stage": None,
        "current_run_id": None,
        # New: artifact versions at each point in time
        "artifact_versions": {},
        # New: error messages per stage
        "stage_errors": {},
        # New: active comment counts per artifact
        "comment_counts": {},
        # New: last trigger per stage
        "stage_triggers": {},
        # New: artifact metadata (type + name)
        "artifact_meta": {},
        # New: git commit SHAs per artifact
        "artifact_git_shas": {},
        # New: cascade parent run relationships
        "cascade_parents": {},
        # New: execution ID + artifact ID per stage/component
        "execution_map": {},
        # Staleness as a separate boolean layer (artifact_id → True/False)
        "artifact_stale": {},
    }


def apply_event(
    snapshot: dict[str, Any],
    event_type: str,
    payload: dict,
    sequence: int,
) -> dict[str, Any]:
    """Apply a single event to a snapshot dict. Returns new snapshot (does NOT mutate input)."""
    snap = copy.deepcopy(snapshot)
    # Ensure new fields exist for snapshots created before they were added
    _ensure_new_fields(snap)
    handler = _HANDLERS.get(event_type)
    if handler:
        handler(snap, payload)
    snap["last_sequence"] = sequence
    return snap


def _ensure_new_fields(snap: dict) -> None:
    """Backfill new snapshot fields for older snapshots."""
    for field in (
        "artifact_versions",
        "stage_errors",
        "comment_counts",
        "stage_triggers",
        "artifact_meta",
        "artifact_git_shas",
        "cascade_parents",
        "execution_map",
    ):
        if field not in snap:
            snap[field] = {}


# ---------------------------------------------------------------------------
# Individual event handlers (mutate snap in-place, called from apply_event)
# ---------------------------------------------------------------------------


def _handle_run_created(snap: dict, p: dict) -> None:
    run_id = p["run_id"]
    snap["run_status"][run_id] = "running"
    snap["is_running"] = True
    snap["is_paused"] = False
    snap["paused_stage"] = None
    snap["current_run_id"] = run_id


def _handle_run_completed(snap: dict, p: dict) -> None:
    run_id = p["run_id"]
    snap["run_status"][run_id] = p.get("status", "completed")
    # Only clear running if this is the current run
    if snap.get("current_run_id") == run_id:
        snap["is_running"] = False
        snap["is_paused"] = False
        snap["paused_stage"] = None


def _handle_stage_queued(snap: dict, p: dict) -> None:
    key = _stage_key(p)
    snap["stage_statuses"][key] = "pending"
    # Track execution in execution_map
    if p.get("execution_id"):
        entry: dict = {"execution_id": p["execution_id"]}
        if p.get("artifact_id"):
            entry["artifact_id"] = p["artifact_id"]
        snap["execution_map"][key] = entry


def _handle_stage_started(snap: dict, p: dict) -> None:
    key = _exec_to_stage_key(snap, p)
    snap["stage_statuses"][key] = "running"
    snap["is_running"] = True
    snap["is_paused"] = False
    snap["paused_stage"] = None
    # Update artifact status if present
    if p.get("artifact_id"):
        snap["artifact_statuses"][p["artifact_id"]] = "generating"
    # Track trigger
    if p.get("trigger"):
        snap["stage_triggers"][key] = p["trigger"]
    # Track retry count
    if p.get("retry_count") is not None:
        snap["stage_errors"].setdefault(key, {})
        snap["stage_errors"][key]["retry_count"] = p["retry_count"]
    # Track execution in execution_map
    if p.get("execution_id"):
        entry: dict = {"execution_id": p["execution_id"]}
        if p.get("artifact_id"):
            entry["artifact_id"] = p["artifact_id"]
        snap["execution_map"][key] = entry
    # Track artifact metadata
    _update_artifact_meta(snap, p)


def _handle_generation_completed(snap: dict, p: dict) -> None:
    if p.get("artifact_id"):
        snap["artifact_statuses"][p["artifact_id"]] = "ai_reviewing"
    _update_artifact_meta(snap, p)


def _handle_ai_review_started(snap: dict, p: dict) -> None:
    key = _exec_to_stage_key(snap, p)
    snap["stage_statuses"][key] = "ai_review"
    if p.get("artifact_id"):
        snap["artifact_statuses"][p["artifact_id"]] = "ai_reviewing"


def _handle_ai_review_completed(snap: dict, p: dict) -> None:
    # After AI review, status depends on whether it passed
    pass  # The next event (awaiting_human_review or stage_failed) sets the status


def _handle_awaiting_human_review(snap: dict, p: dict) -> None:
    key = _exec_to_stage_key(snap, p)
    snap["stage_statuses"][key] = "awaiting_review"
    if p.get("artifact_id"):
        snap["artifact_statuses"][p["artifact_id"]] = "awaiting_review"


def _handle_human_approved(snap: dict, p: dict) -> None:
    key = _exec_to_stage_key(snap, p)
    snap["stage_statuses"][key] = "approved"
    if p.get("artifact_id"):
        snap["artifact_statuses"][p["artifact_id"]] = "approved"
    # Clear error on approval
    snap["stage_errors"].pop(key, None)


def _handle_human_rejected(snap: dict, p: dict) -> None:
    key = _exec_to_stage_key(snap, p)
    snap["stage_statuses"][key] = "rejected"
    if p.get("artifact_id"):
        snap["artifact_statuses"][p["artifact_id"]] = "rejected"


def _handle_feedback_saved(snap: dict, p: dict) -> None:
    # Feedback doesn't change status — it's saved alongside the current state
    pass


def _handle_stage_failed(snap: dict, p: dict) -> None:
    key = _exec_to_stage_key(snap, p)
    snap["stage_statuses"][key] = "failed"
    if p.get("artifact_id"):
        # Preserve artifact status if it was already reviewed — a stage
        # failure (e.g. cancellation) shouldn't nuke a valid artifact.
        # Exception: force_restart is an explicit user action that should
        # always reset the artifact to pending so regeneration can start.
        is_force_restart = p.get("trigger") == "force_restart"
        current = snap["artifact_statuses"].get(p["artifact_id"])
        if is_force_restart:
            snap["artifact_statuses"][p["artifact_id"]] = "pending"
        elif current not in ("approved", "awaiting_review", "rejected"):
            snap["artifact_statuses"][p["artifact_id"]] = "failed"
    # Track error message
    if p.get("error"):
        snap["stage_errors"][key] = {
            "error": p["error"],
            "retry_count": p.get("retry_count"),
        }


def _handle_stage_skipped(snap: dict, p: dict) -> None:
    key = _exec_to_stage_key(snap, p)
    snap["stage_statuses"][key] = "skipped"


def _handle_artifact_revised(snap: dict, p: dict) -> None:
    artifact_id = p["artifact_id"]
    snap["artifact_statuses"][artifact_id] = "generating"
    # The associated stage goes to running
    if p.get("stage_key"):
        key = _stage_key(p)
        snap["stage_statuses"][key] = "running"
    # Track version bump
    if p.get("version") is not None:
        snap["artifact_versions"][artifact_id] = p["version"]


def _handle_stale_resolved(snap: dict, p: dict) -> None:
    artifact_id = p["artifact_id"]
    action = p.get("action", "approved")
    # Clear the stale flag
    snap.setdefault("artifact_stale", {})[artifact_id] = False
    if action == "approved":
        snap["artifact_statuses"][artifact_id] = "approved"
    elif action == "rejected":
        snap["artifact_statuses"][artifact_id] = "rejected"
    # Stage status updated accordingly
    if p.get("stage_key"):
        key = _stage_key(p)
        snap["stage_statuses"][key] = action


def _handle_staleness_propagated(snap: dict, p: dict) -> None:
    stale_dict = snap.setdefault("artifact_stale", {})
    for aid in p.get("stale_ids", []):
        stale_dict[aid] = True


def _handle_cascade_started(snap: dict, p: dict) -> None:
    snap["is_running"] = True
    run_id = p.get("run_id")
    if run_id:
        snap["run_status"][run_id] = "running"
        snap["current_run_id"] = run_id
    # Track parent relationship
    if run_id and p.get("parent_run_id"):
        snap["cascade_parents"][run_id] = p["parent_run_id"]


def _handle_cascade_completed(snap: dict, p: dict) -> None:
    snap["is_running"] = False
    if p.get("run_id"):
        snap["run_status"][p["run_id"]] = "completed"


def _handle_carried_over(snap: dict, p: dict) -> None:
    key = _exec_to_stage_key(snap, p)
    snap["stage_statuses"][key] = "approved"
    if p.get("artifact_id"):
        snap["artifact_statuses"][p["artifact_id"]] = "approved"


def _handle_artifact_pruned(snap: dict, p: dict) -> None:
    artifact_id = p["artifact_id"]
    snap["artifact_statuses"].pop(artifact_id, None)
    snap["artifact_versions"].pop(artifact_id, None)
    snap["artifact_meta"].pop(artifact_id, None)
    snap["artifact_git_shas"].pop(artifact_id, None)
    snap["comment_counts"].pop(artifact_id, None)
    snap.setdefault("artifact_stale", {}).pop(artifact_id, None)
    # Remove stage status and execution_map entry if provided
    if p.get("stage_key"):
        key = _stage_key(p)
        snap["stage_statuses"].pop(key, None)
        snap["execution_map"].pop(key, None)


def _handle_pipeline_reset(snap: dict, p: dict) -> None:
    # Put all artifacts into awaiting_review, clear running state
    for aid in snap["artifact_statuses"]:
        snap["artifact_statuses"][aid] = "awaiting_review"
    for key in snap["stage_statuses"]:
        snap["stage_statuses"][key] = "awaiting_review"
    # Cancel any runs still marked as running
    for run_id, status in snap["run_status"].items():
        if status == "running":
            snap["run_status"][run_id] = "cancelled"
    snap["is_running"] = False
    snap["is_paused"] = False
    snap["paused_stage"] = None
    snap["stage_errors"].clear()
    snap["stage_triggers"].clear()
    snap["execution_map"].clear()
    # Clear all stale flags
    snap.setdefault("artifact_stale", {}).clear()


def _handle_stage_retried(snap: dict, p: dict) -> None:
    key = _exec_to_stage_key(snap, p)
    snap["stage_statuses"][key] = "pending"
    if p.get("artifact_id"):
        snap["artifact_statuses"][p["artifact_id"]] = "pending"


def _handle_comment_added(snap: dict, p: dict) -> None:
    artifact_id = p.get("artifact_id")
    if artifact_id:
        snap["comment_counts"][artifact_id] = snap["comment_counts"].get(artifact_id, 0) + 1


def _handle_generation_progress(snap: dict, p: dict) -> None:
    # Progress events are informational — no state change needed
    pass


def _handle_pipeline_paused(snap: dict, p: dict) -> None:
    snap["is_paused"] = True
    snap["paused_stage"] = p.get("stage_key")


def _handle_pipeline_resumed(snap: dict, p: dict) -> None:
    snap["is_paused"] = False
    snap["paused_stage"] = None


def _handle_artifact_committed(snap: dict, p: dict) -> None:
    artifact_id = p.get("artifact_id")
    if artifact_id:
        if p.get("git_commit_sha"):
            snap["artifact_git_shas"][artifact_id] = p["git_commit_sha"]
        if p.get("version") is not None:
            snap["artifact_versions"][artifact_id] = p["version"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _stage_key(p: dict) -> str:
    """Build a composite key from stage_key + optional component_key."""
    sk = p.get("stage_key", "")
    ck = p.get("component_key")
    return f"{sk}/{ck}" if ck else sk


def _exec_to_stage_key(snap: dict, p: dict) -> str:
    """Resolve the stage key from event payload.

    Events may carry stage_key/component_key directly, or only execution_id.
    For now we require stage_key in the payload; later phases can add an
    execution_id → stage_key mapping to the snapshot.
    """
    return _stage_key(p)


def _update_artifact_meta(snap: dict, p: dict) -> None:
    """Track artifact type, name, and component_key in snapshot if provided."""
    artifact_id = p.get("artifact_id")
    if artifact_id:
        meta = snap["artifact_meta"].get(artifact_id, {})
        if p.get("artifact_type"):
            meta["type"] = p["artifact_type"]
        if p.get("artifact_name"):
            meta["name"] = p["artifact_name"]
        if "component_key" in p:
            meta["component_key"] = p["component_key"]
        if meta:
            snap["artifact_meta"][artifact_id] = meta


_HANDLERS: dict[str, Any] = {
    RUN_CREATED: _handle_run_created,
    RUN_COMPLETED: _handle_run_completed,
    STAGE_QUEUED: _handle_stage_queued,
    STAGE_STARTED: _handle_stage_started,
    GENERATION_COMPLETED: _handle_generation_completed,
    AI_REVIEW_STARTED: _handle_ai_review_started,
    AI_REVIEW_COMPLETED: _handle_ai_review_completed,
    AWAITING_HUMAN_REVIEW: _handle_awaiting_human_review,
    HUMAN_APPROVED: _handle_human_approved,
    HUMAN_REJECTED: _handle_human_rejected,
    FEEDBACK_SAVED: _handle_feedback_saved,
    STAGE_FAILED: _handle_stage_failed,
    STAGE_SKIPPED: _handle_stage_skipped,
    ARTIFACT_REVISED: _handle_artifact_revised,
    STALE_RESOLVED: _handle_stale_resolved,
    STALENESS_PROPAGATED: _handle_staleness_propagated,
    CASCADE_STARTED: _handle_cascade_started,
    CASCADE_COMPLETED: _handle_cascade_completed,
    CARRIED_OVER: _handle_carried_over,
    ARTIFACT_PRUNED: _handle_artifact_pruned,
    PIPELINE_RESET: _handle_pipeline_reset,
    STAGE_RETRIED: _handle_stage_retried,
    COMMENT_ADDED: _handle_comment_added,
    GENERATION_PROGRESS: _handle_generation_progress,
    PIPELINE_PAUSED: _handle_pipeline_paused,
    PIPELINE_RESUMED: _handle_pipeline_resumed,
    ARTIFACT_COMMITTED: _handle_artifact_committed,
}
