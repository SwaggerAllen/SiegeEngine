"""Phase 12 review-batch helpers.

Backs the batched-review walker with two pieces of supporting
state:

* :class:`~backend.models.review.ReviewBatch` — one row per open
  batched-review session. Minted when the user opens the walker
  with the latest graph-event offset pinned, so concurrent writes
  don't shift the stale-node set mid-walk.
* :class:`~backend.models.review.ProjectionSnapshot` — a content-
  addressed cache keyed by ``(project_id, offset)``. Each row
  holds a JSON serialization of
  :func:`backend.graph.queries.projection_snapshot` at that
  offset; the walker's fragment-diff route reads these to
  reconstruct pre-change fragment content without re-running the
  full reducer replay every click.

Both helpers keep the app-code-never-touches-the-ORM-directly
invariant scoped to the event log: these tables are *primary
state*, not projections, so they are written to directly by the
review routes rather than round-tripped through
``append_event``. The reducer's ``rebuild_projections`` does not
wipe them on replay.
"""

from __future__ import annotations

import json
import secrets
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.graph import queries
from backend.graph.reducer import rebuild_projections
from backend.models.project import Project
from backend.models.review import ProjectionSnapshot, ReviewBatch


def _mint_batch_id() -> str:
    """Mint an opaque id for a new review batch.

    Review batches aren't nodes in the event-sourced graph, so they
    don't get a :class:`~backend.graph.ids.Kind` entry. The format
    mirrors the drafts / jobs pattern used elsewhere:
    ``batch_<16 hex chars>``.
    """
    return f"batch_{secrets.token_hex(8)}"


def open_review_batch(session: Session, project_id: str) -> ReviewBatch:
    """Create a new review batch pinned at the project's current offset.

    Pins ``ReviewBatch.pinned_offset = latest_offset(project_id)`` so
    staleness evaluation against the batch is stable under
    concurrent writes — a regen that lands offset ``N+1`` after the
    user opens a batch at offset ``N`` doesn't change which nodes
    the walker has already stepped through.
    """
    if session.get(Project, project_id) is None:
        raise ValueError(f"No project {project_id!r}")
    pinned = queries.latest_offset(session, project_id) or 0
    batch_id = _mint_batch_id()
    batch = ReviewBatch(
        id=batch_id,
        project_id=project_id,
        pinned_offset=pinned,
    )
    session.add(batch)
    session.flush()
    return batch


def close_review_batch(session: Session, batch_id: str) -> ReviewBatch:
    """Stamp ``closed_at`` on an open batch.

    Idempotent: calling with an already-closed batch leaves the
    existing ``closed_at`` timestamp in place and returns the row
    unchanged. Raises ``ValueError`` when the batch id does not
    resolve.
    """
    from datetime import datetime

    batch = session.get(ReviewBatch, batch_id)
    if batch is None:
        raise ValueError(f"No review batch {batch_id!r}")
    if batch.closed_at is None:
        batch.closed_at = datetime.utcnow()
        session.flush()
    return batch


def get_review_batch(session: Session, batch_id: str) -> ReviewBatch | None:
    """Return the batch row, or ``None`` if it doesn't exist."""
    return session.get(ReviewBatch, batch_id)


def get_or_build_snapshot(
    session: Session,
    project_id: str,
    offset: int,
) -> dict[str, Any]:
    """Return the projection snapshot for ``(project_id, offset)``.

    Checks the cache first; on miss, rebuilds the projection at
    ``offset`` inside a nested savepoint, serializes it via
    :func:`backend.graph.queries.projection_snapshot`, rolls the
    savepoint back so the live projection is restored, and then
    persists the serialized payload in ``projection_snapshots`` so
    subsequent calls hit the cache.

    Snapshots are immutable: once written, the row is never
    updated. Cache invalidation is out of scope (garbage-collecting
    stale snapshots is a future concern; offsets identify events
    that never change, so stored snapshots never go out of date).
    """
    cached = session.execute(
        select(ProjectionSnapshot).where(
            ProjectionSnapshot.project_id == project_id,
            ProjectionSnapshot.offset == offset,
        )
    ).scalar_one_or_none()
    if cached is not None:
        return json.loads(cached.payload_blob)

    payload = _build_snapshot_payload(session, project_id, offset)
    row = ProjectionSnapshot(
        project_id=project_id,
        offset=offset,
        payload_blob=json.dumps(payload, default=_json_default),
    )
    session.add(row)
    session.flush()
    return payload


def _build_snapshot_payload(
    session: Session,
    project_id: str,
    offset: int,
) -> dict[str, Any]:
    """Replay events up to ``offset`` inside a savepoint and serialize.

    ``rebuild_projections`` wipes and repopulates the project's
    projection tables; running it on the main session would destroy
    the live state. Wrapping in ``session.begin_nested()`` and
    rolling back after serialization restores the live projection
    automatically via the savepoint. ``expire_all`` then drops any
    identity-map references to the rolled-back rows so downstream
    ORM reads re-fetch the restored rows.
    """
    # Guard against snapshots at offsets that don't exist — keep
    # the cache from filling with empty rows for out-of-range
    # queries. ``offset=0`` means "before any events" and is
    # legitimate.
    if offset < 0:
        raise ValueError(f"offset must be >= 0, got {offset}")
    max_offset = queries.latest_offset(session, project_id) or 0
    if offset > max_offset:
        raise ValueError(f"offset {offset} is past project's latest offset {max_offset}")

    # Expire before AND after: the reducer's ``rebuild_projections``
    # issues bulk deletes that bypass the identity map, and then
    # inserts fresh rows with the same primary keys. Without
    # clearing the identity map the flush produces noisy SAWarning
    # "identity already had an identity" messages. The post-
    # rollback expire restores the map to match the live rows.
    session.expire_all()
    savepoint = session.begin_nested()
    try:
        rebuild_projections(session, project_id, up_to_offset=offset)
        payload = queries.projection_snapshot(session, project_id)
        # ``projection_snapshot`` returns live ORM-adjacent dicts;
        # they reference only primitives already, but explicitly
        # JSON-roundtrip ensures we don't return a structure that
        # pickles a rolled-back row by accident.
        payload_json = json.dumps(payload, default=_json_default)
    finally:
        savepoint.rollback()
        session.expire_all()
    return json.loads(payload_json)


def _json_default(value: Any) -> Any:
    """JSON default serializer for anything ``projection_snapshot`` returns.

    Only used defensively — the dict shape is all primitives today
    (strings, ints, lists, nested dicts). ``datetime`` is the one
    non-JSON-native type that has historically snuck through; it
    lands as an ISO-8601 string for stable round-tripping.
    """
    from datetime import date, datetime

    if isinstance(value, datetime | date):
        return value.isoformat()
    raise TypeError(f"Not JSON-serializable: {type(value).__name__}")
