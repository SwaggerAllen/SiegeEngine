"""Tests for the cohort stratified sampler.

Pure-function tests against the greedy max-coverage algorithm.
No DB required — feeds StructureSummary + CohortSamplerConfig
fixtures directly to ``suggest_cohort``.
"""

from __future__ import annotations

from backend.graph.cohort_sampler import suggest_cohort
from backend.graph.tier_structure import NodeRow, StructureSummary
from backend.models.cohort_sampler_config import CohortSamplerConfig


def _summary(rows: list[tuple[str, dict]]) -> StructureSummary:
    """Build a minimal StructureSummary from (id, metrics) pairs."""
    return StructureSummary(
        tier="comparch",
        tier_name="Comparch",
        per_node=tuple(NodeRow(id=cid, name=cid, metrics=metrics) for cid, metrics in rows),
        aggregate={},
    )


def _config(axes: list[dict]) -> CohortSamplerConfig:
    return CohortSamplerConfig(
        id="sampler_test",
        project_id="proj_test",
        tier="comparch",
        axes={"axes": axes},
    )


class TestSuggestCohortBasic:
    def test_zero_target_returns_empty(self):
        s = _summary([("a", {"kind": "domain"})])
        c = _config([{"key": "kind", "type": "categorical", "weight": 1.0}])
        assert suggest_cohort(s, c, target_size=0) == []

    def test_no_axes_falls_back_to_id_order(self):
        s = _summary([("c", {}), ("a", {}), ("b", {})])
        c = _config([])
        assert suggest_cohort(s, c, target_size=2) == ["a", "b"]

    def test_single_axis_picks_one_per_bucket_first(self):
        s = _summary(
            [
                ("a", {"kind": "domain"}),
                ("b", {"kind": "domain"}),
                ("c", {"kind": "presentational"}),
            ]
        )
        c = _config([{"key": "kind", "type": "categorical", "weight": 1.0}])
        # First pick: 'a' (alphabetical tie-break, both buckets uncovered
        # so any 1.0 score; 'a' wins). Second pick: 'c' (the only one
        # covering presentational). 'b' would only contribute already-
        # covered domain so it loses.
        result = suggest_cohort(s, c, target_size=2)
        assert set(result) == {"a", "c"}
        assert result == ["a", "c"]


class TestNumericBuckets:
    def test_numeric_buckets_assignment(self):
        s = _summary(
            [
                ("zero", {"sub_count": 0}),
                ("two", {"sub_count": 2}),
                ("four", {"sub_count": 4}),
                ("eight", {"sub_count": 8}),
            ]
        )
        c = _config(
            [
                {
                    "key": "sub_count",
                    "type": "numeric_buckets",
                    "weight": 1.0,
                    "buckets": [
                        {"label": "0", "max": 0},
                        {"label": "1-2", "min": 1, "max": 2},
                        {"label": "3-5", "min": 3, "max": 5},
                        {"label": "6+", "min": 6},
                    ],
                }
            ]
        )
        result = suggest_cohort(s, c, target_size=4)
        # All 4 different buckets covered.
        assert set(result) == {"zero", "two", "four", "eight"}

    def test_open_ended_bucket(self):
        s = _summary([("hi", {"x": 100}), ("lo", {"x": 1})])
        c = _config(
            [
                {
                    "key": "x",
                    "type": "numeric_buckets",
                    "weight": 1.0,
                    "buckets": [{"label": "any-pos", "min": 0}],
                }
            ]
        )
        result = suggest_cohort(s, c, target_size=2)
        assert set(result) == {"hi", "lo"}


class TestExcludeIds:
    def test_excluded_ids_skipped_in_pool(self):
        s = _summary(
            [
                ("a", {"kind": "domain"}),
                ("b", {"kind": "presentational"}),
                ("c", {"kind": "domain"}),
            ]
        )
        c = _config([{"key": "kind", "type": "categorical", "weight": 1.0}])
        result = suggest_cohort(s, c, target_size=2, exclude_ids=frozenset({"a", "b"}))
        assert result == ["c"]


class TestAxisWeighting:
    def test_higher_weight_axis_drives_first_pick(self):
        # Both candidates have a unique "kind"; "a" also has a unique
        # is_foundation. With kind weighted higher, the algorithm
        # picks 'a' (covers kind=domain) first, then 'b' (covers kind=
        # presentational AND is_foundation=True).
        s = _summary(
            [
                ("a", {"kind": "domain", "is_foundation": False}),
                ("b", {"kind": "presentational", "is_foundation": True}),
            ]
        )
        c = _config(
            [
                {"key": "kind", "type": "categorical", "weight": 1.0},
                {"key": "is_foundation", "type": "categorical", "weight": 0.3},
            ]
        )
        result = suggest_cohort(s, c, target_size=2)
        assert set(result) == {"a", "b"}


class TestDeterministicTieBreak:
    def test_alphabetical_tie_break(self):
        # All candidates score identically (all have the same single
        # bucket value). Tie-break by ID alphabetical.
        s = _summary([("zebra", {"k": "x"}), ("apple", {"k": "x"}), ("mango", {"k": "x"})])
        c = _config([{"key": "k", "type": "categorical", "weight": 1.0}])
        # First pick: alphabetical "apple". Second: "mango" (now both
        # remaining have score 0, alphabetical wins). Third: "zebra".
        assert suggest_cohort(s, c, target_size=3) == ["apple", "mango", "zebra"]


class TestTargetSizeCap:
    def test_target_size_larger_than_pool_returns_all(self):
        s = _summary([("a", {"k": "x"}), ("b", {"k": "y"})])
        c = _config([{"key": "k", "type": "categorical", "weight": 1.0}])
        result = suggest_cohort(s, c, target_size=10)
        assert set(result) == {"a", "b"}


class TestMissingMetric:
    def test_missing_metric_does_not_crash(self):
        s = _summary(
            [
                ("a", {"kind": "domain"}),
                ("b", {}),  # missing kind metric
            ]
        )
        c = _config([{"key": "kind", "type": "categorical", "weight": 1.0}])
        result = suggest_cohort(s, c, target_size=2)
        # 'a' wins on first pick (covers domain). 'b' contributes
        # nothing to kind axis (label=None) so falls through to fill.
        assert result == ["a", "b"]
