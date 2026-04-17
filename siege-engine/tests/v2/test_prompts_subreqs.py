"""Tests for backend.graph.prompts.subrequirements."""

from __future__ import annotations

from backend.graph.prompts.subrequirements import (
    format_sibling_dep_context,
    render_user_prompt,
)


class TestSiblingDepContext:
    def test_empty_list_renders_empty(self):
        assert format_sibling_dep_context([]) == ""

    def test_deps_with_neither_signal_are_skipped(self):
        rendered = format_sibling_dep_context(
            [
                {"name": "AuthN", "api_intent": "", "responsibilities": []},
                {"name": "Billing", "api_intent": "   "},
            ]
        )
        assert rendered == ""

    def test_renders_each_dep_with_api_intent(self):
        rendered = format_sibling_dep_context(
            [
                {
                    "name": "AuthN",
                    "api_intent": "Issues session tokens; refresh + revoke.",
                },
                {
                    "name": "EventLog",
                    "api_intent": "Append-only audit log with back-pressure.",
                },
            ]
        )
        assert "## AuthN" in rendered
        assert "Issues session tokens; refresh + revoke." in rendered
        assert "## EventLog" in rendered
        assert "Append-only audit log with back-pressure." in rendered

    def test_renders_responsibilities_when_present(self):
        rendered = format_sibling_dep_context(
            [
                {
                    "name": "AuthN",
                    "api_intent": "Issues tokens.",
                    "responsibilities": [
                        {
                            "id": "resp_1",
                            "name": "Mint session",
                            "content": "Forge a new signed token.",
                        },
                        {
                            "id": "resp_2",
                            "name": "Rotate",
                            "content": "Rotate the signing key.",
                        },
                    ],
                }
            ]
        )
        assert "## AuthN" in rendered
        assert "API intent" in rendered
        assert "Issues tokens." in rendered
        assert "Responsibilities assigned here" in rendered
        assert "`resp_1`" in rendered
        assert "**Mint session**" in rendered
        assert "Forge a new signed token." in rendered
        assert "**Rotate**" in rendered

    def test_renders_dep_with_responsibilities_only(self):
        # Api intent missing but top-level resps present — still shown.
        rendered = format_sibling_dep_context(
            [
                {
                    "name": "Ledger",
                    "api_intent": "",
                    "responsibilities": [
                        {
                            "id": "resp_99",
                            "name": "Record entry",
                            "content": "Write a line to the log.",
                        }
                    ],
                }
            ]
        )
        assert "## Ledger" in rendered
        assert "Record entry" in rendered
        assert "API intent" not in rendered


class TestRenderUserPromptSiblingDeps:
    def test_block_absent_when_context_none(self):
        prompt = render_user_prompt(
            component_summary="## Billing\nsome role",
            parent_resps_summary="- `resp_1`",
            domain_parent_context=None,
            sibling_dep_context=None,
            prior_approved=None,
            prior_pending=None,
            feedback=None,
        )
        assert "Sibling dependency context" not in prompt

    def test_block_present_when_context_populated(self):
        prompt = render_user_prompt(
            component_summary="## Billing\nsome role",
            parent_resps_summary="- `resp_1`",
            domain_parent_context=None,
            sibling_dep_context="## AuthN\n\nIssues tokens.",
            prior_approved=None,
            prior_pending=None,
            feedback=None,
        )
        assert "Sibling dependency context" in prompt
        assert "## AuthN" in prompt
        assert "Issues tokens." in prompt
        # Advisory framing: the prompt must tell the LLM not to
        # cite dep ids in <derived-from>.
        assert "advisory" in prompt.lower()
