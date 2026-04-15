"""Typed view over the per-project ``settings`` JSON column.

The column is intentionally open (a dict on the Project row) so we
can land new preferences without a migration each time, but every
*reader* goes through :class:`ProjectSettings` so defaults and
bounds are enforced in one place.

Current settings:

* ``generation_timeout_seconds`` — how long handlers wait on a
  single Claude CLI subprocess before killing it and surfacing a
  timeout error. Default 900 (15 minutes). Minimum 60 (1 minute)
  and maximum 3600 (1 hour) to keep obvious footguns out.
* Five :class:`NodeCountRange` fields — ``features_per_group``,
  ``top_level_responsibilities``, ``top_level_components``,
  ``subcomponents_per_component``,
  ``subresponsibilities_per_component``. These configure the four
  load-bearing numbers (``floor``, ``typical_min``, ``typical_max``,
  ``ceiling``) that each generation prompt cites when nudging the
  LLM toward the "right" level of decomposition for a project. The
  prompt templates substitute these at render time via
  ``render_system_prompt`` in each ``backend.graph.prompts`` module.

Call sites:

* ``get_project_settings(project)`` — read-side helper. Handles a
  ``None`` settings column, a ``{}`` settings column, and any
  unknown-key leftovers by falling back to defaults and dropping
  keys the current schema doesn't know about. Returns a fully
  validated :class:`ProjectSettings` instance.
* ``ProjectSettings.model_dump()`` when persisting — serializes
  back into the JSON column, excluding any transient fields.

The pydantic model is the *source of truth* for defaults. Handlers
do not duplicate default constants: they call
``get_project_settings(...)`` and read the relevant field.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

from backend.models import Project


class NodeCountRange(BaseModel):
    """Four-number band describing how many children a tier should emit.

    Each prompt that guides decomposition (feature grouping,
    top-level responsibilities, top-level components, subcomponents
    per component, subresponsibilities per component) cites four
    numbers: a typical minimum, a typical maximum, a floor below
    which the LLM is told it's under-decomposing, and a ceiling
    above which it's told it's reaching into implementation detail.

    Invariant: ``floor <= typical_min <= typical_max <= ceiling``.
    The typical range is the band the LLM is nudged toward; floor
    and ceiling are the hard warnings. All four must be positive
    integers.
    """

    floor: int = Field(ge=1, le=1000)
    typical_min: int = Field(ge=1, le=1000)
    typical_max: int = Field(ge=1, le=1000)
    ceiling: int = Field(ge=1, le=1000)

    @model_validator(mode="after")
    def _check_ordering(self) -> "NodeCountRange":
        if not (self.floor <= self.typical_min <= self.typical_max <= self.ceiling):
            raise ValueError(
                "NodeCountRange requires "
                "floor <= typical_min <= typical_max <= ceiling; got "
                f"floor={self.floor}, typical_min={self.typical_min}, "
                f"typical_max={self.typical_max}, ceiling={self.ceiling}"
            )
        return self


# Defaults chosen to match the numbers currently hardcoded into the
# prompt templates where possible, and to add sensible bounds where
# the existing prompt only carried a typical range.
_DEFAULT_FEATURES_PER_GROUP = NodeCountRange(floor=2, typical_min=3, typical_max=8, ceiling=15)
_DEFAULT_TOP_LEVEL_RESPONSIBILITIES = NodeCountRange(
    floor=3, typical_min=8, typical_max=20, ceiling=40
)
_DEFAULT_TOP_LEVEL_COMPONENTS = NodeCountRange(floor=3, typical_min=5, typical_max=15, ceiling=25)
_DEFAULT_SUBCOMPONENTS_PER_COMPONENT = NodeCountRange(
    floor=1, typical_min=2, typical_max=8, ceiling=15
)
_DEFAULT_SUBRESPONSIBILITIES_PER_COMPONENT = NodeCountRange(
    floor=3, typical_min=4, typical_max=12, ceiling=30
)


class ProjectSettings(BaseModel):
    """Per-project preferences, validated + defaulted.

    Every setting has a hardcoded default here; the DB column only
    carries *overrides*. Missing keys fall back to the default, so
    old projects with no settings dict behave identically to new
    projects with the defaults persisted explicitly.
    """

    generation_timeout_seconds: int = Field(
        default=900,
        ge=60,
        le=3600,
        description=(
            "How long to wait on a single Claude CLI subprocess before "
            "killing it. 60s floor so you can't accidentally starve "
            "real work; 3600s ceiling so a typo doesn't hang a "
            "worker for a whole day."
        ),
    )

    features_per_group: NodeCountRange = Field(
        default_factory=lambda: _DEFAULT_FEATURES_PER_GROUP.model_copy(),
        description=(
            "How many features should sit inside a named <group> in "
            "the feature-expansion pass. Below the floor, groups "
            "should be inlined; above the ceiling, groups should "
            "split into sub-themes."
        ),
    )
    top_level_responsibilities: NodeCountRange = Field(
        default_factory=lambda: _DEFAULT_TOP_LEVEL_RESPONSIBILITIES.model_copy(),
        description=(
            "How many top-level responsibilities the requirements "
            "pass should produce. Below the floor, decomposition is "
            "too coarse; above the ceiling, the LLM is reaching into "
            "implementation territory."
        ),
    )
    top_level_components: NodeCountRange = Field(
        default_factory=lambda: _DEFAULT_TOP_LEVEL_COMPONENTS.model_copy(),
        description=(
            "How many top-level components (excluding the "
            "foundation) the sysarch pass should produce. Below the "
            "floor, decomposition is too coarse; above the ceiling, "
            "components are too fine and belong in Phase 4 arch docs."
        ),
    )
    subcomponents_per_component: NodeCountRange = Field(
        default_factory=lambda: _DEFAULT_SUBCOMPONENTS_PER_COMPONENT.model_copy(),
        description=(
            "How many subcomponents (including the foundation) "
            "comparch should produce per top-level component. Below "
            "the floor, un-fanned-out is cleaner; above the ceiling, "
            "the LLM is reaching into implementation detail."
        ),
    )
    subresponsibilities_per_component: NodeCountRange = Field(
        default_factory=lambda: _DEFAULT_SUBRESPONSIBILITIES_PER_COMPONENT.model_copy(),
        description=(
            "How many subresponsibilities the subrequirements pass "
            "should produce per component. Below the floor, not "
            "decomposing enough; above the ceiling, reaching into "
            "implementation detail."
        ),
    )

    model_config = {
        "extra": "ignore",  # drop unknown keys from old settings blobs
    }


def get_project_settings(project: Project) -> ProjectSettings:
    """Return the validated settings view for a project.

    Tolerates a ``None`` ``settings`` column, a ``{}`` settings
    column, and any extra or malformed keys by falling back to
    defaults. Raises :class:`pydantic.ValidationError` only when
    an explicit override is out of range — which is a programming
    error, not a user error, because the PUT route also validates.
    """
    raw = project.settings or {}
    if not isinstance(raw, dict):
        # Defensive: someone wrote a non-dict into the column.
        # Treat it as "no overrides" rather than crash a generation.
        raw = {}
    return ProjectSettings.model_validate(raw)
