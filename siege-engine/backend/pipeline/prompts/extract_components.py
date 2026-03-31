from backend.pipeline.prompts.base import PromptTemplate


class ExtractComponentsPrompt(PromptTemplate):
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

        feature_expansion = input_artifacts.get("feature_expansion", "")
        system_arch = input_artifacts.get("system_architecture", "")

        context_parts = []
        if feature_expansion:
            context_parts.append(f"FEATURE EXPANSION:\n\n{feature_expansion}")
        if system_arch:
            context_parts.append(f"SYSTEM ARCHITECTURE:\n\n{system_arch}")

        messages = [
            {"role": "system", "content": self.full_system_message},
            {
                "role": "user",
                "content": "\n\n---\n\n".join(context_parts)
                + "\n\nIdentify the components and their inter-dependencies.",
            },
        ]
        return self._inject_feedback(
            messages,
            human_notes,
            current_content,
            upstream_changes,
        )
