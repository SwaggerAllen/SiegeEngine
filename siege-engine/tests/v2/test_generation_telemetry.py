"""Tests for generation telemetry: CLI parser, handler write, route surface.

Telemetry is observability, not state — it's written by handlers as
a side effect of each LLM call, not through the event-sourced
reducer. These tests lock in that contract.
"""

from __future__ import annotations

import json

import pytest

from backend.cli.manager import GenerationResult, _parse_json_result


class TestParseJsonResult:
    def test_happy_path_with_input_output_tokens(self):
        raw = json.dumps(
            {
                "result": "hello world",
                "model": "claude-sonnet-4-6",
                "usage": {"input_tokens": 1234, "output_tokens": 567},
            }
        )
        got = _parse_json_result(raw, fallback_model=None)
        assert got.text == "hello world"
        assert got.prompt_tokens == 1234
        assert got.completion_tokens == 567
        assert got.model == "claude-sonnet-4-6"

    def test_happy_path_with_prompt_completion_aliases(self):
        # Some CLI versions use prompt_tokens/completion_tokens instead
        # of input_tokens/output_tokens. We accept either.
        raw = json.dumps(
            {
                "text": "hello again",
                "model": "claude-opus-4-6",
                "usage": {"prompt_tokens": 42, "completion_tokens": 17},
            }
        )
        got = _parse_json_result(raw, fallback_model=None)
        assert got.text == "hello again"
        assert got.prompt_tokens == 42
        assert got.completion_tokens == 17
        assert got.model == "claude-opus-4-6"

    def test_missing_usage_falls_back_to_zero(self):
        raw = json.dumps({"result": "no usage here", "model": "claude-sonnet-4-6"})
        got = _parse_json_result(raw, fallback_model=None)
        assert got.text == "no usage here"
        assert got.prompt_tokens == 0
        assert got.completion_tokens == 0
        assert got.model == "claude-sonnet-4-6"

    def test_missing_model_uses_fallback(self):
        raw = json.dumps({"result": "x", "usage": {"input_tokens": 1, "output_tokens": 2}})
        got = _parse_json_result(raw, fallback_model="claude-sonnet-4-6")
        assert got.model == "claude-sonnet-4-6"

    def test_missing_model_and_no_fallback_returns_unknown(self):
        raw = json.dumps({"result": "x"})
        got = _parse_json_result(raw, fallback_model=None)
        assert got.model == "unknown"

    def test_invalid_json_returns_raw_with_zeros(self):
        got = _parse_json_result("not json at all", fallback_model=None)
        assert got.text == "not json at all"
        assert got.prompt_tokens == 0
        assert got.completion_tokens == 0
        assert got.model == "unknown"

    def test_empty_result_field_returns_empty_text(self):
        raw = json.dumps({"result": "", "usage": {"input_tokens": 5}})
        got = _parse_json_result(raw, fallback_model="claude-sonnet-4-6")
        assert got.text == ""
        assert got.prompt_tokens == 5


class TestGenerationResultDataclass:
    def test_frozen(self):
        r = GenerationResult(text="hi", prompt_tokens=1, completion_tokens=2, model="m")
        with pytest.raises(AttributeError):
            r.text = "oops"  # type: ignore[misc]
