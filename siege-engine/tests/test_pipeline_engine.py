"""Tests for backend.pipeline.engine – PipelineEngine helper methods."""

from unittest.mock import MagicMock

from backend.models import StopPoint
from backend.pipeline.engine import BRANCHING_STAGES, PipelineEngine


def _make_stage_def(stage_key, order_index=0):
    sd = MagicMock()
    sd.stage_key = stage_key
    sd.order_index = order_index
    return sd


def _make_run(stop_point=StopPoint.EVERY_ARTIFACT):
    run = MagicMock()
    run.stop_point = stop_point
    return run


class TestShouldPause:
    """Test PipelineEngine._should_pause logic."""

    def setup_method(self):
        self.engine = PipelineEngine.__new__(PipelineEngine)

    def test_no_run_always_pauses(self):
        sd = _make_stage_def("system_requirements")
        assert self.engine._should_pause(sd, None) is True

    def test_every_artifact_always_pauses(self):
        sd = _make_stage_def("system_requirements")
        run = _make_run(stop_point=StopPoint.EVERY_ARTIFACT)
        assert self.engine._should_pause(sd, run) is True

    def test_before_code_pauses_code_stages(self):
        run = _make_run(stop_point=StopPoint.BEFORE_CODE)
        for key in ("code_generation", "code_review"):
            sd = _make_stage_def(key)
            assert self.engine._should_pause(sd, run) is True

    def test_before_code_does_not_pause_non_code_stages(self):
        sd = _make_stage_def("system_requirements")
        run = _make_run(stop_point=StopPoint.BEFORE_CODE)
        assert self.engine._should_pause(sd, run) is False

    def test_end_of_phase_pauses_later_stages(self):
        sd = _make_stage_def("code_generation", order_index=5)
        run = _make_run(stop_point=StopPoint.END_OF_PHASE)
        # Mock the helper methods used by END_OF_PHASE
        self.engine._get_start_order = MagicMock(return_value=2)
        self.engine._starting_phase_complete = MagicMock(return_value=False)
        assert self.engine._should_pause(sd, run, project_id="proj-1") is True

    def test_end_of_phase_does_not_pause_same_phase(self):
        sd = _make_stage_def("system_requirements", order_index=1)
        run = _make_run(stop_point=StopPoint.END_OF_PHASE)
        self.engine._get_start_order = MagicMock(return_value=2)
        self.engine._starting_phase_complete = MagicMock(return_value=False)
        assert self.engine._should_pause(sd, run, project_id="proj-1") is False


class TestBranchingStages:
    def test_branching_stages_defined(self):
        assert len(BRANCHING_STAGES) > 0

    def test_extract_components_is_branching(self):
        assert "extract_components" in BRANCHING_STAGES

    def test_extract_sub_components_is_branching(self):
        assert "extract_sub_components" in BRANCHING_STAGES
