"""Unit tests for ``backend.projects.settings``.

Covers the :class:`ProjectSettings` defaults and the tolerance of
``get_project_settings`` for ``None`` / ``{}`` / unknown-key
settings blobs. Route-layer tests for the same model live in
``test_project_settings_routes.py``.
"""

from __future__ import annotations

from backend.projects.settings import (
    ProjectSettings,
    get_project_settings,
)


class _FakeProject:
    """Minimal stand-in that carries only the ``settings`` column."""

    def __init__(self, settings: object) -> None:
        self.settings = settings


class TestProjectSettingsDefaults:
    def test_default_timeout_unchanged(self) -> None:
        s = ProjectSettings()
        assert s.generation_timeout_seconds == 1800


class TestGetProjectSettings:
    def test_none_column_yields_defaults(self) -> None:
        s = get_project_settings(_FakeProject(None))
        assert s.generation_timeout_seconds == 1800

    def test_empty_dict_column_yields_defaults(self) -> None:
        s = get_project_settings(_FakeProject({}))
        assert s.generation_timeout_seconds == 1800

    def test_non_dict_column_falls_back_to_defaults(self) -> None:
        s = get_project_settings(_FakeProject("corrupt-string-somehow"))
        assert s.generation_timeout_seconds == 1800

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
