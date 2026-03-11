from backend.pipeline.prompts.base import PromptTemplate


class ArchitecturePrompt(PromptTemplate):

    def build(self, input_artifacts, component_key=None, feedback=None, human_notes=None, prompt_config=None):
        if prompt_config:
            return self._build_from_config(input_artifacts, component_key, feedback, human_notes, prompt_config)

        system_reqs = input_artifacts.get("system_requirements", "")
        messages = [
            {"role": "system", "content": self.full_system_message},
            {"role": "user", "content": f"SYSTEM REQUIREMENTS:\n\n{system_reqs}"},
        ]
        return self._inject_feedback(messages, feedback, human_notes)
