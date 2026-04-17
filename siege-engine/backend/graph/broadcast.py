"""In-process per-project pub/sub for the workspace SSE stream.

Every committed write in the structured model produces a
``GraphEvent`` row with an assigned per-project offset. Clients
watching a project's workspace want a low-latency signal that
*something changed* so they can invalidate cached queries without
polling. This module owns that channel.

Design:

- **Single writer.** The current deployment runs one FastAPI
  process per instance. We use pure ``asyncio`` primitives — one
  event loop, no cross-process synchronization. Horizontal
  scaling will require a cross-process backend (Redis pub/sub,
  NATS, Postgres ``LISTEN/NOTIFY``) and is explicitly out of
  scope for now.
- **Publish after commit.** The broadcaster is intentionally
  not wired into ``reducer.append_event`` — publishing inside
  the reducer transaction would let a failed broadcast roll
  back projection state. Instead, write-route handlers call
  ``commit_and_publish(db, project_id)`` in place of
  ``db.commit()``. The helper commits first, then drains the
  ``session.info`` offset stash into broadcast messages.
- **Ring-buffer replay.** Each project keeps a small deque of
  recent messages (default ≈200). Subscribers can request
  ``since=<offset>``; the broadcaster replays everything newer
  than the given offset from the buffer before switching to
  live. This closes the race where an event commits between
  a client's snapshot fetch and its SSE subscribe.
- **Bounded per-subscriber queue.** Each subscriber gets its
  own ``asyncio.Queue`` (maxsize small — 256). A slow
  subscriber that can't drain fast enough is dropped rather
  than allowed to back-pressure the publisher. The client
  reconnects and re-fetches the snapshot on the next SSE
  error event.

Public surface:

- :class:`BroadcastMessage` — the small payload shape clients
  receive.
- :class:`ProjectBroadcaster` — per-process singleton; use
  :func:`get_broadcaster` to access.
- :func:`stash_offset` — call from ``reducer.append_event``
  after a successful ``session.flush`` to record the offset
  for later publish.
- :func:`commit_and_publish` — replacement for ``db.commit()``
  in write-route handlers. Commits, then drains the stash and
  fans out to subscribers.
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models.graph_event import GraphEvent

logger = logging.getLogger(__name__)

# Ring-buffer size per project. Large enough to cover a
# disconnected client reconnecting within a second or two of a
# burst of events (e.g. comparch approval fans out ~20-30
# events across subcomps + impls). Clients that fall further
# behind than this get a full snapshot refetch on reconnect,
# which is the correct fall-back.
_RING_BUFFER_MAXLEN = 256

# Per-subscriber queue bound. A subscriber that can't drain 256
# messages fast enough gets dropped; the client's SSE reconnect
# path re-seeds from /structure. Prevents a single slow client
# from pinning memory for everyone.
_SUBSCRIBER_QUEUE_MAXSIZE = 256


@dataclass(frozen=True)
class BroadcastMessage:
    """A single SSE event payload.

    Deliberately minimal — clients use this as a refetch
    trigger, not as state. Full event bodies stay in
    ``graph_events`` for replay/audit.
    """

    offset: int
    event_type: str
    node_ids: tuple[str, ...]

    def to_payload(self) -> dict[str, Any]:
        return {
            "offset": self.offset,
            "event_type": self.event_type,
            "node_ids": list(self.node_ids),
        }


def _node_ids_for_event(event_type: str, payload: dict[str, Any]) -> tuple[str, ...]:
    """Derive the ``node_ids`` affected by a given event.

    Used by :func:`commit_and_publish` to build messages from
    the serialized event payloads in ``graph_events``. Keeps
    the per-tier-key knowledge here rather than scattered
    across route handlers.
    """
    match event_type:
        case (
            "NodeCreated"
            | "NodeRenamed"
            | "NodeReparented"
            | "NodePromoted"
            | "NodeDemoted"
            | "NodeDeleted"
            | "BootstrapNodeContentCleared"
            | "FanInContentUpdated"
        ):
            nid = payload.get("node_id")
            return (nid,) if isinstance(nid, str) else ()
        case "NodesMerged":
            dest = payload.get("dest_id")
            sources = payload.get("source_ids") or []
            ids = [dest] + list(sources) if isinstance(dest, str) else list(sources)
            return tuple(i for i in ids if isinstance(i, str))
        case "NodeSplit":
            src = payload.get("source_id")
            dests = payload.get("dest_ids") or []
            ids = [src] + list(dests) if isinstance(src, str) else list(dests)
            return tuple(i for i in ids if isinstance(i, str))
        case "EdgeCreated" | "EdgeDeleted":
            src = payload.get("source_id")
            tgt = payload.get("target_id")
            return tuple(i for i in (src, tgt) if isinstance(i, str))
        case "FragmentUpdated":
            owner = payload.get("owner_id")
            return (owner,) if isinstance(owner, str) else ()
        case "DraftGenerated" | "DraftEdited":
            # target_id is the node (or fragment) the draft
            # targets; include it so the frontend can map to
            # the tier detail key.
            tgt = payload.get("target_id")
            return (tgt,) if isinstance(tgt, str) else ()
        case "DraftApproved" | "DraftDiscarded":
            # These carry only a draft_id — the frontend
            # resolver has to follow the draft to its target
            # from the cached structure. We still emit the
            # event so the stream stays complete; the frontend
            # will invalidate structure and let downstream
            # refetches settle the state.
            return ()
        case _:
            return ()


class ProjectBroadcaster:
    """Per-process fan-out hub for project SSE subscribers.

    Thread model: all interactions happen on the FastAPI event
    loop. ``publish`` is synchronous (called from request
    handlers); ``subscribe`` is an async generator consumed by
    the SSE route. No locks needed — single event loop gives
    cooperative mutual exclusion.
    """

    def __init__(self, ring_buffer_maxlen: int = _RING_BUFFER_MAXLEN) -> None:
        self._ring_buffers: dict[str, deque[BroadcastMessage]] = {}
        self._subscribers: dict[str, set[asyncio.Queue[BroadcastMessage]]] = {}
        self._maxlen = ring_buffer_maxlen

    def publish(self, project_id: str, message: BroadcastMessage) -> None:
        """Fan a message out to every live subscriber + ring buffer.

        Synchronous by design — call from a regular request
        handler after ``db.commit()``. Slow subscribers (queues
        full) are dropped silently; their SSE reconnect path
        will re-seed state via /structure.
        """
        buf = self._ring_buffers.setdefault(project_id, deque(maxlen=self._maxlen))
        buf.append(message)

        subs = self._subscribers.get(project_id)
        if not subs:
            return
        dropped: list[asyncio.Queue[BroadcastMessage]] = []
        for queue in subs:
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                logger.warning(
                    "broadcast: dropping slow subscriber on project %s (queue full)",
                    project_id,
                )
                dropped.append(queue)
        for q in dropped:
            subs.discard(q)

    async def subscribe(
        self,
        project_id: str,
        since_offset: int | None = None,
    ) -> AsyncIterator[BroadcastMessage]:
        """Async iterator over live messages for a project.

        If ``since_offset`` is provided, replays buffered
        messages with ``offset > since_offset`` before switching
        to live. This closes the race between a client's
        snapshot fetch and its SSE subscribe — the client reads
        the snapshot's current offset, then subscribes with
        ``since=<that offset>`` to ensure no events are lost.

        Exit semantics: the iterator runs until the caller
        stops iterating (e.g. client disconnects; SSE route's
        task cancellation). The broadcaster deregisters the
        subscriber queue in a ``finally`` block.
        """
        queue: asyncio.Queue[BroadcastMessage] = asyncio.Queue(maxsize=_SUBSCRIBER_QUEUE_MAXSIZE)
        subs = self._subscribers.setdefault(project_id, set())
        subs.add(queue)
        try:
            # Replay buffered history first. Done synchronously
            # so the client sees history before any live event.
            if since_offset is not None:
                buf = self._ring_buffers.get(project_id)
                if buf:
                    for msg in list(buf):
                        if msg.offset > since_offset:
                            yield msg

            while True:
                msg = await queue.get()
                yield msg
        finally:
            subs.discard(queue)
            if not subs:
                # Leave the ring buffer intact even when no
                # subscribers — a reconnect within a few
                # seconds should still see recent history.
                self._subscribers.pop(project_id, None)

    # ── Test-only introspection ─────────────────────────────────
    def _subscriber_count(self, project_id: str) -> int:
        return len(self._subscribers.get(project_id, ()))

    def _ring_buffer_size(self, project_id: str) -> int:
        buf = self._ring_buffers.get(project_id)
        return len(buf) if buf is not None else 0


# Module-level singleton. Tests patch this via
# ``broadcast._BROADCASTER = ProjectBroadcaster()`` for isolation.
_BROADCASTER: ProjectBroadcaster | None = None


def get_broadcaster() -> ProjectBroadcaster:
    """Return the process-wide broadcaster, creating it on first use."""
    global _BROADCASTER
    if _BROADCASTER is None:
        _BROADCASTER = ProjectBroadcaster()
    return _BROADCASTER


def reset_broadcaster_for_tests() -> None:
    """Reset the singleton between tests so state doesn't leak."""
    global _BROADCASTER
    _BROADCASTER = ProjectBroadcaster()


