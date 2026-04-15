"""Cross-tier tests for ``render_system_prompt`` token substitution.

Every generation prompt that cites a count range now pulls the
four numbers (``floor``, ``typical_min``, ``typical_max``,
``ceiling``) from a :class:`NodeCountRange` at render time via
``render_system_prompt``. This module verifies token substitution
for the tiers not already covered by their own prompt test file:

* sysarch — top-level component count
* subrequirements — subresponsibilities per component
* comparch — subcomponents per component

(``requirements`` is covered in ``test_prompts_requirements.py``
and ``feature_expansion`` in ``test_prompts.py``.)
"""

from __future__ import annotations

from backend.graph.prompts.comparch import render_system_prompt as render_comparch
from backend.graph.prompts.subrequirements import (
    render_system_prompt as render_subreqs,
)
from backend.graph.prompts.sysarch import render_system_prompt as render_sysarch
from backend.projects.settings import NodeCountRange, ProjectSettings

_DISTINCTIVE = NodeCountRange(floor=7, typical_min=11, typical_max=13, ceiling=17)
_PLACEHOLDER_TOKENS = ("{{FLOOR}}", "{{TYPICAL_MIN}}", "{{TYPICAL_MAX}}", "{{CEILING}}")


class TestSysarchSystemPrompt:
    def test_substitutes_default_numbers(self) -> None:
        # Defaults are 3 / 5 / 15 / 25.
        out = render_sysarch(ProjectSettings().top_level_components)
        assert "5 to 15 for a normal" in out
        assert "3 or fewer" in out
        assert "25 or more" in out

    def test_substitutes_custom_numbers(self) -> None:
        out = render_sysarch(_DISTINCTIVE)
        assert "11 to 13 for a normal" in out
        assert "7 or fewer" in out
        assert "17 or more" in out
        # Make sure the defaults don't leak through — catches the
        # "handler forgot to call the renderer" case.
        assert "5 to 15 for a normal" not in out

    def test_no_raw_placeholder_tokens_leak(self) -> None:
        out = render_sysarch(ProjectSettings().top_level_components)
        for token in _PLACEHOLDER_TOKENS:
            assert token not in out


class TestSubrequirementsSystemPrompt:
    def test_substitutes_default_numbers(self) -> None:
        # Defaults are 3 / 4 / 12 / 30.
        out = render_subreqs(ProjectSettings().subresponsibilities_per_component)
        assert "4 to 12 subresponsibilities" in out
        assert "3 or fewer" in out
        assert "30 or more" in out

    def test_substitutes_custom_numbers(self) -> None:
        out = render_subreqs(_DISTINCTIVE)
        assert "11 to 13 subresponsibilities" in out
        assert "7 or fewer" in out
        assert "17 or more" in out
        assert "4 to 12 subresponsibilities" not in out

    def test_no_raw_placeholder_tokens_leak(self) -> None:
        out = render_subreqs(ProjectSettings().subresponsibilities_per_component)
        for token in _PLACEHOLDER_TOKENS:
            assert token not in out


class TestComparchSystemPrompt:
    def test_substitutes_default_numbers(self) -> None:
        # Defaults are 1 / 2 / 8 / 15.
        out = render_comparch(ProjectSettings().subcomponents_per_component)
        assert "typically 2 to 8 per component" in out
        assert "1 or fewer subcomponents" in out
        assert "15 or more" in out

    def test_substitutes_custom_numbers(self) -> None:
        out = render_comparch(_DISTINCTIVE)
        assert "typically 11 to 13 per component" in out
        assert "7 or fewer subcomponents" in out
        assert "17 or more" in out
        assert "typically 2 to 8" not in out

    def test_no_raw_placeholder_tokens_leak(self) -> None:
        out = render_comparch(ProjectSettings().subcomponents_per_component)
        for token in _PLACEHOLDER_TOKENS:
            assert token not in out
