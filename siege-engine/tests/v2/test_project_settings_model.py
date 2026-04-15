"""Unit tests for ``backend.projects.settings``.

Covers the :class:`NodeCountRange` ordering invariant, the
:class:`ProjectSettings` defaults, and the tolerance of
``get_project_settings`` for ``None`` / ``{}`` / unknown-key
settings blobs. Route-layer tests for the same model live in
``test_project_settings_routes.py``.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.projects.settings import (
    NodeCountRange,
    ProjectSettings,
    get_project_settings,
)


class _FakeProject:
    """Minimal stand-in that carries only the ``settings`` column."""

    def __init__(self, settings: object) -> None:
        self.settings = settings


class TestNodeCountRange:
    def test_valid_ordered_range_parses(self) -> None:
        r = NodeCountRange(floor=3, typical_min=8, typical_max=20, ceiling=40)
        assert r.floor == 3
        assert r.typical_min == 8
        assert r.typical_max == 20
        assert r.ceiling == 40

    def test_all_four_equal_is_allowed(self) -> None:
        # floor == typical_min == typical_max == ceiling is a
        # degenerate but valid "exactly N" specification.
        r = NodeCountRange(floor=5, typical_min=5, typical_max=5, ceiling=5)
        assert r.ceiling == 5

    @pytest.mark.parametrize(
        "floor,tmin,tmax,ceiling",
        [
            (5, 3, 8, 15),  # floor > typical_min
            (3, 10, 8, 15),  # typical_min > typical_max
            (3, 5, 20, 15),  # typical_max > ceiling
            (15, 10, 8, 3),  # totally reversed
        ],
    )
    def test_out_of_order_is_rejected(self, floor: int, tmin: int, tmax: int, ceiling: int) -> None:
        with pytest.raises(ValidationError):
            NodeCountRange(
                floor=floor,
                typical_min=tmin,
                typical_max=tmax,
                ceiling=ceiling,
            )

    def test_zero_floor_is_rejected(self) -> None:
        # Every value must be a positive count; zero is a footgun
        # (a range of "produce zero of X" is never what the user
        # meant).
        with pytest.raises(ValidationError):
            NodeCountRange(floor=0, typical_min=1, typical_max=2, ceiling=3)

    def test_above_max_ceiling_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            NodeCountRange(floor=1, typical_min=2, typical_max=3, ceiling=9999)


class TestProjectSettingsDefaults:
    def test_default_timeout_unchanged(self) -> None:
        s = ProjectSettings()
        assert s.generation_timeout_seconds == 900

    def test_default_features_per_group(self) -> None:
        s = ProjectSettings()
        assert s.features_per_group.floor == 2
        assert s.features_per_group.typical_min == 3
        assert s.features_per_group.typical_max == 8
        assert s.features_per_group.ceiling == 15

    def test_default_top_level_responsibilities(self) -> None:
        s = ProjectSettings()
        assert s.top_level_responsibilities.floor == 3
        assert s.top_level_responsibilities.typical_min == 8
        assert s.top_level_responsibilities.typical_max == 20
        assert s.top_level_responsibilities.ceiling == 40

    def test_default_top_level_components(self) -> None:
        s = ProjectSettings()
        assert s.top_level_components.floor == 3
        assert s.top_level_components.typical_min == 5
        assert s.top_level_components.typical_max == 15
        assert s.top_level_components.ceiling == 25

    def test_default_subcomponents_per_component(self) -> None:
        s = ProjectSettings()
        assert s.subcomponents_per_component.floor == 1
        assert s.subcomponents_per_component.typical_min == 2
        assert s.subcomponents_per_component.typical_max == 8
        assert s.subcomponents_per_component.ceiling == 15

    def test_default_subresponsibilities_per_component(self) -> None:
        s = ProjectSettings()
        assert s.subresponsibilities_per_component.floor == 3
        assert s.subresponsibilities_per_component.typical_min == 4
        assert s.subresponsibilities_per_component.typical_max == 12
        assert s.subresponsibilities_per_component.ceiling == 30

    def test_defaults_are_independent_per_instance(self) -> None:
        # Regression: the default_factory uses model_copy so two
        # instances don't share the same sub-model reference. Mutate
        # one and confirm the other is untouched.
        a = ProjectSettings()
        b = ProjectSettings()
        assert a.features_per_group is not b.features_per_group

    def test_override_one_range_preserves_others(self) -> None:
        s = ProjectSettings.model_validate(
            {
                "features_per_group": {
                    "floor": 4,
                    "typical_min": 5,
                    "typical_max": 6,
                    "ceiling": 7,
                }
            }
        )
        assert s.features_per_group.floor == 4
        assert s.features_per_group.ceiling == 7
        # Untouched tiers keep their defaults.
        assert s.top_level_components.typical_max == 15

    def test_override_with_bad_ordering_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ProjectSettings.model_validate(
                {
                    "top_level_components": {
                        "floor": 10,
                        "typical_min": 5,
                        "typical_max": 15,
                        "ceiling": 25,
                    }
                }
            )


class TestGetProjectSettings:
    def test_none_column_yields_defaults(self) -> None:
        s = get_project_settings(_FakeProject(None))
        assert s.generation_timeout_seconds == 900
        assert s.top_level_components.typical_max == 15

    def test_empty_dict_column_yields_defaults(self) -> None:
        s = get_project_settings(_FakeProject({}))
        assert s.subresponsibilities_per_component.ceiling == 30

    def test_non_dict_column_falls_back_to_defaults(self) -> None:
        s = get_project_settings(_FakeProject("corrupt-string-somehow"))
        assert s.generation_timeout_seconds == 900
        assert s.features_per_group.floor == 2

    def test_unknown_keys_are_dropped(self) -> None:
        s = get_project_settings(
            _FakeProject(
                {
                    "generation_timeout_seconds": 600,
                    "some_legacy_field_we_no_longer_know": "ignore me",
                }
            )
        )
        assert s.generation_timeout_seconds == 600
        dumped = s.model_dump()
        assert "some_legacy_field_we_no_longer_know" not in dumped

    def test_partial_override_merges_with_defaults(self) -> None:
        s = get_project_settings(
            _FakeProject(
                {
                    "top_level_responsibilities": {
                        "floor": 5,
                        "typical_min": 10,
                        "typical_max": 25,
                        "ceiling": 50,
                    }
                }
            )
        )
        assert s.top_level_responsibilities.ceiling == 50
        # Timeout and other tiers still at defaults.
        assert s.generation_timeout_seconds == 900
        assert s.features_per_group.typical_max == 8
