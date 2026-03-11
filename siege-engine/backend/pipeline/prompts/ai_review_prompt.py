from backend.pipeline.prompts.base import PromptTemplate


class AIReviewPrompt(PromptTemplate):

    def build(self, input_artifacts, component_key=None, feedback=None, human_notes=None, prompt_config=None):
        # Extract special keys from input_artifacts
        # Make a copy so we don't mutate the original
        artifacts = dict(input_artifacts)
        artifact_content = artifacts.pop("artifact_content", "")
        stage_name = artifacts.pop("stage_name", "Artifact")

        if prompt_config:
            # Re-inject the formatted content as input_artifacts for _build_from_config
            # The context template uses {artifact_content}, {stage_name}, and {input_context}
            formatted_context = "\n\n".join(
                f"### {k}\n{v}" for k, v in artifacts.items()
            )
            # Build from config with special placeholder handling
            system_msg = prompt_config.get("system_message") or self.default_system_message
            output_fmt = prompt_config.get("output_format_instructions") or self.default_output_format
            ctx_template = prompt_config.get("context_template") or self.default_context_template

            if output_fmt:
                system_msg = f"{system_msg}\n\n{output_fmt}"

            system_msg = f"{system_msg}\n\n{self.formatting_guidance}"

            user_content = ctx_template.replace("{artifact_content}", artifact_content)
            user_content = user_content.replace("{stage_name}", stage_name)
            user_content = user_content.replace("{input_context}", formatted_context[:4000])

            messages = [
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_content},
            ]
            return messages

        # Default build
        input_context = "\n\n".join(
            f"### {k}\n{v}" for k, v in artifacts.items()
        )

        messages = [
            {"role": "system", "content": self.full_system_message},
            {
                "role": "user",
                "content": (
                    f"ARTIFACT UNDER REVIEW ({stage_name}):\n\n{artifact_content}\n\n"
                    f"---\n\nINPUT CONTEXT USED TO GENERATE THIS ARTIFACT:\n\n{input_context[:4000]}"
                ),
            },
        ]
        return messages
