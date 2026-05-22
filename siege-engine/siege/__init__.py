"""siege — the SiegeEngine core: read projection + writer CLI.

The package supersedes the old SQLAlchemy backend. State lives in git
(`state/<tier>/<id>.json` + `<tier>/<id>/body.md`). The deterministic
logic — both the read-side projection and the write-side
materialization — runs locally via the `siege.cli` command that Claude
Code skills shell out to; a thin HTTP server exposes the read half to
the dashboard. One git commit per state transition.

Module layout:

- ``config`` — environment-driven settings (mirrors backend's
  ``SIEGE_`` prefix where useful).
- ``auth`` — simplified JWT verification ported from
  ``backend/auth/service.py`` (the dashboard read API uses it).
- ``state`` — typed dataclasses for state JSON + load/save helpers.
- ``git_view`` — ``GitView`` substrate: an in-memory snapshot of every
  state JSON at a (ref, head_sha), with lazy-loaded bodies.
- ``fragments`` — fragment kinds + per-section body extraction (the
  git-backed replacement for the old Fragment table).
- ``parsers`` — body section parser, review XML parser.
- ``projection`` — per-tier generation- and review-context builders.
- ``manifest`` — the node identity ledger (derive / parse / write).
- ``validate`` — pre-commit validation gate.
- ``cli`` — the writer + reader CLI skills invoke.
- ``tools`` — the read-projection functions the dashboard server wraps.
- ``server`` — the dashboard's HTTP read API.
"""

__version__ = "0.1.0"
