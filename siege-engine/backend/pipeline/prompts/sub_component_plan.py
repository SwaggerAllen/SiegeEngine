from backend.pipeline.prompts.base import PromptTemplate


class SubComponentPlanPrompt(PromptTemplate):
    def build(
        self,
        input_artifacts,
        component_key=None,
        human_notes=None,
        current_content=None,
        upstream_changes=None,
    ):
        sub_comp_arch = input_artifacts.get("sub_component_architectures", "")
        component_arch = input_artifacts.get("component_architectures", "")

        context_parts = []
        if sub_comp_arch:
            context_parts.append(f"SUB-COMPONENT ARCHITECTURE:\n\n{sub_comp_arch}")
        if component_arch:
            context_parts.append(f"PARENT COMPONENT ARCHITECTURE:\n\n{component_arch}")
        dep_archs = input_artifacts.get("dependency_architectures", "")
        if dep_archs:
            context_parts.append(f"DEPENDENCY SUB-COMPONENT ARCHITECTURES:\n\n{dep_archs}")
        parent_dep_summaries = input_artifacts.get("parent_dependency_summaries", "")
        if parent_dep_summaries:
            context_parts.append(f"PARENT DEPENDENCY CONTRACT SUMMARIES:\n\n{parent_dep_summaries}")

        messages = [
            {"role": "system", "content": self.full_system_message},
            {
                "role": "user",
                "content": "\n\n---\n\n".join(context_parts)
                + f"\n\nSUB-COMPONENT: {component_key}\n\n"
                "Produce a detailed implementation plan for this sub-component.",
            },
        ]
        return self._inject_feedback(
            messages,
            human_notes,
            current_content,
            upstream_changes,
        )
