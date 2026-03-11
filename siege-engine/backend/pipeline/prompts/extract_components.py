from backend.pipeline.prompts.base import PromptTemplate


class ExtractComponentsPrompt(PromptTemplate):

    def build(self, input_artifacts, component_key=None, feedback=None, human_notes=None, prompt_config=None):
        if prompt_config:
            return self._build_from_config(input_artifacts, component_key, feedback, human_notes, prompt_config)

        system_arch = input_artifacts.get("system_architecture", "")
        high_level_plan = input_artifacts.get("high_level_plan", "")

        context_parts = []
        if system_arch:
            context_parts.append(f"SYSTEM ARCHITECTURE:\n\n{system_arch}")
        if high_level_plan:
            context_parts.append(f"HIGH-LEVEL PLAN:\n\n{high_level_plan}")

        messages = [
            {"role": "system", "content": self.full_system_message},
            {
                "role": "user",
                "content": "\n\n---\n\n".join(context_parts)
                + "\n\nIdentify the components and their inter-dependencies.",
            },
        ]
        return self._inject_feedback(messages, feedback, human_notes)
