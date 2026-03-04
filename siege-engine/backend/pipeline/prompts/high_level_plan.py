from backend.pipeline.prompts.base import PromptTemplate


class HighLevelPlanPrompt(PromptTemplate):
    default_system_message = """You are a senior engineering manager and project planner.
Given a system architecture and component architectures, produce a high-level delivery plan."""

    default_output_format = """Your output MUST include:
1. Implementation phases (ordered by dependency and priority)
2. Component delivery order with justification
3. Integration milestones
4. Risk assessment and mitigation strategies
5. Key technical decisions to make during implementation
6. Testing strategy overview"""

    default_context_template = (
        "SYSTEM ARCHITECTURE:\n\n{input_artifacts}\n\n"
        "Produce a high-level delivery plan."
    )

    def build(self, input_artifacts, component_key=None, feedback=None, human_notes=None, prompt_config=None):
        if prompt_config:
            return self._build_from_config(input_artifacts, component_key, feedback, human_notes, prompt_config)

        system_arch = input_artifacts.get("system_architecture", "")
        component_archs = input_artifacts.get("component_architectures", "")
        messages = [
            {"role": "system", "content": self.full_system_message},
            {
                "role": "user",
                "content": f"SYSTEM ARCHITECTURE:\n\n{system_arch}\n\n"
                f"COMPONENT ARCHITECTURES:\n\n{component_archs}\n\n"
                "Produce a high-level delivery plan.",
            },
        ]
        return self._inject_feedback(messages, feedback, human_notes)
