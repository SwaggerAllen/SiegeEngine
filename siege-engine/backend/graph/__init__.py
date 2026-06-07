"""v2 structured model — events, reducer, queries (read side).

Reads go through :mod:`backend.graph.queries`. Application code does
not touch the projection ORM models directly.

This package no longer registers any job handlers. The legacy
``v2.apply_instructions`` and ``v2.rename_rewrite`` handlers retired
with the write pipeline; per-tier generation / review handlers
retired earlier in the read-side rewrite. All authoring now happens
through Claude Code skills against the v3 git substrate.
"""
