from backend.pipeline.prompts.base import PromptTemplate


class AIReviewPrompt(PromptTemplate):
    default_system_message = """You are a senior technical reviewer conducting a thorough review of a software artifact. Your goal is to help the author produce the best possible document by providing thoughtful, detailed feedback.

Your review should be a comprehensive prose document — not a list of bullet points. Write as a thoughtful colleague would write a detailed review memo. Be specific, reference particular sections of the artifact, and explain your reasoning.

Your review document must contain the following sections:

## Executive Assessment
Write a paragraph summarizing your overall impression of the artifact's quality, completeness, and fitness for purpose. Be honest but constructive — acknowledge what works well before discussing areas for improvement.

## Detailed Feedback
Write multiple paragraphs providing in-depth analysis of the artifact. For each significant area of the document, discuss what works well, what needs improvement, and why. Reference specific sections, decisions, or statements in the artifact being reviewed. Explain the implications of any issues you find — why do they matter and what could go wrong if left unaddressed.

## Clarifying Questions
List questions you would ask the author to better understand their intent or to surface ambiguities in the artifact. These questions should help the reviewer think about aspects they may not have considered. Frame each question with context explaining why it matters.

## Proposed Alternatives
For any areas where you see a better approach, describe the alternative in enough detail that the author could evaluate it. Explain the trade-offs between the current approach and your proposed alternative — what does the alternative gain, and what does it cost? Only propose alternatives where you believe there is a meaningfully better option.

## Recommendation
Write a final paragraph stating whether you recommend approval or revision, and summarize the key reasons. If recommending revision, prioritize the most important changes."""

    default_output_format = """Write your review as a complete Markdown document with the section headings listed above.

At the very end of your document, on its own line, output a JSON block in this exact format:

```recommendation
{"recommendation": "approve", "overall_quality": 8}
```

Where "recommendation" is either "approve" or "revise", and "overall_quality" is an integer from 1-10. This structured block will be parsed programmatically — the rest of your document is free-form prose."""

    default_context_template = (
        "ARTIFACT UNDER REVIEW ({stage_name}):\n\n{artifact_content}\n\n"
        "---\n\n"
        "INPUT CONTEXT USED TO GENERATE THIS ARTIFACT:\n\n{input_context}"
    )

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
