"""Typed view over the per-project ``settings`` JSON column.

The column is intentionally open (a dict on the Project row) so we
can land new preferences without a migration each time, but every
*reader* goes through :class:`ProjectSettings` so defaults and
bounds are enforced in one place.

CLI-related settings (timeout, budget, max output tokens,
thinking effort) are bundled by :meth:`ProjectSettings.to_cli_config`
into a :class:`backend.cli.config.CliInvocationConfig` that handlers
thread through the generation chain as a single kwarg. Adding a new
CLI knob is a four-step change: field here, field on
``CliInvocationConfig``, mapping in ``to_cli_config``, read in
``backend.cli.manager``. No handler edits required.

Current settings:

* ``generation_timeout_seconds`` — how long handlers wait on a
  single Claude CLI subprocess before killing it and surfacing a
  timeout error. Default 7200 (2 hours). Minimum 60 (1 minute)
  and maximum 14400 (4 hours) — the top three tiers (expansion,
  reqs, sysarch) pass ``thinking_effort="max"`` and deep-thinking
  Opus runs can push past an hour on a real-sized project; the
  4h ceiling still catches a typo before it hangs a worker for
  a whole day.
* ``cli_max_output_tokens`` — cap on output tokens for a single
  Claude CLI subprocess. Forwarded as the
  ``CLAUDE_CODE_MAX_OUTPUT_TOKENS`` env var on the per-call env
  dict (never on the parent process, so concurrent handlers
  don't race). Default 128000 — double the CLI's intrinsic 64k
  default so sysarch / reqs / subcomparch runs on real-sized
  projects don't truncate mid-atom. Minimum 1000 (avoid
  starvation); maximum 400000 (well past any current model's
  output window — the ceiling exists to catch a typo, not to
  bound a real capability limit).
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

from backend.cli.config import CliInvocationConfig
from backend.models import Project


class ProjectSettings(BaseModel):
    """Per-project preferences, validated + defaulted.

    Every setting has a hardcoded default here; the DB column only
    carries *overrides*. Missing keys fall back to the default, so
    old projects with no settings dict behave identically to new
    projects with the defaults persisted explicitly.
    """

    generation_timeout_seconds: int = Field(
        default=7200,
        ge=60,
        le=14400,
        description=(
            "How long to wait on a single Claude CLI subprocess before "
            "killing it. 60s floor so you can't accidentally starve "
            "real work; 14400s (4h) ceiling because max-effort "
            "sysarch / reqs runs on Opus can push past an hour on a "
            "real-sized project, while still catching a typo before "
            "it hangs a worker for a whole day."
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
    cli_max_output_tokens: int = Field(
        default=128000,
        ge=1000,
        le=400000,
        description=(
            "Cap on output tokens for a single Claude CLI subprocess. "
            "Forwarded as the CLAUDE_CODE_MAX_OUTPUT_TOKENS env var on "
            "the per-call env dict. 128000 default — double the CLI's "
            "intrinsic 64k so sysarch / reqs / subcomparch runs on "
            "real-sized projects don't truncate mid-atom. 1000 floor "
            "avoids starvation; 400000 ceiling catches typos."
        ),
    )

    model_config = {
        "extra": "ignore",  # drop unknown keys from old settings blobs
    }

    def to_cli_config(self, *, thinking_effort: str | None = None) -> CliInvocationConfig:
        """Bundle the CLI-relevant fields into a per-invocation config.

        ``thinking_effort`` is the one tier-specific override —
        callers pass ``"max"`` on the first three tiers (expansion,
        reqs, sysarch) and leave it ``None`` on propagation tiers.
        Every other CLI knob comes from the project settings row.
        """
        return CliInvocationConfig(
            timeout_seconds=self.generation_timeout_seconds,
            max_budget_usd=self.cli_max_budget_usd,
            max_output_tokens=self.cli_max_output_tokens,
            thinking_effort=thinking_effort,
        )


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
