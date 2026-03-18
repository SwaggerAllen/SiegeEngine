from backend.pipeline.prompts.base import PromptTemplate


class CodeReviewPrompt(PromptTemplate):
    def build(
        self,
        input_artifacts,
        component_key=None,
        feedback=None,
        human_notes=None,
        prompt_config=None,
        current_content=None,
        upstream_changes=None,
    ):
        if prompt_config:
            return self._build_from_config(
                input_artifacts, component_key, feedback, human_notes, prompt_config,
                current_content=current_content, upstream_changes=upstream_changes
            )

        component_plan = input_artifacts.get("component_plans", "")
        component_arch = input_artifacts.get("component_architectures", "")
        code_content = input_artifacts.get("code_generation", "")

        messages = [
            {"role": "system", "content": self.full_system_message},
            {
                "role": "user",
                "content": f"COMPONENT ARCHITECTURE:\n\n{component_arch}\n\n"
                f"IMPLEMENTATION PLAN:\n\n{component_plan}\n\n"
                f"GENERATED CODE:\n\n{code_content}\n\n"
                f"COMPONENT: {component_key}\n\n"
                "Review the code for this component. Fix any issues, run tests, "
                "and iterate until the code is production-ready.",
            },
        ]
        return self._inject_feedback(messages, feedback, human_notes, current_content, upstream_changes)
