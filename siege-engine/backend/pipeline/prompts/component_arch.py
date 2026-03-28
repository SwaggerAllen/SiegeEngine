from backend.pipeline.prompts.base import PromptTemplate


class ComponentArchPrompt(PromptTemplate):
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

        feature_expansion = input_artifacts.get("feature_expansion", "")
        system_arch = input_artifacts.get("system_architecture", "")
        input_docs = input_artifacts.get("input_documents", "")

        context_parts = []
        if feature_expansion:
            context_parts.append(f"FEATURE EXPANSION:\n\n{feature_expansion}")
        if system_arch:
            context_parts.append(f"SYSTEM ARCHITECTURE:\n\n{system_arch}")
        if input_docs:
            context_parts.append(f"INPUT DOCUMENTS:\n\n{input_docs}")
        dep_archs = input_artifacts.get("dependency_architectures", "")
        if dep_archs:
            context_parts.append(f"DEPENDENCY COMPONENT ARCHITECTURES:\n\n{dep_archs}")

        messages = [
            {"role": "system", "content": self.full_system_message},
            {
                "role": "user",
                "content": "\n\n---\n\n".join(context_parts)
                + f"\n\nCOMPONENT TO DESIGN: {component_key}\n\n"
                "Produce a detailed architecture for this component.",
            },
        ]
        return self._inject_feedback(
            messages,
            feedback,
            human_notes,
            current_content,
            upstream_changes,
        )
