from backend.pipeline.prompts.base import PromptTemplate


class HighLevelPlanPrompt(PromptTemplate):
    def build(
        self,
        input_artifacts,
        component_key=None,
        human_notes=None,
        current_content=None,
        upstream_changes=None,
    ):
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
                + "\n\nProduce a high-level delivery plan.",
            },
        ]
        return self._inject_feedback(messages, human_notes)
