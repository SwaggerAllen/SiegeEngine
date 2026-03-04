from backend.pipeline.prompts.architecture import ArchitecturePrompt
from backend.pipeline.prompts.base import PromptTemplate
from backend.pipeline.prompts.codegen import CodeGenPrompt
from backend.pipeline.prompts.component_arch import ComponentArchPrompt
from backend.pipeline.prompts.component_plan import ComponentPlanPrompt
from backend.pipeline.prompts.high_level_plan import HighLevelPlanPrompt

PROMPT_REGISTRY: dict[str, type[PromptTemplate]] = {
    "architecture": ArchitecturePrompt,
    "component_arch": ComponentArchPrompt,
    "high_level_plan": HighLevelPlanPrompt,
    "component_plan": ComponentPlanPrompt,
    "codegen": CodeGenPrompt,
}
