"""B8 — Universal-scope policies: optional <required> field.

Pins that policies can omit ``<required>`` (or leave it empty)
and still validate. Universal policies — AGPL license
obligations, org-wide conventions — don't map to a single
enforcing responsibility; the application pass attaches them
to every candidate component in scope instead.
"""

from __future__ import annotations

import pytest

from backend.graph.handlers.sysarch_mint import _serialize_policy_blob
from backend.graph.parsers.validators import (
    Policy,
    ValidationError,
    validate_policy_blob,
)
from backend.graph.prompts.policy_application import format_candidate_policies


def _policy_xml(*, name, trigger, rationale, required=None):
    parts = [
        "<policy>",
        f"<name>{name}</name>",
        f"<trigger>{trigger}</trigger>",
    ]
    if required is not None:
        parts.append(f"<required>{required}</required>")
    parts.append(f"<rationale>{rationale}</rationale>")
    parts.append("</policy>")
    return "".join(parts)


class TestValidatorAcceptsOmitted:
    def test_policy_without_required_is_universal(self):
        xml = _policy_xml(
            name="AGPL Compliance",
            trigger="any module distributed as part of the build",
            rationale=(
                "The project ships under AGPL; every component must carry the "
                "license notice and ensure source availability."
            ),
        )
        policy = validate_policy_blob(xml, known_resp_ids=set())
        assert policy.required_resp_id is None
        assert policy.name == "AGPL Compliance"

    def test_policy_with_empty_required_is_universal(self):
        xml = (
            "<policy>"
            "<name>Convention</name>"
            "<trigger>any new module</trigger>"
            "<required></required>"
            "<rationale>Stub rationale paragraph explaining why.</rationale>"
            "</policy>"
        )
        policy = validate_policy_blob(xml, known_resp_ids=set())
        assert policy.required_resp_id is None

    def test_policy_with_valid_required_still_works(self):
        xml = _policy_xml(
            name="Telemetry",
            trigger="any LLM call",
            rationale="We want per-call telemetry for observability.",
            required="resp_TEL000001",
        )
        policy = validate_policy_blob(xml, known_resp_ids={"resp_TEL000001"})
        assert policy.required_resp_id == "resp_TEL000001"

    def test_policy_with_bogus_required_raises(self):
        xml = _policy_xml(
            name="Bad",
            trigger="any call",
            rationale="Rationale paragraph for the bad policy test case.",
            required="resp_BOGUSXYZ",
        )
        with pytest.raises(ValidationError, match="unknown responsibility"):
            validate_policy_blob(xml, known_resp_ids={"resp_REAL00001"})

    def test_multiple_required_rejected(self):
        xml = (
            "<policy>"
            "<name>Bad</name>"
            "<trigger>any call</trigger>"
            "<required>resp_A</required>"
            "<required>resp_B</required>"
            "<rationale>Rationale for the multi-required bad test case.</rationale>"
            "</policy>"
        )
        with pytest.raises(ValidationError, match="at most one"):
            validate_policy_blob(xml, known_resp_ids={"resp_A", "resp_B"})


class TestPolicyBlobSerializer:
    def test_universal_policy_round_trip(self):
        p = Policy(
            name="AGPL",
            trigger="any module",
            required_resp_id=None,
            rationale="Paragraph rationale for the universal scope test case.",
        )
        blob = _serialize_policy_blob(p)
        # No <required> tag at all in the blob.
        assert "<required>" not in blob
        # Round-trip parses back as universal.
        reparsed = validate_policy_blob(blob, known_resp_ids=set())
        assert reparsed.required_resp_id is None
        assert reparsed.name == "AGPL"

    def test_scoped_policy_round_trip(self):
        p = Policy(
            name="Telemetry",
            trigger="any LLM call",
            required_resp_id="resp_TEL000001",
            rationale="Rationale paragraph for the scoped policy round-trip.",
        )
        blob = _serialize_policy_blob(p)
        reparsed = validate_policy_blob(blob, known_resp_ids={"resp_TEL000001"})
        assert reparsed.required_resp_id == "resp_TEL000001"


class TestApplicationPromptFormat:
    def test_universal_policy_renders_without_required(self):
        out = format_candidate_policies(
            [
                {
                    "id": "policy_U1",
                    "name": "AGPL",
                    "trigger": "any module",
                    "required": None,
                    "rationale": "License obligation.",
                }
            ]
        )
        assert "universal-scope policy" in out
        assert "no required resp" not in out  # old placeholder gone

    def test_scoped_policy_renders_required_id(self):
        out = format_candidate_policies(
            [
                {
                    "id": "policy_S1",
                    "name": "Telemetry",
                    "trigger": "any LLM call",
                    "required": "resp_TEL000001",
                    "rationale": "Observability.",
                }
            ]
        )
        assert "resp_TEL000001" in out
