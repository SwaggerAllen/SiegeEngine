"""Typed view over the per-project ``settings`` JSON column.

The column is intentionally open (a dict on the Project row) so we
can land new preferences without a migration each time, but every
*reader* goes through :class:`ProjectSettings` so defaults and
bounds are enforced in one place.

Current settings:

* ``generation_timeout_seconds`` — how long handlers wait on a
  single Claude CLI subprocess before killing it and surfacing a
  timeout error. Default 1800 (30 minutes). Minimum 60 (1 minute)
  and maximum 3600 (1 hour) to keep obvious footguns out.
* ``cli_max_budget_usd`` — maximum dollar budget passed to the
  Claude CLI's ``--max-budget-usd`` flag for a single generation
  attempt. Default 2.00. Each parse-validate retry is a fresh
  call with a fresh budget. Bumping this lets bigger decomposition
  tasks finish thinking without blowing the budget mid-response;
  lowering it caps runaway cost at the expense of possibly
  cutting off long reasoning chains. Minimum 0.10 and maximum
  20.00. Budget-exceeded failures are non-retryable (see
  :class:`backend.cli.manager.CliBudgetExceededError`).

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
        default=1800,
        ge=60,
        le=3600,
        description=(
            "How long to wait on a single Claude CLI subprocess before "
            "killing it. 60s floor so you can't accidentally starve "
            "real work; 3600s ceiling so a typo doesn't hang a "
            "worker for a whole day."
        ),
    )
    cli_max_budget_usd: float = Field(
        default=2.00,
        ge=0.10,
        le=20.00,
        description=(
            "Maximum dollar budget per Claude CLI invocation. Passed "
            "as --max-budget-usd. Each parse-validate retry is a "
            "fresh call with a fresh budget. 0.10 floor catches "
            "accidental zeros; 20.00 ceiling keeps a typo from "
            "burning a whole card in one generation."
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
