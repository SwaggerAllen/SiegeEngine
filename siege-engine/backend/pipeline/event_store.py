"""EventStore: append events, update materialized snapshot."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.models.pipeline_events import PipelineEvent, PipelineSnapshot
from backend.pipeline.events import ALL_EVENT_TYPES
from backend.pipeline.reducer import apply_event, empty_snapshot

logger = logging.getLogger(__name__)


class EventStore:
    """Append-only event store with materialized snapshot updates."""

    def __init__(self, db: Session):
        self.db = db

    def emit(
        self,
        project_id: str,
        event_type: str,
        payload: dict[str, Any],
        run_id: str | None = None,
    ) -> PipelineEvent:
        """Append an event and update the materialized snapshot."""
        if event_type not in ALL_EVENT_TYPES:
            raise ValueError(f"Unknown event type: {event_type}")

        seq = self._next_sequence(project_id)
        event = PipelineEvent(
            project_id=project_id,
            run_id=run_id,
            sequence=seq,
            event_type=event_type,
            payload=payload,
        )
        self.db.add(event)

        # Update materialized snapshot
        snapshot = self._get_or_create_snapshot(project_id)
        new_state = apply_event(
            _snapshot_to_dict(snapshot),
            event_type,
            payload,
            seq,
        )
        _update_snapshot_from_dict(snapshot, new_state)

        logger.debug(
            "[EventStore] project=%s seq=%d type=%s run=%s",
            project_id, seq, event_type, run_id,
        )
        return event

    def get_snapshot(self, project_id: str) -> PipelineSnapshot:
        """Get or create the current snapshot for a project."""
        return self._get_or_create_snapshot(project_id)

    def rebuild_snapshot(self, project_id: str) -> PipelineSnapshot:
        """Rebuild snapshot by replaying all events from scratch."""
        snapshot = self._get_or_create_snapshot(project_id)
        state = empty_snapshot()

        events = (
            self.db.query(PipelineEvent)
            .filter_by(project_id=project_id)
            .order_by(PipelineEvent.sequence)
            .all()
        )
        for event in events:
            state = apply_event(state, event.event_type, event.payload, event.sequence)

        _update_snapshot_from_dict(snapshot, state)
        return snapshot

    def _next_sequence(self, project_id: str) -> int:
        """Get the next monotonic sequence number for a project."""
        max_seq = (
            self.db.query(func.max(PipelineEvent.sequence))
            .filter_by(project_id=project_id)
            .scalar()
        )
        return (max_seq or 0) + 1

    def _get_or_create_snapshot(self, project_id: str) -> PipelineSnapshot:
        """Get existing snapshot or create a new one."""
        snapshot = (
            self.db.query(PipelineSnapshot)
            .filter_by(project_id=project_id)
            .first()
        )
        if not snapshot:
            snapshot = PipelineSnapshot(
                project_id=project_id,
                last_sequence=0,
                run_status={},
                stage_statuses={},
                artifact_statuses={},
                is_running=False,
                is_paused=False,
                paused_stage=None,
                current_run_id=None,
            )
            self.db.add(snapshot)
            self.db.flush()
        return snapshot


def _snapshot_to_dict(snapshot: PipelineSnapshot) -> dict[str, Any]:
    """Convert a PipelineSnapshot ORM object to a plain dict for the reducer."""
    return {
        "last_sequence": snapshot.last_sequence,
        "run_status": dict(snapshot.run_status or {}),
        "stage_statuses": dict(snapshot.stage_statuses or {}),
        "artifact_statuses": dict(snapshot.artifact_statuses or {}),
        "is_running": snapshot.is_running,
        "is_paused": snapshot.is_paused,
        "paused_stage": snapshot.paused_stage,
        "current_run_id": snapshot.current_run_id,
    }


def _update_snapshot_from_dict(snapshot: PipelineSnapshot, state: dict[str, Any]) -> None:
    """Write a reducer output dict back to a PipelineSnapshot ORM object."""
    snapshot.last_sequence = state["last_sequence"]
    snapshot.run_status = state["run_status"]
    snapshot.stage_statuses = state["stage_statuses"]
    snapshot.artifact_statuses = state["artifact_statuses"]
    snapshot.is_running = state["is_running"]
    snapshot.is_paused = state["is_paused"]
    snapshot.paused_stage = state["paused_stage"]
    snapshot.current_run_id = state.get("current_run_id")
