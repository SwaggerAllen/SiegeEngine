"""Tests for backend.pipeline.defaults – pipeline stage configuration."""

from backend.pipeline.defaults import DEFAULT_STAGES


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
