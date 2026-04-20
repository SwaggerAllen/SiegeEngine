"""Read-side helpers for the Phase 9 staleness ledger.

Centralizes the bulk lookup that the ``/structure`` route and the
per-tier bootstrap routes both need: "for this project, which nodes
are stale and why". Mirrors the pattern in :mod:`backend.graph.running`
for generation-job state — one module, one query, both routes call
it so the badge computation stays in one place.

See ``docs/architecture/v2-roadmap.md`` Phase 9 for the surrounding
fanout / auto-enqueue design. This file is read-only; writes to the
ledger happen exclusively in
:func:`backend.graph.fanout.apply_staleness_changes`.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models.node import StalenessLedger


def stale_node_reasons(db: Session, project_id: str) -> dict[str, list[str]]:
    """Return ``{stale_node_id: [reason, ...]}`` for every stale node.

    One query over the ledger. Reasons are de-duplicated and stable-
    ordered so the frontend's structural-comparison of the structure
    response doesn't flap on re-fetches. A node missing from the
    returned dict is not stale; callers should default to
    ``reasons = []`` + ``is_stale = False``.

    Different upstreams may independently mark the same dependent
    stale with different reasons; the ``(project, stale, source,
    reason)`` unique constraint keeps the raw row count bounded by
    ``|inbound edges| × |reason vocabulary|`` per node, so the
    python-side dedupe is cheap.
    """
    rows = (
        db.execute(
            select(
                StalenessLedger.stale_node_id,
                StalenessLedger.reason,
            )
            .where(StalenessLedger.project_id == project_id)
            .order_by(StalenessLedger.stale_node_id.asc(), StalenessLedger.reason.asc())
        )
    ).all()

    out: dict[str, list[str]] = {}
    for stale_id, reason in rows:
        bucket = out.setdefault(stale_id, [])
        if reason not in bucket:
            bucket.append(reason)
    return out
