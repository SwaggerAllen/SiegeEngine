from backend.pipeline.prompts.base import PromptTemplate


class ArchitecturePrompt(PromptTemplate):
    default_system_message = """You are a senior software architect.
Given a project document, produce a comprehensive system architecture document."""

    default_output_format = """Your output MUST include:
1. System overview and goals
2. Component breakdown (list each component with key, name, description, responsibilities)
3. Data flow between components
4. Technology choices with justifications
5. Non-functional requirements (scalability, security, etc.)

IMPORTANT: Output the component list in a JSON code block tagged ```components
with format: [{"key": "comp_key", "name": "Component Name", "description": "..."}]
This list will be used for downstream parallel processing of each component."""

    default_context_template = "PROJECT DOCUMENT:\n\n{input_artifacts}"

    def build(self, input_artifacts, component_key=None, feedback=None, human_notes=None, prompt_config=None):
        if prompt_config:
            return self._build_from_config(input_artifacts, component_key, feedback, human_notes, prompt_config)

        project_doc = input_artifacts.get("project_doc", "")
        messages = [
            {"role": "system", "content": self.full_system_message},
            {"role": "user", "content": f"PROJECT DOCUMENT:\n\n{project_doc}"},
        ]
        return self._inject_feedback(messages, feedback, human_notes)
