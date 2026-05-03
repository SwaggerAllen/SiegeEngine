"""Sampler configuration for cohort auto-suggest.

One row per (project_id, tier). Holds the axes the stratified
sampler stratifies along + per-axis weights + bucket definitions.
Configurable via API so the user can tune axis priorities or add
new axes without a backend deploy interrupting in-flight
generations.

``axes`` JSON shape::

    {
      "axes": [
        {"key": "kind", "label": "Kind", "weight": 1.0,
         "type": "categorical"},
        {"key": "is_foundation", "label": "Foundation",
         "weight": 0.7, "type": "categorical"},
        {"key": "sub_count", "label": "Sub count", "weight": 0.8,
         "type": "numeric_buckets",
         "buckets": [
           {"label": "0", "max": 0},
           {"label": "1-2", "min": 1, "max": 2},
           {"label": "3-5", "min": 3, "max": 5},
           {"label": "6+", "min": 6}
         ]},
        ...
      ]
    }

The sampler reads this against the per-tier
:class:`backend.graph.tier_structure.StructureSummary.per_node`
metrics. ``key`` matches a metric key; ``type`` chooses the
bucket-derivation strategy:

- ``categorical`` — one bucket per distinct value the metric
  takes across the corpus (computed lazily from the corpus, no
  ``buckets`` list needed in the config).
- ``numeric_buckets`` — bucket the metric value against the
  ``buckets`` list's ``min``/``max`` ranges (both inclusive,
  either bound can be omitted for open-ended).
"""

from __future__ import annotations

import secrets
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base


def mint_cohort_sampler_config_id() -> str:
    return f"sampler_{secrets.token_hex(8)}"


class CohortSamplerConfig(Base):
    __tablename__ = "cohort_sampler_configs"
    __table_args__ = (
        UniqueConstraint("project_id", "tier", name="uq_cohort_sampler_configs_project_tier"),
    )

    id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=mint_cohort_sampler_config_id
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tier: Mapped[str] = mapped_column(String(32), nullable=False)
    axes: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )


# Default axis configurations seeded on first GET if no row exists
# for a (project, tier). Tuned for the comparch tier as our
# initial use case; other tiers will get their own defaults as
# they grow campaign workflows.
DEFAULT_AXES_BY_TIER: dict[str, dict[str, Any]] = {
    "comparch": {
        "axes": [
            {"key": "kind", "label": "Kind", "weight": 1.0, "type": "categorical"},
            {
                "key": "is_foundation",
                "label": "Foundation",
                "weight": 0.7,
                "type": "categorical",
            },
            {
                "key": "sub_count",
                "label": "Sub count",
                "weight": 0.8,
                "type": "numeric_buckets",
                "buckets": [
                    {"label": "0", "max": 0},
                    {"label": "1-2", "min": 1, "max": 2},
                    {"label": "3-5", "min": 3, "max": 5},
                    {"label": "6+", "min": 6},
                ],
            },
            {
                "key": "dep_count",
                "label": "Dep count",
                "weight": 0.6,
                "type": "numeric_buckets",
                "buckets": [
                    {"label": "0", "max": 0},
                    {"label": "1-2", "min": 1, "max": 2},
                    {"label": "3+", "min": 3},
                ],
            },
            {
                "key": "multi_owner_resp_count",
                "label": "Multi-owner",
                "weight": 0.5,
                "type": "numeric_buckets",
                "buckets": [
                    {"label": "none", "max": 0},
                    {"label": "any", "min": 1},
                ],
            },
        ]
    },
}


def default_axes_for_tier(tier: str) -> dict[str, Any]:
    """Return the seeded default axis config for a tier.

    Falls back to an empty axes list for tiers without a baked-in
    default — the user will see "no axes configured" in the UI and
    can add some manually.
    """
    return DEFAULT_AXES_BY_TIER.get(tier, {"axes": []})
