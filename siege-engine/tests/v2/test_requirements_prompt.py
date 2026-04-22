"""Requirements prompt — structural-overlap rule invariants.

The scope-list grammar moved overlap detection from prose "does
not cover" disclaimers into a mechanical rule: scope phrases must
be unique across responsibilities, and ``<does-not-own>`` entries
with ``<defers to="...">`` are the structured boundary-work path.
These tests lock in the load-bearing guidance so it doesn't get
edited out by accident.
"""

from __future__ import annotations

from backend.graph.prompts.requirements import render_system_prompt


def test_scope_dedup_rule_present():
    sys = render_system_prompt()
    assert "Scope-dedup rule" in sys, (
        "Requirements prompt must state the scope-dedup rule — "
        "two responsibilities must not share a scope phrase, "
        "because scope phrases are the primary mechanical dedup target."
    )


def test_single_owner_rule_present():
    sys = render_system_prompt()
    assert "Single-owner rule" in sys, (
        "Requirements prompt must state the single-owner rule so "
        "the LLM knows the validator enforces one <owns> per feature."
    )


def test_does_not_own_guidance_present():
    """The <does-not-own> / <defers> structured boundary path must
    be described — that's the replacement for the old prose
    'does not cover' clause, doing the same boundary work in a
    machine-readable form."""
    sys = render_system_prompt()
    assert "<does-not-own>" in sys
    assert "<defers" in sys
    assert 'to="' in sys, (
        'Prompt must show the to="Other Responsibility" attribute '
        "shape so the LLM emits resolvable cross-references."
    )


def test_scope_phrase_examples_present():
    """Worked scope-phrase examples give the LLM concrete patterns
    to match against — short noun phrases on the system axis."""
    sys = render_system_prompt()
    # Good examples
    assert "append-only event log" in sys
    # Bad examples distinguishing system vs feature axis
    assert "users can log in" in sys
    assert "(feature axis)" in sys


def test_failure_surface_guidance_present():
    sys = render_system_prompt()
    assert "<failure-surface>" in sys
    assert "concrete failure mode" in sys
