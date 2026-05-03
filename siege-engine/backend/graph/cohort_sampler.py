"""Stratified greedy sampler for cohort selection.

Given a per-tier :class:`backend.graph.tier_structure.StructureSummary`
and a :class:`backend.models.cohort_sampler_config.CohortSamplerConfig`,
:func:`suggest_cohort` picks ``target_size`` comp IDs that maximise
coverage across the configured axes.

Algorithm — greedy, deterministic:

1. Compute the full bucket set for each axis (categorical: every
   distinct value seen in the corpus; numeric_buckets: the configured
   bucket list).
2. Initialise the "covered buckets" set to empty.
3. While we have candidates and haven't hit ``target_size``:
   a. For each remaining candidate, compute its score = sum across
      axes of (axis.weight × number-of-its-buckets-currently-uncovered).
   b. Pick the highest-scoring candidate; tie-break by the candidate's
      ID alphabetically (deterministic).
   c. Add the picked candidate's buckets to "covered".
4. When all axes are fully covered, the remaining slots are filled by
   continuing the same greedy pass — score becomes 0 for every
   candidate so tie-break (ID alphabetical) takes over, which is fine
   for pure-fill behaviour.

The exclusion set ``exclude_ids`` is applied at step 1 — used by the
exploration-sample endpoint to skip comps already sampled in prior
exploration batches.
"""

from __future__ import annotations

from typing import Any

from backend.graph.tier_structure import NodeRow, StructureSummary
from backend.models.cohort_sampler_config import CohortSamplerConfig


def suggest_cohort(
    structure_summary: StructureSummary,
    config: CohortSamplerConfig,
    target_size: int,
    exclude_ids: frozenset[str] = frozenset(),
) -> list[str]:
    """Return a list of comp IDs covering as many axis buckets as possible.

    See module docstring for the algorithm. ``target_size`` is a soft
    cap — the function returns up to that many candidates; if the
    candidate pool (after exclusion) is smaller, returns what's
    available.
    """
    if target_size <= 0:
        return []
    candidates = [n for n in structure_summary.per_node if n.id not in exclude_ids]
    if not candidates:
        return []

    axes_cfg = (config.axes or {}).get("axes") or []
    if not axes_cfg:
        # No axes configured — degenerate to deterministic ID-order
        # fill so the sampler is still usable (the user just won't get
        # axis-coverage benefits until they add axes).
        return [n.id for n in sorted(candidates, key=lambda r: r.id)[:target_size]]

    # Pre-compute each candidate's bucket assignment per axis.
    # ``buckets_by_candidate[id][axis_idx] = bucket_label`` (or None
    # if the metric is missing on this candidate — those candidates
    # don't contribute to that axis but still get scored on the
    # others).
    bucket_universe: list[set[str]] = []
    candidate_buckets: dict[str, list[str | None]] = {}
    for axis in axes_cfg:
        bucket_universe.append(set())
    for cand in candidates:
        per_axis: list[str | None] = []
        for axis_idx, axis in enumerate(axes_cfg):
            label = _bucket_for_metric(cand, axis)
            per_axis.append(label)
            if label is not None:
                bucket_universe[axis_idx].add(label)
        candidate_buckets[cand.id] = per_axis

    covered: list[set[str]] = [set() for _ in axes_cfg]
    remaining: dict[str, NodeRow] = {c.id: c for c in candidates}
    chosen: list[str] = []

    while remaining and len(chosen) < target_size:
        best_id: str | None = None
        best_score = -1.0
        # Sort by ID for deterministic tie-break (alphabetical).
        for cand_id in sorted(remaining):
            score = _score_candidate(
                candidate_buckets[cand_id],
                axes_cfg,
                covered,
            )
            if score > best_score:
                best_score = score
                best_id = cand_id
        if best_id is None:
            break
        chosen.append(best_id)
        # Mark this candidate's buckets as covered so subsequent
        # picks prefer different ones.
        for axis_idx, label in enumerate(candidate_buckets[best_id]):
            if label is not None:
                covered[axis_idx].add(label)
        del remaining[best_id]

    return chosen


def _score_candidate(
    candidate_axes: list[str | None],
    axes_cfg: list[dict[str, Any]],
    covered: list[set[str]],
) -> float:
    score = 0.0
    for axis_idx, axis in enumerate(axes_cfg):
        weight = float(axis.get("weight", 1.0))
        label = candidate_axes[axis_idx]
        if label is not None and label not in covered[axis_idx]:
            score += weight
    return score


def _bucket_for_metric(node: NodeRow, axis: dict[str, Any]) -> str | None:
    """Return the bucket label this node falls in for ``axis``, or None."""
    metric_key = axis.get("key")
    if not metric_key:
        return None
    value = node.metrics.get(metric_key)
    if value is None:
        return None
    axis_type = axis.get("type", "categorical")
    if axis_type == "categorical":
        # Stringify so booleans / mixed types collapse to a comparable
        # bucket label.
        return str(value)
    if axis_type == "numeric_buckets":
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return None
        for bucket in axis.get("buckets") or []:
            lo = bucket.get("min")
            hi = bucket.get("max")
            if lo is not None and numeric < float(lo):
                continue
            if hi is not None and numeric > float(hi):
                continue
            label = bucket.get("label")
            if isinstance(label, str):
                return label
            return f"{lo if lo is not None else '-inf'}..{hi if hi is not None else '+inf'}"
        return None
    return None
