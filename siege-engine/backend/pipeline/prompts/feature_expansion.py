from backend.pipeline.prompts.base import PromptTemplate


class FeatureExpansionPrompt(PromptTemplate):
    def build(
        self,
        input_artifacts,
        component_key=None,
        human_notes=None,
        current_content=None,
        upstream_changes=None,
    ):
        project_doc = input_artifacts.get("project_doc", "")
        input_docs = input_artifacts.get("input_documents", "")
        user_content = f"PROJECT DOCUMENT:\n\n{project_doc}"
        if input_docs:
            user_content += f"\n\n---\n\nINPUT DOCUMENTS:\n\n{input_docs}"
        messages = [
            {"role": "system", "content": self.full_system_message},
            {"role": "user", "content": user_content},
        ]
        return self._inject_feedback(
            messages,
            human_notes,
            current_content,
            upstream_changes,
        )
