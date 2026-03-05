from backend.pipeline.prompts.base import PromptTemplate


class CodeReviewPrompt(PromptTemplate):
    default_system_message = """You are a senior code reviewer performing a thorough review of generated code.

Your task:
1. Review all code files in this project for correctness, quality, and adherence to the architecture
2. Fix any bugs, security issues, or code quality problems you find
3. Run tests if a test framework is configured, and fix any failures
4. Ensure the code follows the component plan and architecture documents
5. Iterate until the code is production-ready

After completing your review and fixes, write a summary document with:
- What was reviewed
- Issues found and fixed
- Remaining concerns (if any)
- Final quality assessment

End your document with a recommendation block:
```recommendation
{"recommendation": "approve", "overall_quality": 8}
```

Use "approve" if the code is production-ready, "revise" if it needs more work."""

    default_output_format = ""

    default_context_template = (
        "COMPONENT ARCHITECTURE:\n\n{component_architectures}\n\n"
        "COMPONENT PLAN:\n\n{component_plans}\n\n"
        "COMPONENT: {component_key}\n\n"
        "Review the code for this component in the project directory. "
        "Fix any issues you find, run tests, and iterate until satisfied."
    )

    def build(self, input_artifacts, component_key=None, feedback=None, human_notes=None, prompt_config=None):
        if prompt_config:
            return self._build_from_config(input_artifacts, component_key, feedback, human_notes, prompt_config)

        component_plan = input_artifacts.get("component_plans", "")
        component_arch = input_artifacts.get("component_architectures", "")
        code_content = input_artifacts.get("code_generation", "")

        messages = [
            {"role": "system", "content": self.default_system_message},
            {
                "role": "user",
                "content": f"COMPONENT ARCHITECTURE:\n\n{component_arch}\n\n"
                f"IMPLEMENTATION PLAN:\n\n{component_plan}\n\n"
                f"GENERATED CODE:\n\n{code_content}\n\n"
                f"COMPONENT: {component_key}\n\n"
                "Review the code for this component. Fix any issues, run tests, "
                "and iterate until the code is production-ready.",
            },
        ]
        return self._inject_feedback(messages, feedback, human_notes)
