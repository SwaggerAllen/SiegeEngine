from backend.pipeline.prompts.base import PromptTemplate


class SubComponentRequirementsPrompt(PromptTemplate):
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

        sub_component_map = input_artifacts.get("extract_sub_components", "")
        component_plan = input_artifacts.get("component_plans", "")
        component_arch = input_artifacts.get("component_architectures", "")

        context_parts = []
        if component_arch:
            context_parts.append(f"PARENT COMPONENT ARCHITECTURE:\n\n{component_arch}")
        if component_plan:
            context_parts.append(f"PARENT COMPONENT PLAN:\n\n{component_plan}")
        if sub_component_map:
            context_parts.append(f"SUB-COMPONENT DECOMPOSITION:\n\n{sub_component_map}")
        dep_archs = input_artifacts.get("dependency_architectures", "")
        if dep_archs:
            context_parts.append(f"DEPENDENCY SUB-COMPONENT ARCHITECTURES:\n\n{dep_archs}")

        messages = [
            {"role": "system", "content": self.full_system_message},
            {
                "role": "user",
                "content": "\n\n---\n\n".join(context_parts)
                + f"\n\nSUB-COMPONENT: {component_key}\n\n"
                "Produce detailed requirements for this sub-component.",
            },
        ]
        return self._inject_feedback(messages, feedback, human_notes)
