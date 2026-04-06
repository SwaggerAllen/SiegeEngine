from backend.pipeline.prompts.base import PromptTemplate


class FEComponentPlanPrompt(PromptTemplate):
    def build(
        self,
        input_artifacts,
        component_key=None,
        human_notes=None,
        current_content=None,
        upstream_changes=None,
    ):
        component_arch = input_artifacts.get("fe_component_architectures", "")
        component_map = input_artifacts.get("extract_components", "")
        dep_archs = input_artifacts.get("dependency_architectures", "")
        domain_parents = input_artifacts.get("domain_parent_architectures", "")

        context_parts = []
        if component_map:
            context_parts.append(f"COMPONENT MAP:\n\n{component_map}")
        if component_arch:
            context_parts.append(f"FRONTEND COMPONENT ARCHITECTURE:\n\n{component_arch}")
        if domain_parents:
            context_parts.append(f"DOMAIN PARENT ARCHITECTURES:\n\n{domain_parents}")
        if dep_archs:
            context_parts.append(f"DEPENDENCY COMPONENT ARCHITECTURES:\n\n{dep_archs}")

        messages = [
            {"role": "system", "content": self.full_system_message},
            {
                "role": "user",
                "content": "\n\n---\n\n".join(context_parts)
                + f"\n\nFRONTEND COMPONENT: {component_key}\n\n"
                "Produce a detailed implementation plan for this frontend component.",
            },
        ]
        return self._inject_feedback(
            messages,
            human_notes,
            current_content,
            upstream_changes,
        )
