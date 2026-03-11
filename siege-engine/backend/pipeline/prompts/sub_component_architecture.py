from backend.pipeline.prompts.base import PromptTemplate


class SubComponentArchPrompt(PromptTemplate):

    def build(self, input_artifacts, component_key=None, feedback=None, human_notes=None, prompt_config=None):
        if prompt_config:
            return self._build_from_config(input_artifacts, component_key, feedback, human_notes, prompt_config)

        sub_comp_reqs = input_artifacts.get("sub_component_requirements", "")
        component_arch = input_artifacts.get("component_architectures", "")

        context_parts = []
        if component_arch:
            context_parts.append(f"PARENT COMPONENT ARCHITECTURE:\n\n{component_arch}")
        if sub_comp_reqs:
            context_parts.append(f"SUB-COMPONENT REQUIREMENTS:\n\n{sub_comp_reqs}")

        messages = [
            {"role": "system", "content": self.full_system_message},
            {
                "role": "user",
                "content": "\n\n---\n\n".join(context_parts)
                + f"\n\nSUB-COMPONENT: {component_key}\n\n"
                "Produce a detailed architecture for this sub-component.",
            },
        ]
        return self._inject_feedback(messages, feedback, human_notes)
