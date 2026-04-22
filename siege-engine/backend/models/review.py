"""Phase 12 review-batch tables.

Both tables back the batched-review walker:

* :class:`ReviewBatch` — one row per open review session. Pins
  ``GraphEvent.offset`` at open time so concurrent writes don't
  shift the stale-node set out from under the user mid-walk.
* :class:`ProjectionSnapshot` — cached point-in-time projection
  dumps, keyed by ``(project_id, offset)``. Pure optimization on
  the log-walk path the walker uses to reconstruct fragment
  content at ``pinned_offset`` for diffing.

Neither table is derived from the event log; both are primary
state managed by the review routes. ``rebuild_projections`` does
not wipe them.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base


class ReviewBatch(Base):
    __tablename__ = "review_batches"
    __table_args__ = (Index("ix_review_batches_project", "project_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    pinned_offset: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ProjectionSnapshot(Base):
    __tablename__ = "projection_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "offset",
            name="uq_projection_snapshots_project_offset",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    offset: Mapped[int] = mapped_column(BigInteger, nullable=False)
    payload_blob: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
