"""Tests for backend.models – enums, model defaults, and status transitions."""

from backend.models import (
    ArtifactStatus,
    ArtifactType,
    ExecutionMode,
    FanOutStrategy,
    PipelineRunStatus,
    StageStatus,
    StopPoint,
)


class TestArtifactStatus:
    def test_all_statuses_defined(self):
        expected = {
            "pending",
            "generating",
            "ai_reviewing",
            "awaiting_review",
            "approved",
            "rejected",
            "failed",
            "stale",
        }
        actual = {s.value for s in ArtifactStatus}
        assert actual == expected

    def test_string_values(self):
        assert ArtifactStatus.APPROVED == "approved"
        assert ArtifactStatus.STALE == "stale"


class TestArtifactType:
    def test_project_doc_exists(self):
        assert ArtifactType.PROJECT_DOC == "project_doc"

    def test_code_types_exist(self):
        assert ArtifactType.CODE == "code"
        assert ArtifactType.CODE_REVIEW == "code_review"

    def test_component_types(self):
        component_types = [t for t in ArtifactType if "component" in t.value.lower()]
        assert len(component_types) >= 6  # requirements, architecture, plan for both levels


class TestStageStatus:
    def test_all_statuses(self):
        expected = {
            "pending",
            "running",
            "ai_review",
            "awaiting_review",
            "approved",
            "rejected",
            "skipped",
            "failed",
        }
        actual = {s.value for s in StageStatus}
        assert actual == expected


class TestPipelineRunStatus:
    def test_all_statuses(self):
        expected = {"running", "paused", "completed", "failed", "cancelled"}
        actual = {s.value for s in PipelineRunStatus}
        assert actual == expected


class TestStopPoint:
    def test_all_stop_points(self):
        expected = {"end_of_phase", "before_code", "every_artifact", "after_all", "at_fan_out", "after_triplets"}
        actual = {s.value for s in StopPoint}
        assert actual == expected


class TestExecutionMode:
    def test_modes(self):
        assert ExecutionMode.GATED == "gated"
        assert ExecutionMode.ASYNC == "async"


class TestFanOutStrategy:
    def test_strategies(self):
        expected = {"none", "component", "sub_component", "leaf"}
        actual = {s.value for s in FanOutStrategy}
        assert actual == expected
