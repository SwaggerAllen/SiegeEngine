"""Guard the expansion review prompt against re-regressing on
the "implicits-are-the-point" framing.

The generator is explicitly instructed to include features not
in the input doc but obviously needed by the project (marked
``<implicit/>``). The review prompt used to treat *any* feature
not in the spec as speculative, which fought the generator and
produced unhelpful "this is not in the doc" findings. These
tests pin the corrective language so a future edit doesn't
quietly undo it.
"""

from __future__ import annotations

from backend.graph.prompts.review.expansion import render_system_prompt


def test_intro_names_implicit_inference_as_expected():
    sys = render_system_prompt()
    # The corrective phrase about implicit features being the
    # generator doing its job.
    assert "extraction *and inference*" in sys
    # The concrete "flag wrong inferences, not presence" rule.
    assert "wrong for this project" in sys


def test_handles_criteria_separates_correctness_from_presence():
    sys = render_system_prompt()
    assert "Implicit features — correctness, not presence" in sys
    # The worked anti-examples — these are the patterns reviewers
    # should match against when deciding whether to flag an
    # implicit feature.
    assert "single-user" in sys
    assert "multi-tenant" in sys or "team invitations" in sys


def test_coverage_direction_is_scoped_to_gaps():
    """The 'does the feature set cover the input doc' bullet
    should only fire for features *missing from what the doc
    describes*, not for features beyond the doc."""
    sys = render_system_prompt()
    assert "the other direction, features *beyond* the doc, is expected" in sys
