from backend.pipeline.prompts.base import PromptTemplate


class ComponentPlanPrompt(PromptTemplate):

    def build(self, input_artifacts, component_key=None, feedback=None, human_notes=None, prompt_config=None):
        if prompt_config:
            return self._build_from_config(input_artifacts, component_key, feedback, human_notes, prompt_config)

        component_arch = input_artifacts.get("component_architectures", "")
        component_reqs = input_artifacts.get("component_requirements", "")
        component_map = input_artifacts.get("extract_components", "")
        messages = [
            {"role": "system", "content": self.full_system_message},
            {
                "role": "user",
                "content": f"COMPONENT MAP:\n\n{component_map}\n\n"
                f"COMPONENT ARCHITECTURE:\n\n{component_arch}\n\n"
                f"COMPONENT REQUIREMENTS:\n\n{component_reqs}\n\n"
                f"COMPONENT: {component_key}\n\n"
                "Produce a detailed implementation plan for this component.",
            },
        ]
        return self._inject_feedback(messages, feedback, human_notes)
