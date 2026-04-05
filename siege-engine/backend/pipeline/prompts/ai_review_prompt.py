from backend.pipeline.prompts.base import PromptTemplate


class AIReviewPrompt(PromptTemplate):
    def build(
        self,
        input_artifacts,
        component_key=None,
        human_notes=None,
        current_content=None,
        upstream_changes=None,
    ):
        # Extract special keys from input_artifacts
        # Make a copy so we don't mutate the original
        artifacts = dict(input_artifacts)
        artifact_content = artifacts.pop("artifact_content", "")
        stage_name = artifacts.pop("stage_name", "Artifact")
        input_context = "\n\n".join(f"### {k}\n{v}" for k, v in artifacts.items())

        messages = [
            {"role": "system", "content": self.full_system_message},
            {
                "role": "user",
                "content": (
                    f"ARTIFACT UNDER REVIEW ({stage_name}):\n\n"
                    f"{artifact_content}\n\n"
                    f"---\n\nINPUT CONTEXT USED TO GENERATE "
                    f"THIS ARTIFACT:\n\n{input_context[:4000]}"
                ),
            },
        ]
        return messages
