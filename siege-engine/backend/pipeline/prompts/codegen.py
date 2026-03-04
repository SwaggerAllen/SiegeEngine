from backend.pipeline.prompts.base import PromptTemplate


class CodeGenPrompt(PromptTemplate):
    default_system_message = """You are a senior software engineer generating production-quality code.
Given a component implementation plan and architecture, produce the code files.

Requirements:
1. Generate complete, runnable code (not pseudocode or stubs)
2. Follow the language's idiomatic conventions
3. Include proper error handling
4. Add brief inline comments for complex logic
5. Include module/function docstrings"""

    default_output_format = """Output each file in a code block with the file path as the info string:
```filepath:path/to/file.ext
<code content>
```

Generate all files specified in the implementation plan."""

    default_context_template = (
        "COMPONENT ARCHITECTURE:\n\n{input_artifacts}\n\n"
        "COMPONENT: {component_key}\n\n"
        "Generate the code for this component."
    )

    def build(self, input_artifacts, component_key=None, feedback=None, human_notes=None, prompt_config=None):
        if prompt_config:
            return self._build_from_config(input_artifacts, component_key, feedback, human_notes, prompt_config)

        component_plan = input_artifacts.get("component_plans", "")
        component_arch = input_artifacts.get("component_architectures", "")
        messages = [
            {"role": "system", "content": self.full_system_message},
            {
                "role": "user",
                "content": f"COMPONENT ARCHITECTURE:\n\n{component_arch}\n\n"
                f"IMPLEMENTATION PLAN:\n\n{component_plan}\n\n"
                f"COMPONENT: {component_key}\n\n"
                "Generate the code for this component.",
            },
        ]
        return self._inject_feedback(messages, feedback, human_notes)
