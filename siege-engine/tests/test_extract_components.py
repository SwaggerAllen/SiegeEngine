"""Tests for backend.pipeline.nodes.extract_components."""

import json

from backend.pipeline.nodes.extract_components import (
    parse_components_from_content,
    parse_sub_components_from_content,
    validate_dependency_dag,
)

# ── parse_components_from_content ──────────────────────────────────


class TestParseComponentsFromContent:
    def test_components_code_block_with_list(self):
        components = [
            {"key": "auth", "name": "Auth", "dependencies": []},
            {"key": "api", "name": "API", "dependencies": ["auth"]},
        ]
        content = f"```components\n{json.dumps(components)}\n```"
        result = parse_components_from_content(content)
        assert len(result) == 2
        assert result[0]["key"] == "auth"
        assert result[1]["key"] == "api"

    def test_components_code_block_with_dict_wrapper(self):
        data = {
            "components": [
                {"key": "db", "name": "Database", "dependencies": []},
            ]
        }
        content = f"```components\n{json.dumps(data)}\n```"
        result = parse_components_from_content(content)
        assert len(result) == 1
        assert result[0]["key"] == "db"

    def test_fallback_to_json_object(self):
        data = {"components": [{"key": "web", "name": "Web"}]}
        content = f"Here is the output:\n{json.dumps(data)}"
        result = parse_components_from_content(content)
        assert len(result) == 1
        assert result[0]["key"] == "web"

    def test_fallback_to_json_array(self):
        data = [{"key": "svc", "name": "Service"}]
        content = f"Components:\n{json.dumps(data)}"
        result = parse_components_from_content(content)
        assert len(result) == 1
        assert result[0]["key"] == "svc"

    def test_no_json_returns_empty(self):
        content = "This is just plain text with no JSON."
        result = parse_components_from_content(content)
        assert result == []

    def test_invalid_json_returns_empty(self):
        content = "```components\nnot valid json\n```"
        result = parse_components_from_content(content)
        assert result == []


# ── parse_sub_components_from_content ──────────────────────────────


class TestParseSubComponentsFromContent:
    def test_needs_decomposition_true(self):
        data = {
            "needs_decomposition": True,
            "components": [
                {"key": "auth.tokens", "name": "Token Manager"},
            ],
        }
        content = f"```components\n{json.dumps(data)}\n```"
        result = parse_sub_components_from_content(content)
        assert result["needs_decomposition"] is True
        assert len(result["components"]) == 1

    def test_needs_decomposition_false(self):
        data = {"needs_decomposition": False, "components": []}
        content = f"```components\n{json.dumps(data)}\n```"
        result = parse_sub_components_from_content(content)
        assert result["needs_decomposition"] is False
        assert result["components"] == []

    def test_fallback_json_object(self):
        # The fallback regex matches the outermost {...} containing "needs_decomposition"
        data = {"needs_decomposition": True, "components": []}
        content = f"Result: {json.dumps(data)}"
        result = parse_sub_components_from_content(content)
        assert result["needs_decomposition"] is True

    def test_no_json_returns_defaults(self):
        content = "No components here."
        result = parse_sub_components_from_content(content)
        assert result["needs_decomposition"] is False
        assert result["components"] == []


# ── validate_dependency_dag ────────────────────────────────────────


class TestValidateDependencyDag:
    def test_valid_dag_no_errors(self):
        components = [
            {"key": "a", "dependencies": []},
            {"key": "b", "dependencies": ["a"]},
            {"key": "c", "dependencies": ["a", "b"]},
        ]
        errors = validate_dependency_dag(components)
        assert errors == []

    def test_unknown_dependency(self):
        components = [
            {"key": "a", "dependencies": ["nonexistent"]},
        ]
        errors = validate_dependency_dag(components)
        assert any("unknown key" in e for e in errors)

    def test_self_dependency(self):
        components = [
            {"key": "a", "dependencies": ["a"]},
        ]
        errors = validate_dependency_dag(components)
        assert any("depends on itself" in e for e in errors)

    def test_circular_dependency(self):
        components = [
            {"key": "a", "dependencies": ["b"]},
            {"key": "b", "dependencies": ["a"]},
        ]
        errors = validate_dependency_dag(components)
        assert any("Circular" in e for e in errors)

    def test_three_node_cycle(self):
        components = [
            {"key": "a", "dependencies": ["c"]},
            {"key": "b", "dependencies": ["a"]},
            {"key": "c", "dependencies": ["b"]},
        ]
        errors = validate_dependency_dag(components)
        assert any("Circular" in e for e in errors)
