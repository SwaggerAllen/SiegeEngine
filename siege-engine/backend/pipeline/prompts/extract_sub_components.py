from backend.pipeline.prompts.base import PromptTemplate


class ExtractSubComponentsPrompt(PromptTemplate):
    def build(
        self,
        input_artifacts,
        component_key=None,
        human_notes=None,
        current_content=None,
        upstream_changes=None,
    ):
        component_arch = input_artifacts.get("component_architectures", "")

        context_parts = []
        if component_arch:
            context_parts.append(f"COMPONENT ARCHITECTURE:\n\n{component_arch}")

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
            human_notes,
            current_content,
            upstream_changes,
        )