# ── Session-info offset stash ──────────────────────────────────────
#
# ``reducer.append_event`` appends to ``session.info['_broadcast_offsets']``
# after each successful flush. Write-route handlers then call
# :func:`commit_and_publish` instead of bare ``db.commit()``.


_STASH_KEY = "_broadcast_offsets"


def stash_offset(session: Session, offset: int) -> None:
    """Record a committed event offset on the session for later publish.

    Called from :func:`backend.graph.reducer.append_event` after
    the event row has been successfully flushed. The offset sits
    in the session until :func:`commit_and_publish` drains it.
    """
    offsets = session.info.setdefault(_STASH_KEY, [])
    offsets.append(offset)


def commit_and_publish(db: Session, project_id: str) -> None:
    """Drop-in replacement for ``db.commit()`` in write-route handlers.

    Commits the transaction, then publishes a broadcast message
    per stashed offset. Reads the event type + payload back from
    ``graph_events`` to build the message — cheap since we just
    wrote those rows.

    If the publish fan-out raises, it is logged and swallowed —
    broadcast failure must never undo a committed write.
    """
    offsets = list(db.info.get(_STASH_KEY, []))
    db.info[_STASH_KEY] = []
    db.commit()
    if not offsets:
        return
    try:
        rows = list(
            db.execute(
                select(GraphEvent).where(
                    GraphEvent.project_id == project_id,
                    GraphEvent.offset.in_(offsets),
                )
            ).scalars()
        )
        rows.sort(key=lambda r: r.offset)
        broadcaster = get_broadcaster()
        for row in rows:
            node_ids = _node_ids_for_event(row.event_type, row.payload or {})
            broadcaster.publish(
                project_id,
                BroadcastMessage(
                    offset=row.offset,
                    event_type=row.event_type,
                    node_ids=node_ids,
                ),
            )
    except Exception:
        logger.exception("broadcast: publish failed for project %s offsets %s", project_id, offsets)
