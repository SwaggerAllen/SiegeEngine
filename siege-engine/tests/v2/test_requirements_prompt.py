"""Requirements prompt — atomic-grammar rule invariants.

The atomic grammar collapses each responsibility to one concern:
``<name>`` + ``<feats>``. Name-dedup and feat-coverage are
mechanical invariants; many-to-many at the feat level is
expected; empty ``<feats/>`` is legal. These tests lock in the
load-bearing guidance so it doesn't get edited out by accident.
"""

from __future__ import annotations

from backend.graph.prompts.requirements import render_system_prompt


def test_name_dedup_rule_present():
    sys = render_system_prompt()
    assert "Name-dedup" in sys, (
        "Requirements prompt must state the name-dedup rule — two atoms must not share a name."
    )


def test_feat_coverage_guidance_present():
    sys = render_system_prompt()
    assert "Feat-coverage" in sys, (
        "Requirements prompt must state that every feature appears "
        "in at least one atom's <feats> — the validator enforces it."
    )


def test_many_to_many_rule_present():
    """Many-to-many at the feat level is the key shift away from
    single-owner. The prompt must tell the LLM a feature may
    legitimately appear in multiple atoms' ``<feats>``."""
    sys = render_system_prompt()
    assert "Many-to-many" in sys
    assert "implicates" in sys or "implicate" in sys


def test_rotation_worked_example_present():
    """The worked example shows the rotation in action: a handful
    of features expanding into ten-ish atoms, with one feat on
    multiple atoms and one atom with empty <feats/>."""
    sys = render_system_prompt()
    assert "<requirements>" in sys
    assert "<feats/>" in sys, "Example must include an empty <feats/> atom."
    assert '<feat id="feat_login01"/>' in sys


def test_empty_feats_allowed_guidance():
    sys = render_system_prompt()
    assert "Empty ``<feats/>`` is legal" in sys or "empty" in sys.lower()
    assert "system-emergent" in sys


def test_platform_nfr_atomization_guidance_present():
    """The reqs tier is the one and only chance to atomize
    platform-NFR concerns — rate limiting, audit logging, token
    telemetry, fuses, encryption, SLA enforcement, license
    compliance. Sysarch cannot recover these if reqs doesn't emit
    them, so the prompt must explicitly name them as atom-eligible.
    """
    sys = render_system_prompt()
    assert "platform-nfr" in sys.lower() or "platform nfr" in sys.lower()
    # Concrete NFR examples so the LLM has category shape to match.
    for example in ("rate limiting", "audit", "telemetry", "AGPL"):
        assert example.lower() in sys.lower(), (
            f"Requirements prompt must name {example!r} as an NFR example."
        )
    # The worked example gains at least one NFR-shaped atom with
    # empty <feats/>, so reviewers see the pattern concretely.
    assert "audit every credential access" in sys
