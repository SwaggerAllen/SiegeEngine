from backend.pipeline.prompts.base import PromptTemplate


class ExtractComponentsPrompt(PromptTemplate):
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

        system_arch = input_artifacts.get("system_architecture", "")
        input_docs = input_artifacts.get("input_documents", "")

        context_parts = []
        if input_docs:
            context_parts.append(f"INPUT DOCUMENTS:\n\n{input_docs}")
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
            feedback,
            human_notes,
            current_content,
            upstream_changes,
        )
