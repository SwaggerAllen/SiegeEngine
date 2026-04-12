"""Pending-change queue + review view markers.

``PendingInstruction`` rows hold bulleted instructions produced by UI
actions or prose feedback that have not yet been executed. The queue
is sequential per project: ``backend.graph.queue.apply_pending_queue``
marks queued rows ``running`` and enqueues a single ``v2.apply_instructions``
Job, which a handler picks up serially.

``View`` rows are point-in-time markers in the graph event log. They
are created on the first time a user opens a review screen for a
batch; projections at the view's moment are reconstructable by
replaying events up to ``event_offset``.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base

PENDING_INSTRUCTION_STATUSES = ("queued", "running", "applied", "discarded", "failed")


class PendingInstruction(Base):
    __tablename__ = "pending_instructions"
    __table_args__ = (
        CheckConstraint(
            f"status IN {PENDING_INSTRUCTION_STATUSES}",
            name="ck_pending_instructions_status",
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    instruction_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="queued")
    job_id: Mapped[str | None] = mapped_column(
        ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class View(Base):
    __tablename__ = "views"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    batch_id: Mapped[str] = mapped_column(String(64), nullable=False)
    event_offset: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
