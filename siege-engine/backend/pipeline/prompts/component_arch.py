from backend.pipeline.prompts.base import PromptTemplate


class ComponentArchPrompt(PromptTemplate):
    default_system_message = """You are a senior software architect specializing in component design.
Given a system architecture and a specific component, produce a detailed component architecture."""

    default_output_format = """Your output MUST include:
1. Component purpose and responsibilities
2. Internal module breakdown
3. Public API / interfaces
4. Data models specific to this component
5. Dependencies on other components
6. Error handling strategy
7. Testing considerations"""

    default_context_template = (
        "SYSTEM ARCHITECTURE:\n\n{input_artifacts}\n\n"
        "COMPONENT TO DESIGN: {component_key}\n\n"
        "Produce a detailed architecture for this component."
    )

    def build(self, input_artifacts, component_key=None, feedback=None, human_notes=None, prompt_config=None):
        if prompt_config:
            return self._build_from_config(input_artifacts, component_key, feedback, human_notes, prompt_config)

        system_arch = input_artifacts.get("system_architecture", "")
        messages = [
            {"role": "system", "content": self.full_system_message},
            {
                "role": "user",
                "content": f"SYSTEM ARCHITECTURE:\n\n{system_arch}\n\n"
                f"COMPONENT TO DESIGN: {component_key}\n\n"
                "Produce a detailed architecture for this component.",
            },
        ]
        return self._inject_feedback(messages, feedback, human_notes)
