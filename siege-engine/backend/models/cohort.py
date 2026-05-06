"""Cohort model — a saved selection of comp IDs to iterate against.

Phase 14 follow-up. A cohort is the user's "canonical sample" of
parent comps to drive a generation campaign at the next tier down.
The campaign workflow:

1. Open the per-tier structure-summary, browse the distribution.
2. Stratified-sample (or hand-pick) ~6-8 comps spanning variation
   axes (kind, foundation, sub count, dep count, multi-owner).
3. Save as a cohort.
4. Each iteration cycle: regenerate the cohort comps' children at
   the target tier (typically subcomparch) under one batch, A/B
   prompt changes against this fixed baseline.

``tier`` is the tier we select FROM (e.g. ``"comparch"``); the
target tier (the one we generate AT during regenerate) is implicit
— for a comparch cohort the target is subcomparch, the only
meaningful child tier. Future cohorts at other tiers extend this
naturally.

``comp_ids`` is the list of parent ``comp_*`` IDs. Subs are
derived per-cycle by walking each comp's children, so adding a
new sub to a cohort comp later automatically picks it up.

``version`` increments when a cohort is archived and replaced
with a new selection — supports "cohort v1 vs v2 score deltas" in
the campaign retrospective.
"""

from __future__ import annotations

import secrets
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base


def mint_cohort_id() -> str:
    return f"cohort_{secrets.token_hex(8)}"


class Cohort(Base):
    __tablename__ = "cohorts"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=mint_cohort_id)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tier: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False, default="canonical")
    comp_ids: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    # Experimental supplementary comps managed by Fresh cycles. Set
    # (replaced) on each fresh-mode cohort_regenerate; iterated by
    # subsequent review-mode regens until the next fresh swaps in a
    # new random sample. Distinct from ``comp_ids`` (the canonical
    # set) so the structure-summary "Save as cohort" flow doesn't
    # collide with campaign-loop exploration management.
    experimental_comp_ids: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )
