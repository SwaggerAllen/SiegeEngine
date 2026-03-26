from backend.pipeline.prompts.base import PromptTemplate


class ExtractSubComponentsPrompt(PromptTemplate):
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
                input_artifacts,
                component_key,
                feedback,
                human_notes,
                prompt_config,
                current_content=current_content,
                upstream_changes=upstream_changes,
            )

        component_arch = input_artifacts.get("component_architectures", "")
        system_reqs = input_artifacts.get("system_requirements", "")

        context_parts = []
        if component_arch:
            context_parts.append(f"COMPONENT ARCHITECTURE:\n\n{component_arch}")
        if system_reqs:
            context_parts.append(f"SYSTEM REQUIREMENTS:\n\n{system_reqs}")

        messages = [
            {"role": "system", "content": self.full_system_message},
            {
                "role": "user",
                "content": "\n\n---\n\n".join(context_parts) + f"\n\nCOMPONENT: {component_key}\n\n"
                "Evaluate whether this component needs sub-component decomposition.",
            },
        ]
        return self._inject_feedback(
            messages,
            feedback,
            human_notes,
            current_content,
            upstream_changes,
        )
