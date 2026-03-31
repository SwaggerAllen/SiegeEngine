from backend.pipeline.prompts.base import PromptTemplate


class ComponentPlanPrompt(PromptTemplate):
    def build(
        self,
        input_artifacts,
        component_key=None,
        human_notes=None,
        prompt_config=None,
        current_content=None,
        upstream_changes=None,
    ):
        if prompt_config:
            return self._build_from_config(
                input_artifacts,
                component_key,
                human_notes,
                prompt_config,
                current_content=current_content,
                upstream_changes=upstream_changes,
            )

        component_arch = input_artifacts.get("component_architectures", "")
        component_map = input_artifacts.get("extract_components", "")
        dep_archs = input_artifacts.get("dependency_architectures", "")
        context = (
            f"COMPONENT MAP:\n\n{component_map}\n\nCOMPONENT ARCHITECTURE:\n\n{component_arch}"
        )
        if dep_archs:
            context += f"\n\nDEPENDENCY COMPONENT ARCHITECTURES:\n\n{dep_archs}"
        messages = [
            {"role": "system", "content": self.full_system_message},
            {
                "role": "user",
                "content": context + f"\n\nCOMPONENT: {component_key}\n\n"
                "Produce a detailed implementation plan for this component.",
            },
        ]
        return self._inject_feedback(
            messages,
            human_notes,
            current_content,
            upstream_changes,
        )
