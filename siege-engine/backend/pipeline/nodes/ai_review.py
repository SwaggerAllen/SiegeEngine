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
    "feature_expansion": (
        "## Feature Expansion Review Focus\n"
        "\n"
        "This document should enumerate EVERY feature the system needs — both explicit\n"
        "and implied. Flag any of these issues:\n"
        "\n"
        "- **Missing cross-cutting features**: Features that span multiple components\n"
        "  (file uploads, notifications, search, caching) are commonly missed. Check that\n"
        "  the expansion surfaces these and describes which system boundaries they cross.\n"
        "\n"
        "- **Missing operational features**: Health checks, admin tools, monitoring,\n"
        "  backup/restore, configuration management. A production system needs these.\n"
        "\n"
        "- **Missing implicit features**: Pagination, data validation, error responses,\n"
        "  rate limiting, accessibility. These are rarely in specifications but always needed.\n"
        "\n"
        "- **Premature solutionizing**: The feature expansion should describe WHAT is needed,\n"
        "  not HOW to build it. Architecture decisions belong to the next stage.\n"
        "\n"
        "- **Insufficient detail on cross-component features**: For features that touch\n"
        "  multiple components, the expansion should explain what each component contributes.\n"
        "  Vague cross-cutting features create architectural blind spots."
    ),
    "system_requirements": (
        "## Requirements-Specific Review Focus\n"
        "\n"
        "This document should capture WHAT the system needs to do, not HOW to build it.\n"
        "Flag any of these anti-patterns:\n"
        "\n"
        "- **Premature solutionizing**: References to specific technologies, frameworks,\n"
        '  databases, or architectural patterns. "Use PostgreSQL" is architecture, not a\n'
        '  requirement. "Persistent relational storage with ACID guarantees" is a requirement.\n'
        "\n"
        "- **Architecture leakage**: Component breakdowns, service boundaries, API designs,\n"
        "  or deployment topologies. The requirements should be satisfiable by multiple\n"
        "  possible architectures.\n"
        "\n"
        '- **Vague requirements**: "The system should be fast" or "handle many users."\n'
        "  Requirements need specificity: latency targets, throughput numbers, user counts.\n"
        "\n"
        "- **Missing requirements**: Check that functional, non-functional, data, integration,\n"
        "  security, and edge-case requirements are all addressed. Gaps here cascade into\n"
        "  architectural blind spots downstream."
    ),
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
    "extract_components": (
        "## Component Extraction Review Focus\n"
        "\n"
        "- **Over-decomposition**: Are there components that always change together, share\n"
        "  most of their data, or have trivial interfaces? They should probably be merged.\n"
        "  Each additional component = 2-4 more documents and a more complex dependency graph.\n"
        "\n"
        "- **Under-decomposition**: Are there components handling multiple unrelated domains\n"
        "  or with mixed scaling requirements? They should probably be split.\n"
        "\n"
        "- **Dependency graph quality**: Are there near-circular dependency patterns?\n"
        "  Components with excessive fan-in or fan-out? The graph should be a clean DAG\n"
        "  with clear layering.\n"
        "\n"
        "- **Buildable units**: Can each component be implemented and tested independently\n"
        "  once its dependencies are built? If not, the boundaries may be wrong."
    ),
    "component_architectures": (
        "## Component Architecture Review Focus\n"
        "\n"
        "- **Component skeleton**: Does the architecture include a component_skeleton covering\n"
        "  directory structure, configuration, dependency setup, shared utilities, and base\n"
        "  classes? The skeleton should be treated as a first-class architectural element.\n"
        "\n"
        "- **Honors external contracts**: Does the design implement all interfaces specified\n"
        "  by the system architecture? Are there deviations from the agreed contracts?\n"
        "\n"
        "- **Appropriate internal complexity**: Is the internal module breakdown justified by\n"
        "  the component's scope, or is it over-engineered for a simple component?\n"
        "\n"
        "- **Data model completeness**: Are all data models, schemas, and relationships\n"
        "  defined with enough detail for implementation?\n"
        "\n"
        "- **Testability**: Can the proposed architecture be meaningfully unit-tested and\n"
        "  integration-tested as described?\n"
        "\n"
        "- **Decomposition-ready**: Are the internal module boundaries clear enough that the\n"
        "  component could be further decomposed into sub-components if needed?"
    ),
    "component_plans": (
        "## Implementation Plan Review Focus\n"
        "\n"
        "- **Completeness**: Does the file inventory cover everything needed to implement\n"
        "  the component architecture? Are there missing files, missing tests, or missing\n"
        "  integration points?\n"
        "\n"
        "- **Consistency with architecture**: Does the plan faithfully translate the\n"
        "  architecture into files, or does it introduce architectural deviations?\n"
        "\n"
        "- **Build order correctness**: Can each step actually be implemented and tested\n"
        "  after its predecessors complete?\n"
        "\n"
        "- **Test coverage**: Are there test cases for the important behaviors, edge cases,\n"
        "  and error paths?"
    ),
    "extract_sub_components": (
        "## Sub-Component Extraction Review Focus\n"
        "\n"
        "- **Unnecessary decomposition**: Is this component actually complex enough to warrant\n"
        "  sub-components? Simple components (thin wrappers, CRUD services, single-concern\n"
        "  modules) should NOT be decomposed. Each sub-component adds an architecture + plan\n"
        "  cycle, so the complexity must justify the overhead.\n"
        "\n"
        "- **Boundary clarity**: Are the boundaries between sub-components sharp and\n"
        "  unambiguous? Can each sub-component be implemented and tested independently?\n"
        "  Overlapping responsibilities between sub-components will cause integration bugs.\n"
        "\n"
        "- **Consistency with parent**: Do the sub-components together cover all the parent\n"
        "  component's responsibilities without gaps or overlaps?\n"
        "\n"
        "- **Dependency graph**: Is the sub-component dependency graph a clean DAG? Circular\n"
        "  or excessive dependencies between sub-components suggest the decomposition is wrong."
    ),
    "sub_component_architectures": (
        "## Sub-Component Architecture Review Focus\n"
        "\n"
        "- **Component skeleton**: Does the architecture include a component_skeleton covering\n"
        "  the sub-component's directory structure, configuration, and shared utilities?\n"
        "\n"
        "- **Honors sibling interfaces**: Does the design implement all interfaces specified\n"
        "  in the sub-component extraction? Are there deviations from the agreed contracts\n"
        "  with siblings?\n"
        "\n"
        "- **Parent conventions**: Does the design stay consistent with the parent component's\n"
        "  framework, database, and coding conventions? Introducing competing tech within a\n"
        "  parent component creates integration headaches.\n"
        "\n"
        "- **Appropriate complexity**: Is the internal module breakdown proportional to the\n"
        "  sub-component's scope? A sub-component should be simpler than its parent — if it\n"
        "  looks as complex as a full component, the decomposition may be wrong.\n"
        "\n"
        "- **Testability in isolation**: Can this sub-component be tested independently with\n"
        "  siblings mocked at the interface boundaries?"
    ),
    "sub_component_plans": (
        "## Sub-Component Implementation Plan Review Focus\n"
        "\n"
        "- **Completeness**: Does the file inventory cover everything in the sub-component\n"
        "  architecture? Missing files or missing tests?\n"
        "\n"
        "- **Integration with siblings and parent**: Are import paths, shared utilities, and\n"
        "  parent-provided infrastructure correctly referenced? The plan should make it clear\n"
        "  how this sub-component plugs into its parent.\n"
        "\n"
        "- **Build order**: Can each step be implemented after its predecessors? Are\n"
        "  dependencies on sibling sub-components properly sequenced?\n"
        "\n"
        "- **Test plan**: Are there tests covering both this sub-component's own behavior AND\n"
        "  its integration with sibling interfaces?"
    ),
    "code_generation": (
        "## Code Generation Review Focus\n"
        "\n"
        "- **Plan adherence**: Does the generated code match the implementation plan? Are all\n"
        "  files from the plan present? Are there extra files not in the plan?\n"
        "\n"
        "- **Architecture consistency**: Does the code implement the component architecture\n"
        "  as designed? Are interfaces, data models, and module boundaries correct?\n"
        "\n"
        "- **Code quality**: Is the code production-ready? Check for proper error handling,\n"
        "  input validation, logging, and adherence to language idioms.\n"
        "\n"
        "- **Security**: Are there any security vulnerabilities (injection, XSS, auth bypass,\n"
        "  hardcoded secrets, etc.)?"
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
