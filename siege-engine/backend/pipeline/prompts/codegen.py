from backend.pipeline.prompts.base import PromptTemplate


class CodeGenPrompt(PromptTemplate):
    def build(
        self,
        input_artifacts,
        component_key=None,
        feedback=None,
        human_notes=None,
        prompt_config=None,
    ):
        if prompt_config:
            return self._build_from_config(
                input_artifacts, component_key, feedback, human_notes, prompt_config
            )

        component_plan = input_artifacts.get("component_plans", "")
        component_arch = input_artifacts.get("component_architectures", "")
        messages = [
            {"role": "system", "content": self.full_system_message},
            {
                "role": "user",
                "content": f"COMPONENT ARCHITECTURE:\n\n{component_arch}\n\n"
                f"IMPLEMENTATION PLAN:\n\n{component_plan}\n\n"
                f"COMPONENT: {component_key}\n\n"
                "Generate the code for this component.",
            },
        ]
        return self._inject_feedback(messages, feedback, human_notes)
