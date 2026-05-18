"""siege_mcp — Read-only MCP server for SiegeEngine project state.

The package supersedes the old SQLAlchemy backend: state lives in git
(`state/<tier>/<id>.json` + `<tier>/<id>/body.md`), the MCP server
provides typed reads, and skills installed via the Claude Code plugin
do the writing (one commit per state transition).

Module layout:

- ``config`` — environment-driven settings (mirrors backend's
  ``SIEGE_`` prefix where useful).
- ``auth`` — simplified JWT verification ported from
  ``backend/auth/service.py``.
- ``state`` — typed dataclasses for state JSON + load/save helpers.
- ``git_view`` — ``GitView`` substrate: a per-(project, ref, head_sha)
  in-memory snapshot of every state JSON, with lazy-loaded bodies.
- ``fragments`` — fragment kinds + per-section body extraction (the
  git-backed replacement for the old Fragment table).
- ``parsers`` — body section parser, review XML parser.
- ``tiers`` — per-tier generation- and review-context builders.
- ``review_summary`` / ``structure`` — aggregation helpers.
- ``validate`` — pre-commit validation gate.
- ``tools`` — MCP tool registrations.
- ``server`` — MCP + HTTP transport entry point.
"""

__version__ = "0.1.0"
