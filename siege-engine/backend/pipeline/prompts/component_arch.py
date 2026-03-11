from backend.pipeline.prompts.base import PromptTemplate


class ComponentArchPrompt(PromptTemplate):

    def build(self, input_artifacts, component_key=None, feedback=None, human_notes=None, prompt_config=None):
        if prompt_config:
            return self._build_from_config(input_artifacts, component_key, feedback, human_notes, prompt_config)

        comp_reqs = input_artifacts.get("component_requirements", "")
        system_arch = input_artifacts.get("system_architecture", "")

        context_parts = []
        if comp_reqs:
            context_parts.append(f"COMPONENT REQUIREMENTS:\n\n{comp_reqs}")
        if system_arch:
            context_parts.append(f"SYSTEM ARCHITECTURE:\n\n{system_arch}")

        messages = [
            {"role": "system", "content": self.full_system_message},
            {
                "role": "user",
                "content": "\n\n---\n\n".join(context_parts)
                + f"\n\nCOMPONENT TO DESIGN: {component_key}\n\n"
                "Produce a detailed architecture for this component.",
            },
        ]
        return self._inject_feedback(messages, feedback, human_notes)
