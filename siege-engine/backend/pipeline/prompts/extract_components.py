from backend.pipeline.prompts.base import PromptTemplate


class ExtractComponentsPrompt(PromptTemplate):

    def build(self, input_artifacts, component_key=None, feedback=None, human_notes=None, prompt_config=None):
        if prompt_config:
            return self._build_from_config(input_artifacts, component_key, feedback, human_notes, prompt_config)

        system_reqs = input_artifacts.get("system_requirements", "")
        system_arch = input_artifacts.get("system_architecture", "")

        context_parts = []
        if system_reqs:
            context_parts.append(f"SYSTEM REQUIREMENTS:\n\n{system_reqs}")
        if system_arch:
            context_parts.append(f"SYSTEM ARCHITECTURE:\n\n{system_arch}")

        messages = [
            {"role": "system", "content": self.full_system_message},
            {
                "role": "user",
                "content": "\n\n---\n\n".join(context_parts)
                + "\n\nIdentify the components and their inter-dependencies.",
            },
        ]
        return self._inject_feedback(messages, feedback, human_notes)
