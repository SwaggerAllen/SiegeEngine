from backend.pipeline.prompts.base import PromptTemplate


class SubComponentPlanPrompt(PromptTemplate):

    def build(self, input_artifacts, component_key=None, feedback=None, human_notes=None, prompt_config=None):
        if prompt_config:
            return self._build_from_config(input_artifacts, component_key, feedback, human_notes, prompt_config)

        sub_comp_arch = input_artifacts.get("sub_component_architectures", "")
        sub_comp_reqs = input_artifacts.get("sub_component_requirements", "")

        context_parts = []
        if sub_comp_arch:
            context_parts.append(f"SUB-COMPONENT ARCHITECTURE:\n\n{sub_comp_arch}")
        if sub_comp_reqs:
            context_parts.append(f"SUB-COMPONENT REQUIREMENTS:\n\n{sub_comp_reqs}")

        messages = [
            {"role": "system", "content": self.full_system_message},
            {
                "role": "user",
                "content": "\n\n---\n\n".join(context_parts)
                + f"\n\nSUB-COMPONENT: {component_key}\n\n"
                "Produce a detailed implementation plan for this sub-component.",
            },
        ]
        return self._inject_feedback(messages, feedback, human_notes)
