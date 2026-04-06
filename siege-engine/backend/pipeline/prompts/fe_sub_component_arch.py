from backend.pipeline.prompts.base import PromptTemplate


class FESubComponentArchPrompt(PromptTemplate):
    def build(
        self,
        input_artifacts,
        component_key=None,
        human_notes=None,
        current_content=None,
        upstream_changes=None,
    ):
        component_arch = input_artifacts.get("fe_component_architectures", "")
        sub_component_map = input_artifacts.get("fe_extract_sub_components", "")

        context_parts = []
        if component_arch:
            context_parts.append(f"PARENT FRONTEND COMPONENT ARCHITECTURE:\n\n{component_arch}")
        if sub_component_map:
            context_parts.append(f"SUB-COMPONENT DECOMPOSITION:\n\n{sub_component_map}")
        domain_parents = input_artifacts.get("domain_parent_architectures", "")
        if domain_parents:
            context_parts.append(f"DOMAIN PARENT ARCHITECTURES:\n\n{domain_parents}")
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
                + f"\n\nFRONTEND SUB-COMPONENT: {component_key}\n\n"
                "Produce a detailed architecture for this frontend sub-component.",
            },
        ]
        return self._inject_feedback(
            messages,
            human_notes,
            current_content,
            upstream_changes,
        )
