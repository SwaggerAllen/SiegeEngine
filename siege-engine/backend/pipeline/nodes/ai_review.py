import logging

from backend.cli.extractor import extractor
from backend.cli.manager import cli_manager
from backend.config import settings
from backend.models import StageDefinition
from backend.pipeline.prompts import PROMPT_REGISTRY

logger = logging.getLogger(__name__)


async def ai_review(
    stage_def: StageDefinition,
    generated_content: str,
    input_artifacts: dict[str, str],
    review_prompt_overrides: dict | None = None,
) -> dict:
    """
    Run AI review on generated content via CLI.
    Returns structured feedback with a full review document.
    """
    prompt_class = PROMPT_REGISTRY["ai_review"]
    prompt = prompt_class()

    # Build the input dict for the review prompt
    review_inputs = {
        **input_artifacts,
        "artifact_content": generated_content,
        "stage_name": stage_def.display_name,
    }

    # Use overrides if provided (from PipelineConfig.review_prompt_overrides)
    prompt_config_dict = None
    if review_prompt_overrides:
        prompt_config_dict = {
            "system_message": review_prompt_overrides.get("system_message"),
            "output_format_instructions": review_prompt_overrides.get("output_format_instructions"),
            "context_template": review_prompt_overrides.get("context_template"),
        }

    messages = prompt.build(
        input_artifacts=review_inputs,
        prompt_config=prompt_config_dict,
    )

    # Model selection: from overrides, fall back to defaults
    model_name = (review_prompt_overrides or {}).get("model") or "claude-sonnet-4-20250514"

    # Extract system and user messages for CLI
    system_msg = next((m["content"] for m in messages if m["role"] == "system"), None)
    user_msgs = [m["content"] for m in messages if m["role"] == "user"]
    user_prompt = "\n\n".join(user_msgs)

    logger.info("CLI ai_review: model=%s", model_name)
    content = await cli_manager.generate(
        prompt=user_prompt,
        system_prompt=system_msg,
        model=model_name,
        tools="",  # No tools needed for review — just prompt → response
        timeout=settings.cli_timeout_document,
    )

    # Extract recommendation from the review document
    recommendation = await extractor.extract_recommendation(content)

    return {
        "document": content,
        "overall_quality": recommendation.get("overall_quality", 5),
        "recommendation": recommendation.get("recommendation", "approve"),
    }
