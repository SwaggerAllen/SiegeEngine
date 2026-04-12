"""Graph event log — append-only source of truth for the structured model.

Every write to the structured model is recorded as a row in this table.
Projection tables (nodes, edges, fragments, drafts) are derived views
that can be rebuilt from scratch by replaying the log in offset order.

Offsets are monotonic **per project**, assigned inside the append
transaction in ``backend.graph.reducer.append_event``.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base


class GraphEvent(Base):
    __tablename__ = "graph_events"
    __table_args__ = (
        UniqueConstraint("project_id", "offset", name="uq_graph_events_project_offset"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    offset: Mapped[int] = mapped_column(BigInteger, nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
