"""Tests for backend.pipeline.defaults – pipeline stage configuration."""

from backend.pipeline.defaults import DEFAULT_STAGES
from backend.pipeline.readiness import (
    COMPONENT_STAGE_ORDER,
    SUB_COMPONENT_STAGE_ORDER,
    _STAGE_KEY_TO_ORDER,
)


class TestDefaultStages:
    def test_stages_not_empty(self):
        assert len(DEFAULT_STAGES) > 0

    def test_stages_have_required_keys(self):
        required = {
            "stage_key",
            "display_name",
            "order_index",
            "output_artifact_type",
            "input_stage_keys",
            "fan_out_strategy",
            "prompt_template_key",
        }
        for stage in DEFAULT_STAGES:
            missing = required - set(stage.keys())
            assert not missing, f"Stage '{stage.get('stage_key')}' missing keys: {missing}"

    def test_order_indices_are_sequential(self):
        indices = [s["order_index"] for s in DEFAULT_STAGES]
        assert indices == sorted(indices)
        assert indices == list(range(len(DEFAULT_STAGES)))

    def test_stage_keys_are_unique(self):
        keys = [s["stage_key"] for s in DEFAULT_STAGES]
        assert len(keys) == len(set(keys))

    def test_input_stage_keys_reference_valid_stages(self):
        valid_keys = {s["stage_key"] for s in DEFAULT_STAGES}
        for stage in DEFAULT_STAGES:
            for input_key in stage["input_stage_keys"]:
                assert input_key in valid_keys, (
                    f"Stage '{stage['stage_key']}' references unknown input '{input_key}'"
                )

    def test_first_stage_has_no_inputs(self):
        first = DEFAULT_STAGES[0]
        assert first["input_stage_keys"] == []

    def test_fan_out_strategies_are_valid(self):
        valid = {"none", "component", "sub_component", "leaf"}
        for stage in DEFAULT_STAGES:
            assert stage["fan_out_strategy"] in valid, (
                f"Stage '{stage['stage_key']}' has invalid fan_out_strategy"
            )

    def test_no_circular_dependencies(self):
        """Verify input_stage_keys never reference a stage with equal or higher order_index."""
        key_to_order = {s["stage_key"]: s["order_index"] for s in DEFAULT_STAGES}
        for stage in DEFAULT_STAGES:
            for input_key in stage["input_stage_keys"]:
                assert key_to_order[input_key] < stage["order_index"], (
                    f"Stage '{stage['stage_key']}' (order {stage['order_index']}) "
                    f"depends on '{input_key}' (order {key_to_order[input_key]})"
                )

    def test_code_generation_uses_leaf_fan_out(self):
        code_gen = next(s for s in DEFAULT_STAGES if s["stage_key"] == "code_generation")
        assert code_gen["fan_out_strategy"] == "leaf"

    def test_system_stages_have_no_fan_out(self):
        for stage in DEFAULT_STAGES:
            if stage["stage_key"].startswith("system_"):
                assert stage["fan_out_strategy"] == "none"


class TestStageOrderConsistency:
    """Ensure readiness ordering constants stay in sync with DEFAULT_STAGES."""

    def test_stage_key_to_order_matches_defaults(self):
        """_STAGE_KEY_TO_ORDER must match the order_index in DEFAULT_STAGES."""
        for stage in DEFAULT_STAGES:
            key = stage["stage_key"]
            assert key in _STAGE_KEY_TO_ORDER, f"Missing key in _STAGE_KEY_TO_ORDER: {key}"
            assert _STAGE_KEY_TO_ORDER[key] == stage["order_index"], (
                f"Order mismatch for '{key}': "
                f"_STAGE_KEY_TO_ORDER={_STAGE_KEY_TO_ORDER[key]}, "
                f"DEFAULT_STAGES={stage['order_index']}"
            )

    def test_component_stage_order_is_ascending(self):
        """COMPONENT_STAGE_ORDER must list stages in ascending order_index."""
        indices = [_STAGE_KEY_TO_ORDER[k] for k in COMPONENT_STAGE_ORDER]
        assert indices == sorted(indices), (
            f"COMPONENT_STAGE_ORDER is not in ascending order: {list(zip(COMPONENT_STAGE_ORDER, indices))}"
        )

    def test_sub_component_stage_order_is_ascending(self):
        """SUB_COMPONENT_STAGE_ORDER must list stages in ascending order_index."""
        indices = [_STAGE_KEY_TO_ORDER[k] for k in SUB_COMPONENT_STAGE_ORDER]
        assert indices == sorted(indices), (
            f"SUB_COMPONENT_STAGE_ORDER is not in ascending order: {list(zip(SUB_COMPONENT_STAGE_ORDER, indices))}"
        )
