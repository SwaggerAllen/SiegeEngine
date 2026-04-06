import json
import logging
import re

logger = logging.getLogger(__name__)


def _parse_json_from_content(content: str) -> dict | list | None:
    """Extract the first JSON object or array from content (tagged block or raw)."""
    # Try ```components block first
    pattern = r"```components\s*\n(.*?)```"
    match = re.search(pattern, content, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    # Fallback: find JSON object
    pattern = r'\{[\s\S]*?"(?:components|domain_components)"[\s\S]*?\}'
    match = re.search(pattern, content)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    # Fallback: find JSON array with "key" fields
    pattern = r'\[[\s\S]*?"key"[\s\S]*?\]'
    match = re.search(pattern, content)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    return None


def parse_dual_components_from_content(content: str) -> dict:
    """Parse components in dual format: {"domain": [...], "frontend": [...]}.

    Supports both old format (flat list / {"components": [...]}) and new dual
    format ({"domain_components": [...], "frontend_components": [...]}).
    """
    data = _parse_json_from_content(content)
    if data is None:
        return {"domain": [], "frontend": []}

    # New dual format
    if isinstance(data, dict) and "domain_components" in data:
        return {
            "domain": data.get("domain_components", []),
            "frontend": data.get("frontend_components", []),
        }

    # Old format — treat everything as domain
    if isinstance(data, dict) and "components" in data:
        return {"domain": data["components"], "frontend": []}
    if isinstance(data, list):
        return {"domain": data, "frontend": []}

    return {"domain": [], "frontend": []}


def parse_components_from_content(content: str) -> list[dict]:
    """Parse components from a ```components tagged code block or raw JSON.

    Backward-compatible: returns only domain components.
    """
    return parse_dual_components_from_content(content)["domain"]


def parse_sub_components_from_content(content: str) -> dict:
    """Parse sub-component extraction result.

    Returns dict with keys:
        needs_decomposition: bool
        components: list[dict]
    """
    # Try ```components block first
    pattern = r"```components\s*\n(.*?)```"
    match = re.search(pattern, content, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(1))
            if isinstance(data, dict):
                return {
                    "needs_decomposition": data.get("needs_decomposition", False),
                    "components": data.get("components", []),
                }
        except json.JSONDecodeError:
            pass

    # Fallback: find JSON object with "needs_decomposition" key
    pattern = r'\{[\s\S]*?"needs_decomposition"[\s\S]*?\}'
    match = re.search(pattern, content)
    if match:
        try:
            data = json.loads(match.group(0))
            return {
                "needs_decomposition": data.get("needs_decomposition", False),
                "components": data.get("components", []),
            }
        except json.JSONDecodeError:
            pass

    return {"needs_decomposition": False, "components": []}


def validate_dependency_dag(components: list[dict]) -> list[str]:
    """Validate that component dependencies form a DAG (no cycles).

    Returns list of error messages (empty if valid).
    """
    errors = []
    keys = {c.get("key", "") for c in components}

    for comp in components:
        for dep in comp.get("dependencies", []):
            if dep not in keys:
                errors.append(f"Component '{comp.get('key')}' depends on unknown key '{dep}'")
            if dep == comp.get("key"):
                errors.append(f"Component '{comp.get('key')}' depends on itself")

    # Check for cycles using DFS
    adj = {c.get("key", ""): c.get("dependencies", []) for c in components}
    visited = set()
    in_stack = set()

    def dfs(node):
        if node in in_stack:
            errors.append(f"Circular dependency detected involving '{node}'")
            return
        if node in visited:
            return
        in_stack.add(node)
        for dep in adj.get(node, []):
            if dep in keys:
                dfs(dep)
        in_stack.discard(node)
        visited.add(node)

    for key in keys:
        dfs(key)

    return errors
