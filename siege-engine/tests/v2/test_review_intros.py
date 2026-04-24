"""B3 — Every per-tier review prompt supplies a prose intro for each section.

Pins the invariant that review system prompts include the
``_HANDLES_INTRO`` / ``_ARCHITECTURE_INTRO`` paragraphs before
the bullet criteria. The shared template still renders correctly
when tiers omit the kwargs (uses a safe default) so older code
paths stay backward compatible.
"""

from __future__ import annotations

import pytest

from backend.graph.prompts.review import (
    comparch,
    expansion,
    fanin,
    impl,
    requirements,
    subcomparch,
    subreqs,
    sysarch,
)
from backend.graph.prompts.review._shared import render_review_system_prompt


@pytest.mark.parametrize(
    "tier_module, tier_name",
    [
        (expansion, "expansion"),
        (requirements, "requirements"),
        (sysarch, "sysarch"),
        (subreqs, "subreqs"),
        (comparch, "comparch"),
        (subcomparch, "subcomparch"),
        (impl, "impl"),
        (fanin, "fanin"),
    ],
)
def test_tier_review_prompt_includes_prose_intros(tier_module, tier_name):
    system_prompt = tier_module.render_system_prompt()
    # Both section headers are present.
    assert "Handles & structure review" in system_prompt
    assert "Architectural-decisions review" in system_prompt
    # Intros land before criteria — each tier's intro is more than
    # one sentence; use a length heuristic to guard against a tier
    # accidentally dropping its intro.
    handles_idx = system_prompt.find("Handles & structure review")
    architecture_idx = system_prompt.find("Architectural-decisions review")
    handles_body = system_prompt[handles_idx:architecture_idx]
    architecture_body = system_prompt[architecture_idx:]
    # Strip the "Specific checks under..." line to count intro length.
    handles_intro_body = handles_body.split("Specific checks under")[0]
    architecture_intro_body = architecture_body.split("Specific checks under")[0]
    # Intros should be prose paragraphs, not empty placeholders.
    # 120 chars ≈ a 2-sentence paragraph.
    assert len(handles_intro_body.strip()) > 120, (
        f"{tier_name} handles intro too short — add prose framing before the "
        f"bullet criteria. Got: {handles_intro_body!r}"
    )
    assert len(architecture_intro_body.strip()) > 120, (
        f"{tier_name} architecture intro too short — add prose framing. "
        f"Got: {architecture_intro_body!r}"
    )


def test_sysarch_review_prompt_treats_presentational_mirror_as_intended():
    """Presentational components should mirror their domain parent's
    resp IDs in their own ``<responsibilities>`` block — that's the
    spec-intended pattern, not a flaw. The review prompt must say so
    explicitly and must NOT instruct the reviewer to flag a resp
    appearing in one domain + one presentational as "doubly-mapped."
    Catching this in a previous prompt revision: the reviewer scored
    a clean draft 44/100 on the basis that 35 resp IDs were
    "double-mapped" between domain and presentational components,
    which was the intended mirror, not a bug."""
    system_prompt = sysarch.render_system_prompt()
    handles_idx = system_prompt.find("Handles & structure review")
    arch_idx = system_prompt.find("Architectural-decisions review")
    handles_body = system_prompt[handles_idx:arch_idx]
    # Positive framing must appear: mirror is correct.
    assert "intended pattern" in handles_body
    assert "mirror" in handles_body.lower()
    # The "doubly-mapped" framing must be qualified: only flag when
    # both endpoints are domain components, NOT the
    # domain-plus-presentational mirror.
    assert "domain double-ownership" in handles_body.lower() or (
        "two *domain* components" in handles_body
    )
    # The parroting check must scope itself to invariants/operations
    # *content*, not resp-ID assignment.
    assert "content" in handles_body.lower()


def test_reqs_review_prompt_flags_tech_leaks_in_names():
    """The reqs tier is pre-tech-choice — sysarch owns libraries,
    frameworks, and algorithm selection. Atom names that embed a
    specific library/framework/algorithm author-name leak sysarch's
    decisions back into the reqs tier and should be flagged. Wire
    protocols (SAML, OIDC, HTTP) are fine because swapping them
    changes what the atom means."""
    system_prompt = requirements.render_system_prompt()
    handles_idx = system_prompt.find("Handles & structure review")
    arch_idx = system_prompt.find("Architectural-decisions review")
    handles_body = system_prompt[handles_idx:arch_idx]
    # The rule itself must appear.
    assert "technology choices" in handles_body.lower() or "tech-choice" in handles_body.lower()
    # Concrete bad-example renames so the reviewer has pattern shape.
    assert "Liquid" in handles_body
    assert "Sugiyama" in handles_body
    # The carve-out that wire protocols are fine must be explicit.
    assert "SAML" in handles_body or "wire-protocol" in handles_body.lower()


def test_reqs_review_prompt_flags_missing_nfr_atoms():
    """The reqs review is the platform's last chance to catch a
    missing NFR atom before sysarch compresses. The prompt must
    explicitly tell the reviewer to check for platform-NFR coverage
    (rate limiting, audit, telemetry, fuses, encryption, SLA,
    license hygiene) with concrete examples."""
    system_prompt = requirements.render_system_prompt()
    # The NFR check is under the architectural-decisions section.
    arch_idx = system_prompt.find("Architectural-decisions review")
    arch_body = system_prompt[arch_idx:]
    assert "platform-NFR" in arch_body or "platform NFR" in arch_body
    # Concrete categories the reviewer should name-check against.
    for example in ("rate limiting", "audit", "telemetry"):
        assert example.lower() in arch_body.lower(), (
            f"Reqs review prompt must name {example!r} as an NFR example."
        )
    # The reviewer must call out specific missing atoms, not
    # flag NFR-coverage generically.
    assert "Don't flag generically" in arch_body or "name the missing atom" in arch_body


def test_shared_template_renders_with_default_intros_when_absent():
    """Backward compatibility: tiers that omit the intro kwargs
    get a safe generic paragraph rather than an empty section."""
    rendered = render_review_system_prompt(
        artifact_label="``<x>``",
        scope_label="this scope",
        handles_criteria="- check A\n- check B\n",
        architecture_criteria="- axis check\n",
    )
    assert "Handles & structure review" in rendered
    assert "Architectural-decisions review" in rendered
    # Default intros are non-empty.
    assert "Audit the artifact's handle quality" in rendered
    assert "Audit the artifact's architectural choices" in rendered
