import json

from langchain_anthropic import ChatAnthropic

from backend.models import StageDefinition
from backend.pipeline.llm_limiter import rate_limited_invoke


async def ai_review(
    stage_def: StageDefinition,
    generated_content: str,
    input_artifacts: dict[str, str],
) -> dict:
    """
    Run AI review on generated content. Returns structured feedback.
    """
    review_prompt = [
        {
            "role": "system",
            "content": """You are a senior technical reviewer. Review the following artifact
for completeness, consistency with inputs, quality, and correctness.

Provide structured feedback as JSON with keys:
- overall_quality: 1-10
- issues: list of {"severity": "high"|"medium"|"low", "description": "...", "suggestion": "..."}
- strengths: list of strings
- recommendation: "approve" | "revise"

Return ONLY the JSON object.""",
        },
        {
            "role": "user",
            "content": f"ARTIFACT TO REVIEW ({stage_def.display_name}):\n\n{generated_content}\n\n"
            f"INPUT CONTEXT:\n\n{json.dumps(input_artifacts)[:4000]}",
        },
    ]

    model = ChatAnthropic(
        model="claude-sonnet-4-20250514",
        temperature=0.1,
        max_tokens=4096,
    )
    response = await rate_limited_invoke(model, review_prompt)

    # Parse JSON from response
    try:
        # Try to extract JSON from the response
        content = response.content
        # Handle markdown code block wrapping
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0]
        elif "```" in content:
            content = content.split("```")[1].split("```")[0]
        return json.loads(content)
    except (json.JSONDecodeError, IndexError):
        return {
            "overall_quality": 5,
            "issues": [],
            "strengths": [],
            "recommendation": "approve",
            "raw_feedback": response.content,
        }
