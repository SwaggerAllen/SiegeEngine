"""Batch model — the universal "this group of work was issued together" row.

Every multi-job operation (a tier-op like Reset All) and every per-
node operation (bootstrap_reset, bootstrap_feedback, etc.) mints
one ``Batch`` row at the top of the route. The minted batch_id
threads through:

- Every job the operation enqueues (``Job.batch_id``).
- Every draft those jobs commit (``Draft.batch_id`` — extending the
  existing per-draft column's semantics so multi-draft tier-ops
  share one batch_id).

This makes "what was issued together?" universally queryable:
- Resume operation reads ``Job.batch_id`` to find the operation's
  jobs that didn't complete (only re-enqueues the gaps; never
  throws out completed work).
- Review-summary scoping reads ``Draft.batch_id`` to filter the
  per-tier review aggregation to drafts produced in this batch.

Distinct from :class:`ReviewBatch` (the older human-curated
review-session concept in :mod:`backend.models.review`) — that one
governs an interactive multi-node review workflow; this one
records every issued operation, including single-node ones.
"""

from __future__ import annotations

import secrets
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base


def mint_batch_id() -> str:
    """Generate a fresh batch identifier with a stable prefix."""
    return f"batch_{secrets.token_hex(8)}"


class Batch(Base):
    """One row per issued operation.

    ``op_type`` values currently in use:
    - ``reset_tier`` — tier-ops Reset All
    - ``review_sweep_tier`` — tier-ops Regen From Reviews
    - ``resume_tier`` — tier-ops Resume Tier (mints a fresh batch)
    - ``resume_batch`` — Resume the missing pieces of an earlier
      batch (does NOT mint; stamps the prior batch_id)
    - ``single_node_reset`` — per-node Reset / Reset & Regen button
    - ``single_node_feedback`` — per-node Reject & Regen button
    - ``single_node_approve`` — per-node Approve button
    - ``single_node_retry_review`` — per-node Retry review button

    ``tier`` is set for tier-ops and tier-targeted single-node
    actions; ``None`` for ops that don't have a tier scope. ``params``
    carries op-specific extra fields (e.g. ``force=True`` flag for
    Reset All).
    """

    __tablename__ = "batches"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=mint_batch_id)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    op_type: Mapped[str] = mapped_column(String(64), nullable=False)
    tier: Mapped[str | None] = mapped_column(String(32), nullable=True)
    scope_keys: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    params: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    initiator_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    # ``running`` is the lifecycle default; transitions to ``completed``
    # / ``partial`` / ``cancelled`` via batch-status helpers (Phase 2
    # follow-up). For now status stays ``running`` and consumers
    # derive completion from job statuses; the column is here so the
    # follow-up work doesn't need a second migration.
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="running")
