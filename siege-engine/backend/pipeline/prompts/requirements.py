from backend.pipeline.prompts.base import PromptTemplate


class SystemRequirementsPrompt(PromptTemplate):
    def build(
        self,
        input_artifacts,
        component_key=None,
        feedback=None,
        human_notes=None,
        prompt_config=None,
    ):
        if prompt_config:
            return self._build_from_config(
                input_artifacts, component_key, feedback, human_notes, prompt_config
            )

        project_doc = input_artifacts.get("project_doc", "")
        messages = [
            {"role": "system", "content": self.full_system_message},
            {"role": "user", "content": f"PROJECT DOCUMENT:\n\n{project_doc}"},
        ]
        return self._inject_feedback(messages, feedback, human_notes)


