from backend.pipeline.prompts.base import PromptTemplate


class FECodeGenPrompt(PromptTemplate):
    def build(
        self,
        input_artifacts,
        component_key=None,
        human_notes=None,
        current_content=None,
        upstream_changes=None,
    ):
        component_plan = input_artifacts.get("fe_component_plans", "")
        component_arch = input_artifacts.get("fe_component_architectures", "")
        domain_parents = input_artifacts.get("domain_parent_architectures", "")

        context_parts = []
        if component_arch:
            context_parts.append(f"FRONTEND COMPONENT ARCHITECTURE:\n\n{component_arch}")
        if component_plan:
            context_parts.append(f"FRONTEND IMPLEMENTATION PLAN:\n\n{component_plan}")
        if domain_parents:
            context_parts.append(f"DOMAIN PARENT ARCHITECTURES:\n\n{domain_parents}")

        messages = [
            {"role": "system", "content": self.full_system_message},
            {
                "role": "user",
                "content": "\n\n---\n\n".join(context_parts)
                + f"\n\nFRONTEND COMPONENT: {component_key}\n\n"
                "Generate the code for this frontend component.",
            },
        ]
        return self._inject_feedback(
            messages,
            human_notes,
            current_content,
            upstream_changes,
        )
