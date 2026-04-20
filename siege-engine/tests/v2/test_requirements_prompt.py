"""B5 — Requirements prompt pins the "non-overlapping responsibilities" rule.

Snapshot-style check that guards against accidental removal of
the non-overlap guidance, which is the load-bearing rule for
keeping sysarch's component-boundary decisions clean.
"""

from __future__ import annotations

from backend.graph.prompts.requirements import render_system_prompt


def test_non_overlapping_rule_present():
    sys = render_system_prompt()
    assert "Responsibilities do not overlap" in sys, (
        "Requirements prompt must state the non-overlap rule — see B5. "
        "Two resps must not claim ownership of the same system "
        "capability; that rule keeps sysarch's component boundaries "
        "clean."
    )


def test_overlap_example_present():
    """The worked overlap example (Billing vs Receipts) is a
    memorable shorthand the LLM can pattern-match against."""
    sys = render_system_prompt()
    assert "Billing" in sys and "Receipts" in sys, (
        "Requirements prompt must include the Billing/Receipts "
        "overlap example so the LLM has a concrete pattern to "
        "match against."
    )


def test_does_not_cover_clause_remains():
    """The non-overlap rule complements the 'does not cover'
    guidance; both should be present."""
    sys = render_system_prompt()
    assert "does **not** cover" in sys
