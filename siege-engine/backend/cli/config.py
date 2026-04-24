"""Per-invocation CLI configuration bundle.

One typed dataclass carrying every knob the Claude CLI subprocess
cares about — timeout, budget, output-token cap, thinking effort.
Handlers build an instance from :class:`ProjectSettings` via
:meth:`ProjectSettings.to_cli_config` and thread it through the
parse-validate loop + review runner as a single kwarg. The CLI
manager reads fields off the config in ``_invoke`` and
``_build_subprocess_env``.

Adding a new CLI knob is a four-line change across the platform:

1. Add the field to :class:`backend.projects.settings.ProjectSettings`
   (bounds + docstring).
2. Add the same field to :class:`CliInvocationConfig`.
3. Map it in :meth:`ProjectSettings.to_cli_config`.
4. Read it in :mod:`backend.cli.manager` — either as a ``--flag``
   on the subprocess args or an env var on the per-call env dict.

Plus the usual frontend Zod + settings-page input for user-visible
knobs. No handler changes required.

Kept separate from ``ProjectSettings`` so the CLI manager can stay
agnostic of the per-project storage shape — e.g. a rename-rewrite
call that doesn't have a project context can still build a
``CliInvocationConfig`` by hand.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CliInvocationConfig:
    """Bundled CLI knobs for one ``cli_manager.generate*`` call.

    All fields are required so handlers can't silently forget a
    knob when they build one. ``thinking_effort`` is the one tier-
    specific override — callers set ``"max"`` on the first three
    tiers and leave it ``None`` elsewhere; see CLAUDE.md §Thinking
    effort per tier for the rationale.
    """

    timeout_seconds: int
    max_budget_usd: float
    max_output_tokens: int
    thinking_effort: str | None = None
