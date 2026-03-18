import logging

from backend.cli.extractor import extractor
from backend.cli.manager import cli_manager
from backend.config import settings
from backend.models import StageDefinition
from backend.pipeline.prompts import PROMPT_REGISTRY

logger = logging.getLogger(__name__)

# Stage-specific review guidance injected into the system message.
# Keyed by stage_key from the StageDefinition.
STAGE_REVIEW_GUIDANCE: dict[str, str] = {
    "system_architecture": (
        "## Architecture-Specific Review Focus\n"
        "\n"
        "Pay special attention to **component boundaries and"
        " decomposition**. This is one of the most consequential"
        " decisions in the architecture and should receive"
        " detailed scrutiny:\n"
        "\n"
        "- **Are there too many components?** Over-decomposed"
        " architectures create unnecessary inter-service"
        " communication, deployment complexity, and cognitive"
        " overhead. If two components always change together,"
        " are always deployed together, or share most of their"
        " data, they should probably be one component. Flag any"
        " components that seem to exist for organizational"
        " purity rather than genuine technical need.\n"
        "\n"
        "- **Are there too few components?** Under-decomposed"
        " architectures create monoliths that are hard to scale,"
        " test, and maintain independently. If a single component"
        " handles multiple unrelated domains, has mixed scaling"
        " requirements, or would benefit from independent"
        " deployment, it should probably be split. Flag any"
        " components that seem to be doing too much.\n"
        "\n"
        "- **Are the boundaries in the right places?** Good"
        " boundaries follow domain boundaries, minimize"
        " cross-component coupling, and maximize internal"
        " cohesion. Each component should have a clear, singular"
        " responsibility. Flag boundaries that cut across domains"
        " or create excessive cross-component dependencies.\n"
        "\n"
        "- **Is the component count justified?** For each"
        " component, ask: does this need to be separate? What is"
        " gained by the separation? What is the cost? The right"
        " number of components is the minimum needed to achieve"
        " genuine separation of concerns — no fewer, no more.\n"
        "\n"
        "When evaluating, consider the specific functional"
        " requirements and the realistic scale of the system."
        " A small CRUD app with 15 microservices is"
        " over-decomposed; a complex platform with 3 monolithic"
        " services is under-decomposed. Ground your assessment"
        " in the actual requirements, not in abstract principles."
    ),
}


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

    # Inject stage-specific review guidance
    stage_guidance = STAGE_REVIEW_GUIDANCE.get(stage_def.stage_key)
    if stage_guidance and system_msg:
        system_msg = f"{system_msg}\n\n{stage_guidance}"

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
