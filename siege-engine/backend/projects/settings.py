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

Call sites:

* ``get_project_settings(project)`` — read-side helper. Handles a
  ``None`` settings column, a ``{}`` settings column, and any
  unknown-key leftovers by falling back to defaults and dropping
  keys the current schema doesn't know about. Returns a fully
  validated :class:`ProjectSettings` instance.
* ``ProjectSettings.model_dump()`` when persisting — serializes
  back into the JSON column, excluding any transient fields.

The pydantic model is the *source of truth* for defaults. The
handler does not duplicate ``DEFAULT_TIMEOUT_SECONDS``: it calls
``get_project_settings(...)`` and reads
``.generation_timeout_seconds``.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from backend.models import Project


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
