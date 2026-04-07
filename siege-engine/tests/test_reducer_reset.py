"""Tests for pipeline_reset reducer behavior."""

from backend.pipeline import events as evt
from backend.pipeline.reducer import apply_event, empty_snapshot


class TestPipelineResetPreservesPending:
    """pipeline_reset should preserve 'pending' stage_statuses."""

    def test_pending_stages_stay_pending(self):
        snap = empty_snapshot()
        # Set up some stage statuses
        snap["stage_statuses"]["feature_expansion"] = "approved"
        snap["stage_statuses"]["component_architectures/auth"] = "pending"
        snap["stage_statuses"]["component_architectures/identity"] = "pending"

        snap = apply_event(snap, evt.PIPELINE_RESET, {}, sequence=1)

        # Pending stages stay pending
        assert snap["stage_statuses"]["component_architectures/auth"] == "pending"
        assert snap["stage_statuses"]["component_architectures/identity"] == "pending"
        # Non-pending stages reset to awaiting_review
        assert snap["stage_statuses"]["feature_expansion"] == "awaiting_review"

    def test_approved_stages_reset_to_awaiting_review(self):
        snap = empty_snapshot()
        snap["stage_statuses"]["feature_expansion"] = "approved"
        snap["stage_statuses"]["system_architecture"] = "approved"

        snap = apply_event(snap, evt.PIPELINE_RESET, {}, sequence=1)

        assert snap["stage_statuses"]["feature_expansion"] == "awaiting_review"
        assert snap["stage_statuses"]["system_architecture"] == "awaiting_review"

    def test_rejected_stages_reset_to_awaiting_review(self):
        snap = empty_snapshot()
        snap["stage_statuses"]["component_architectures/auth"] = "rejected"

        snap = apply_event(snap, evt.PIPELINE_RESET, {}, sequence=1)

        assert snap["stage_statuses"]["component_architectures/auth"] == "awaiting_review"

    def test_failed_stages_reset_to_awaiting_review(self):
        snap = empty_snapshot()
        snap["stage_statuses"]["code_generation/auth"] = "failed"

        snap = apply_event(snap, evt.PIPELINE_RESET, {}, sequence=1)

        assert snap["stage_statuses"]["code_generation/auth"] == "awaiting_review"

    def test_reset_clears_execution_map(self):
        snap = empty_snapshot()
        snap["execution_map"]["feature_expansion"] = "exec-1"
        snap["execution_map"]["component_architectures/auth"] = "exec-2"

        snap = apply_event(snap, evt.PIPELINE_RESET, {}, sequence=1)

        assert snap["execution_map"] == {}

    def test_reset_clears_is_running(self):
        snap = empty_snapshot()
        snap["is_running"] = True

        snap = apply_event(snap, evt.PIPELINE_RESET, {}, sequence=1)

        assert snap["is_running"] is False
