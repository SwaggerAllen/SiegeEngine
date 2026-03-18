"""Tests for backend.dag.service – DAG helper functions (no DB required)."""

from unittest.mock import MagicMock

from backend.dag.service import (
    _build_prompt_info,
    _derive_stage_status,
    _find_artifact_node,
    _latest_executions,
)
from backend.models import StageStatus


# ── _build_prompt_info ────────────────────────────────────────────


class TestBuildPromptInfo:
    def test_with_prompt_config(self):
        pc = MagicMock()
        pc.model = "claude-sonnet-4-20250514"
        stage_def = MagicMock()
        stage_def.stage_key = "system_requirements"
        stage_def.prompt_config = pc
        stage_def.prompt_template_key = "system_requirements"

        result = _build_prompt_info(stage_def)
        assert result["stage_key"] == "system_requirements"
        assert result["model"] == "claude-sonnet-4-20250514"
        assert result["has_custom_config"] is True
        assert result["template_key"] == "system_requirements"

    def test_without_prompt_config(self):
        stage_def = MagicMock()
        stage_def.stage_key = "code_generation"
        stage_def.prompt_config = None
        stage_def.prompt_template_key = "codegen"

        result = _build_prompt_info(stage_def)
        assert result["model"] is None
        assert result["has_custom_config"] is False


# ── _latest_executions ────────────────────────────────────────────


def _mock_exec(component_key, started_at, status=StageStatus.APPROVED):
    e = MagicMock()
    e.component_key = component_key
    e.started_at = started_at
    e.completed_at = started_at
    e.status = status
    return e


class TestLatestExecutions:
    def test_single_execution_per_component(self):
        execs = [_mock_exec("auth", 10), _mock_exec("api", 20)]
        result = _latest_executions(execs)
        assert len(result) == 2

    def test_keeps_latest_when_retried(self):
        old = _mock_exec("auth", 10, StageStatus.FAILED)
        new = _mock_exec("auth", 20, StageStatus.APPROVED)
        result = _latest_executions([old, new])
        assert len(result) == 1
        assert result[0].started_at == 20

    def test_none_component_key(self):
        e1 = _mock_exec(None, 5)
        e2 = _mock_exec(None, 15)
        result = _latest_executions([e1, e2])
        assert len(result) == 1
        assert result[0].started_at == 15

    def test_empty_list(self):
        assert _latest_executions([]) == []


# ── _derive_stage_status ──────────────────────────────────────────


class TestDeriveStageStatus:
    def test_empty_returns_pending(self):
        status, is_active = _derive_stage_status([])
        assert status == "pending"
        assert is_active is False

    def test_all_approved(self):
        execs = [
            _mock_exec("a", 10, StageStatus.APPROVED),
            _mock_exec("b", 20, StageStatus.APPROVED),
        ]
        status, is_active = _derive_stage_status(execs)
        assert status == "approved"
        assert is_active is False

    def test_running_takes_priority(self):
        execs = [
            _mock_exec("a", 10, StageStatus.APPROVED),
            _mock_exec("b", 20, StageStatus.RUNNING),
        ]
        status, is_active = _derive_stage_status(execs)
        assert status == "running"
        assert is_active is True

    def test_ai_review_is_active(self):
        execs = [_mock_exec("a", 10, StageStatus.AI_REVIEW)]
        status, is_active = _derive_stage_status(execs)
        assert status == "ai_reviewing"
        assert is_active is True

    def test_failed_not_active(self):
        execs = [_mock_exec("a", 10, StageStatus.FAILED)]
        status, is_active = _derive_stage_status(execs)
        assert status == "failed"
        assert is_active is False

    def test_awaiting_review(self):
        execs = [_mock_exec("a", 10, StageStatus.AWAITING_REVIEW)]
        status, is_active = _derive_stage_status(execs)
        assert status == "awaiting_review"
        assert is_active is False

    def test_mixed_approved_and_pending_shows_awaiting(self):
        execs = [
            _mock_exec("a", 10, StageStatus.APPROVED),
            _mock_exec("b", 20, StageStatus.PENDING),
        ]
        status, is_active = _derive_stage_status(execs)
        # Some approved, some not all approved -> awaiting_review
        assert status == "awaiting_review"
        assert is_active is False


# ── _find_artifact_node ───────────────────────────────────────────


class TestFindArtifactNode:
    def test_finds_matching_node(self):
        nodes = [
            {"data": {"artifact_type": "code", "component_key": "auth"}},
            {"data": {"artifact_type": "code", "component_key": "api"}},
        ]
        result = _find_artifact_node(nodes, "code", "auth")
        assert result is not None
        assert result["data"]["component_key"] == "auth"

    def test_returns_none_when_not_found(self):
        nodes = [
            {"data": {"artifact_type": "code", "component_key": "auth"}},
        ]
        assert _find_artifact_node(nodes, "code", "nonexistent") is None

    def test_empty_nodes(self):
        assert _find_artifact_node([], "code", "auth") is None
