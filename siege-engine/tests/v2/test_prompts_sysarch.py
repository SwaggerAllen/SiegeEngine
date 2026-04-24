"""Tests for ``backend.graph.prompts.sysarch.render_user_prompt``.

Parallel to ``test_prompts_requirements.py`` — narrow coverage of
the ``input_doc`` kwarg that the handler passes only on the
initial bootstrap generation.
"""

from __future__ import annotations

from backend.graph.prompts.sysarch import render_system_prompt, render_user_prompt


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
