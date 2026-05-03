"""Job queue model for background task processing."""

import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    job_type: Mapped[str] = mapped_column(String(100), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    # queued|running|completed|failed|cancelled
    status: Mapped[str] = mapped_column(String(20), default="queued")
    priority: Mapped[int] = mapped_column(Integer, default=10)  # lower = higher priority
    max_retries: Mapped[int] = mapped_column(Integer, default=0)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    locked_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Phase F: True when this job completed via the deferred-retry
    # path (handler raised TierDeferredError). The wakeup hook keys
    # off this flag to find rows that should be re-enqueued when
    # their blocking dep settles. Replaces a fragile "deferred:"
    # prefix on error_message that was load-bearing string discrimination.
    is_deferred: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Phase 14 — universal batch tagging. Set to the ``Batch.id`` of
    # the operation that issued this job. ``None`` for legacy rows
    # from before the column landed and for system-side enqueues
    # (e.g. handler-internal cascade jobs that aren't user-issued
    # operations). Indexed so resume / scope-by-batch queries are
    # cheap.
    batch_id: Mapped[str | None] = mapped_column(
        ForeignKey("batches.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
