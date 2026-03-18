"""Tests for backend.pipeline.engine – PipelineEngine helper methods."""

from unittest.mock import MagicMock

from backend.models import StopPoint
from backend.pipeline.engine import BRANCHING_STAGES, PipelineEngine


def _make_stage_def(stage_key, human_review_enabled=True):
    sd = MagicMock()
    sd.stage_key = stage_key
    sd.human_review_enabled = human_review_enabled
    return sd


def _make_run(human_review=True, stop_point=StopPoint.AFTER_ALL):
    run = MagicMock()
    run.human_review = human_review
    run.stop_point = stop_point
    return run


class TestShouldPause:
    """Test PipelineEngine._should_pause logic."""

    def setup_method(self):
        self.engine = PipelineEngine.__new__(PipelineEngine)

    def test_no_run_uses_stage_human_review(self):
        sd = _make_stage_def("system_requirements", human_review_enabled=True)
        assert self.engine._should_pause(sd, None) is True

        sd2 = _make_stage_def("system_requirements", human_review_enabled=False)
        assert self.engine._should_pause(sd2, None) is False

    def test_human_review_off_never_pauses(self):
        sd = _make_stage_def("system_requirements", human_review_enabled=True)
        run = _make_run(human_review=False)
        assert self.engine._should_pause(sd, run) is False

    def test_after_all_with_human_review_on(self):
        sd = _make_stage_def("system_requirements", human_review_enabled=True)
        run = _make_run(human_review=True, stop_point=StopPoint.AFTER_ALL)
        assert self.engine._should_pause(sd, run) is True

    def test_after_all_stage_review_disabled(self):
        sd = _make_stage_def("code_generation", human_review_enabled=False)
        run = _make_run(human_review=True, stop_point=StopPoint.AFTER_ALL)
        assert self.engine._should_pause(sd, run) is False

    def test_before_code_pauses_code_stages(self):
        run = _make_run(human_review=True, stop_point=StopPoint.BEFORE_CODE)
        for key in ("code_generation", "code_review"):
            sd = _make_stage_def(key, human_review_enabled=False)
            assert self.engine._should_pause(sd, run) is True

    def test_before_code_non_code_stage_uses_human_review(self):
        sd = _make_stage_def("system_requirements", human_review_enabled=False)
        run = _make_run(human_review=True, stop_point=StopPoint.BEFORE_CODE)
        assert self.engine._should_pause(sd, run) is False

    def test_branching_stage_always_pauses_with_human_review(self):
        for stage_key in BRANCHING_STAGES:
            sd = _make_stage_def(stage_key, human_review_enabled=False)
            run = _make_run(human_review=True, stop_point=StopPoint.AFTER_ALL)
            assert self.engine._should_pause(sd, run) is True


class TestBranchingStages:
    def test_branching_stages_defined(self):
        assert len(BRANCHING_STAGES) > 0

    def test_extract_components_is_branching(self):
        assert "extract_components" in BRANCHING_STAGES

    def test_extract_sub_components_is_branching(self):
        assert "extract_sub_components" in BRANCHING_STAGES
