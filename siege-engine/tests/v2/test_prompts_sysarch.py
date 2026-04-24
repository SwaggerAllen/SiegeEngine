"""Tests for ``backend.graph.prompts.sysarch.render_user_prompt``.

Parallel to ``test_prompts_requirements.py`` — narrow coverage of
the ``input_doc`` kwarg that the handler passes only on the
initial bootstrap generation.
"""

from __future__ import annotations

from backend.graph.prompts.sysarch import render_system_prompt, render_user_prompt


def test_no_target_component_count_guidance():
    """Sysarch prompt must not bias the LLM toward a particular
    component count. Conserving components by merging unrelated
    concerns produces vague handles just as splitting one coherent
    concern produces vague handles. Bias-free framing is "as many
    as the project's data-ownership and failure-mode boundaries
    warrant, and no fewer." Old framing ("Prefer fewer, sharper
    components to more, blurrier ones") biased toward under-emission,
    which produced bundles of unrelated concerns at the merged
    component."""
    sys = render_system_prompt()
    # Old biased framing must not appear.
    assert "Prefer fewer" not in sys
    # New explicit framing.
    assert "no target component count" in sys.lower()


def test_external_boundary_isolation_rule_present():
    """Each external integration (LLM provider, git forge, IdP,
    notification channel, payment processor, etc.) deserves its own
    component for failure-surface isolation. Bundling the
    LLM-dispatch boundary inside the prompt-rendering component is
    the exact smell this rule catches."""
    sys = render_system_prompt()
    assert "external boundary" in sys.lower() or "external boundaries" in sys.lower()
    # Concrete examples of external boundaries the LLM should
    # recognize as separate-component candidates.
    for example in ("LLM provider", "git forge", "SSO"):
        assert example in sys, f"External-boundary rule must name {example!r} as an example."
    # The "blast radius is one component's sandbox/retry" justification
    # must be explicit so the LLM understands the *why*, not just the
    # rule.
    assert "failure surface" in sys.lower()


def test_kind_split_is_interface_vs_domain_not_frontend_vs_backend():
    """The domain/presentational split is about external-interface
    vs. domain-logic, NOT backend-vs-frontend. A REST API surface,
    a webhook relay, and a notification dispatcher are all
    presentational (external interfaces outsiders consume) even
    though none are "frontend." The prompt must say this
    explicitly so the sysarch LLM doesn't misclassify non-UI
    consumption surfaces as domain.
    """
    sys = render_system_prompt()
    # Explicit framing.
    assert "external-interface" in sys.lower() or "external interface" in sys.lower()
    assert (
        "not backend-vs-frontend" in sys.lower()
        or "not backend/frontend" in sys.lower()
        or ("not backend-vs-frontend" in sys.lower())
    )
    # Non-UI presentational examples enumerated.
    for example in ("REST", "webhook", "notification"):
        assert example in sys, (
            f"Kind rule must name {example!r} as a presentational (interface) example."
        )
    # Outbound-call-wrapper examples that are domain, so the LLM
    # doesn't misclassify them as external interfaces.
    assert "LLM" in sys and "git" in sys.lower()
    # Decision test is spelled out.
    assert "would the system lose" in sys.lower() or "deleted this component" in sys.lower()


def test_backend_vocab_leak_self_check_present():
    """Presentational components must not parrot domain transactional
    invariants. The previous self-check (parrots-domain-invariants)
    catches some but not all cases — backend vocabulary like
    "persist", "atomically", "transaction", "commit" leaking into a
    presentational invariant is a specific failure mode that needs
    its own callout. Concrete worked example required so the LLM
    has pattern shape: "owner assignment captures persist
    atomically..." vs. the UI rewrite."""
    sys = render_system_prompt()
    # The ownership-vs-delivery distinction is named — ownership
    # words leak, delivery-format words (REST/HTTP/JSON/webhook)
    # are legitimate on interface presentationals.
    assert "ownership" in sys.lower() or "transactional" in sys.lower()
    # The forbidden-word list is explicit.
    for word in ("persist", "atomically", "commit"):
        assert word in sys, f"Backend-vocab self-check must name {word!r} as a flagged word."
    # The concrete worked example demonstrates the rewrite.
    assert "renders inline" in sys.lower() or "owner-assignment input" in sys


def test_policy_shaped_resp_guidance_present():
    """Reqs seeds policy-shaped atoms (rate limiting, audit, telemetry,
    license hygiene) as ordinary resps; sysarch decides per-atom whether
    each is local to one component (assign as a regular resp) or
    cross-cutting (lift to <policies>). The prompt must state this
    so the sysarch LLM doesn't treat every policy-shaped atom as a
    policy or ignore the signal entirely.
    """
    sys = render_system_prompt()
    # Explicitly name the decision sysarch has to make.
    assert "cross-cutting" in sys.lower()
    assert "local" in sys.lower()
    # The "when in doubt, local wins" rule biases toward under-
    # promotion, which matches the invariant that policies carry
    # application-edge overhead downstream.
    assert "local wins" in sys.lower() or "local — emit" in sys
    # Concrete reqs-seed examples so the LLM has pattern shape.
    assert "rate-limit" in sys.lower()
    assert "AGPL" in sys or "audit" in sys.lower()


class TestRenderUserPromptInputDoc:
    def _kwargs(self, **overrides: object) -> dict:
        base: dict[str, object] = {
            "features_summary": "- `feat_abc12345` **Widget**: Does widget things.",
            "reqs_summary": "- `resp_def67890` **Widget Storage**: Persists widgets.",
            "prior_approved": None,
            "prior_pending": None,
            "feedback": None,
        }
        base.update(overrides)
        return base

    def test_input_doc_renders_when_supplied(self) -> None:
        out = render_user_prompt(
            **self._kwargs(input_doc="A widget tracker with per-user storage quotas.")
        )
        assert "# Project input document" in out
        assert "A widget tracker with per-user storage quotas." in out
        # The input doc section must lead the features + resps
        # blocks so the LLM reads framing before derived data.
        doc_idx = out.index("# Project input document")
        feat_idx = out.index("# Project features")
        resp_idx = out.index("# Top-level responsibilities")
        assert doc_idx < feat_idx < resp_idx

    def test_input_doc_omitted_when_empty(self) -> None:
        out = render_user_prompt(**self._kwargs(input_doc=""))
        assert "# Project input document" not in out

    def test_input_doc_omitted_when_whitespace_only(self) -> None:
        out = render_user_prompt(**self._kwargs(input_doc="   \n  \n"))
        assert "# Project input document" not in out

    def test_default_omits_input_doc(self) -> None:
        out = render_user_prompt(**self._kwargs())
        assert "# Project input document" not in out
