from backend.pipeline.prompts.base import PromptTemplate


class FEComponentArchPrompt(PromptTemplate):
    def build(
        self,
        input_artifacts,
        component_key=None,
        human_notes=None,
        current_content=None,
        upstream_changes=None,
    ):
        feature_expansion = input_artifacts.get("feature_expansion", "")
        system_arch = input_artifacts.get("system_architecture", "")

        context_parts = []
        if feature_expansion:
            context_parts.append(f"FEATURE EXPANSION:\n\n{feature_expansion}")
        if system_arch:
            context_parts.append(f"SYSTEM ARCHITECTURE:\n\n{system_arch}")
        domain_parents = input_artifacts.get("domain_parent_architectures", "")
        if domain_parents:
            context_parts.append(f"DOMAIN PARENT ARCHITECTURES:\n\n{domain_parents}")
        dep_archs = input_artifacts.get("dependency_architectures", "")
        if dep_archs:
            context_parts.append(f"DEPENDENCY COMPONENT ARCHITECTURES:\n\n{dep_archs}")

        messages = [
            {"role": "system", "content": self.full_system_message},
            {
                "role": "user",
                "content": "\n\n---\n\n".join(context_parts)
                + f"\n\nFRONTEND COMPONENT TO DESIGN: {component_key}\n\n"
                "Produce a detailed architecture for this frontend component.",
            },
        ]
        return self._inject_feedback(
            messages,
            human_notes,
            current_content,
            upstream_changes,
        )
