from backend.pipeline.prompts.ai_review_prompt import AIReviewPrompt
from backend.pipeline.prompts.architecture import ArchitecturePrompt
from backend.pipeline.prompts.base import PromptTemplate
from backend.pipeline.prompts.code_review import CodeReviewPrompt
from backend.pipeline.prompts.codegen import CodeGenPrompt
from backend.pipeline.prompts.component_arch import ComponentArchPrompt
from backend.pipeline.prompts.component_plan import ComponentPlanPrompt
from backend.pipeline.prompts.high_level_plan import HighLevelPlanPrompt
from backend.pipeline.prompts.requirements import (
    ComponentRequirementsPrompt,
    SystemRequirementsPrompt,
)

PROMPT_REGISTRY: dict[str, type[PromptTemplate]] = {
    "system_requirements": SystemRequirementsPrompt,
    "component_requirements": ComponentRequirementsPrompt,
    "architecture": ArchitecturePrompt,
    "component_arch": ComponentArchPrompt,
    "high_level_plan": HighLevelPlanPrompt,
    "component_plan": ComponentPlanPrompt,
    "codegen": CodeGenPrompt,
    "code_review": CodeReviewPrompt,
    "ai_review": AIReviewPrompt,
}
