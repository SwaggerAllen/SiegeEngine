from pathlib import Path

import yaml

from backend.pipeline.prompts.ai_review_prompt import AIReviewPrompt
from backend.pipeline.prompts.architecture import ArchitecturePrompt
from backend.pipeline.prompts.base import PromptTemplate
from backend.pipeline.prompts.code_review import CodeReviewPrompt
from backend.pipeline.prompts.codegen import CodeGenPrompt
from backend.pipeline.prompts.component_arch import ComponentArchPrompt
from backend.pipeline.prompts.component_plan import ComponentPlanPrompt
from backend.pipeline.prompts.extract_components import ExtractComponentsPrompt
from backend.pipeline.prompts.extract_sub_components import ExtractSubComponentsPrompt
from backend.pipeline.prompts.requirements import SystemRequirementsPrompt
from backend.pipeline.prompts.sub_component_architecture import SubComponentArchPrompt
from backend.pipeline.prompts.sub_component_plan import SubComponentPlanPrompt

PROMPT_REGISTRY: dict[str, type[PromptTemplate]] = {
    "system_requirements": SystemRequirementsPrompt,
    "architecture": ArchitecturePrompt,
    "component_arch": ComponentArchPrompt,
    "component_plan": ComponentPlanPrompt,
    "extract_components": ExtractComponentsPrompt,
    "extract_sub_components": ExtractSubComponentsPrompt,
    "sub_component_arch": SubComponentArchPrompt,
    "sub_component_plan": SubComponentPlanPrompt,
    "codegen": CodeGenPrompt,
    "code_review": CodeReviewPrompt,
    "ai_review": AIReviewPrompt,
}

# ── Load prompt defaults from YAML ───────────────────────────────────────────
_yaml_path = Path(__file__).parent / "defaults.yaml"
with open(_yaml_path) as _f:
    _PROMPT_DEFAULTS = yaml.safe_load(_f)

# Apply shared defaults to the base class
if "formatting_guidance" in _PROMPT_DEFAULTS:
    PromptTemplate.formatting_guidance = _PROMPT_DEFAULTS["formatting_guidance"]
if "revision_instructions" in _PROMPT_DEFAULTS:
    PromptTemplate.default_revision_instructions = _PROMPT_DEFAULTS["revision_instructions"]

# Apply per-prompt defaults
_FIELD_MAP = {
    "system_message": "default_system_message",
    "output_format_instructions": "default_output_format",
    "context_template": "default_context_template",
    "revision_instructions": "default_revision_instructions",
    "formatting_guidance": "formatting_guidance",
}

for _key, _prompt_cls in PROMPT_REGISTRY.items():
    _cfg = _PROMPT_DEFAULTS.get("prompts", {}).get(_key, {})
    for _yaml_key, _attr_name in _FIELD_MAP.items():
        if _yaml_key in _cfg:
            setattr(_prompt_cls, _attr_name, _cfg[_yaml_key])
