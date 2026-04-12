"""Generation telemetry — per-LLM-call token usage.

Every LLM call made by a pipeline handler appends a row here so the
frontend can surface token counts on every node/section the user
reviews. This is observability, not state — it is **not** written
through the event-sourced reducer, and replay of the event log does
**not** reconstruct it. Telemetry rows are born from handler
side-effects and live for the lifetime of the project row (cascade
on project delete).

See ``docs/architecture/v2-rearchitecture.md`` §Generation telemetry.

Schema shape matches the spec's stated key:
``(node_id, fragment_or_section, model, prompt_tokens,
completion_tokens, timestamp)``, with ``project_id`` added for
scoping and an index on ``(project_id, node_id, created_at)`` to
make the "latest telemetry for this node" query cheap.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base


class GenerationTelemetry(Base):
    __tablename__ = "generation_telemetry"
    __table_args__ = (
        Index(
            "ix_generation_telemetry_project_node_created",
            "project_id",
            "node_id",
            "created_at",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=lambda: f"tlm_{uuid.uuid4().hex[:16]}"
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Optional so that future callers generating content not yet
    # associated with a node (e.g. parse-retry scratch work) can still
    # record usage. MVP always sets it.
    node_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Identifies which part of the node was generated:
    # "expansion" for the whole expansion doc, "techspec"/"pubapi"/
    # "privapi"/"deps" for fragment regens, etc. Free-form string so
    # we don't have to migrate every time a new generation site
    # shows up.
    section: Mapped[str | None] = mapped_column(String(32), nullable=True)
    model: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
