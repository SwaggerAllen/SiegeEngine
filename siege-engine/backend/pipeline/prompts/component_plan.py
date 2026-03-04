from backend.pipeline.prompts.base import PromptTemplate


class ComponentPlanPrompt(PromptTemplate):
    default_system_message = """You are a senior software engineer producing a detailed implementation plan.
Given a component architecture and high-level delivery plan, produce a step-by-step implementation plan for this component."""

    default_output_format = """Your output MUST include:
1. Ordered list of files to create/modify
2. For each file: purpose, key functions/classes, dependencies
3. Implementation order within the component
4. Unit test plan with specific test cases
5. Integration points with other components
6. Estimated complexity per file (simple/moderate/complex)"""

    default_context_template = (
        "COMPONENT ARCHITECTURE:\n\n{input_artifacts}\n\n"
        "COMPONENT: {component_key}\n\n"
        "Produce a detailed implementation plan for this component."
    )

    def build(self, input_artifacts, component_key=None, feedback=None, human_notes=None, prompt_config=None):
        if prompt_config:
            return self._build_from_config(input_artifacts, component_key, feedback, human_notes, prompt_config)

        component_arch = input_artifacts.get("component_architectures", "")
        high_level_plan = input_artifacts.get("high_level_plan", "")
        messages = [
            {"role": "system", "content": self.full_system_message},
            {
                "role": "user",
                "content": f"COMPONENT ARCHITECTURE:\n\n{component_arch}\n\n"
                f"HIGH LEVEL PLAN:\n\n{high_level_plan}\n\n"
                f"COMPONENT: {component_key}\n\n"
                "Produce a detailed implementation plan for this component.",
            },
        ]
        return self._inject_feedback(messages, feedback, human_notes)
