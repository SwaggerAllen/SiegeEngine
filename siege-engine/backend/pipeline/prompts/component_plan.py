from backend.pipeline.prompts.base import PromptTemplate


class ComponentPlanPrompt(PromptTemplate):

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
