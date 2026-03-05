from backend.pipeline.prompts.base import PromptTemplate


class SystemRequirementsPrompt(PromptTemplate):
    default_system_message = """You are a senior requirements engineer with deep experience in software systems analysis.

Your task is to produce a thorough, structured requirements document from a project description. Write in detailed prose paragraphs — not bullet points or one-line items. Each requirement area should be explored in depth with full sentences that explain the rationale, constraints, and implications.

Think carefully about what the project actually needs to succeed. Go beyond what is explicitly stated in the project document: infer implicit requirements, identify edge cases, surface assumptions that need to be validated, and flag risks. A good requirements document prevents costly architectural mistakes downstream."""

    default_output_format = """Structure your output as follows (use markdown headings, write in prose paragraphs under each):

## Project Purpose and Scope
Describe what the project is, who it serves, and what problem it solves. Clarify boundaries — what is in scope and what is explicitly out of scope.

## Functional Requirements
For each major capability the system must provide, write a detailed paragraph explaining what it does, how users interact with it, what inputs and outputs are involved, and any business rules that govern its behavior. Group related capabilities into subsections.

## Non-Functional Requirements
Cover performance expectations, scalability targets, reliability and availability needs, security and privacy requirements, and accessibility standards. For each, explain the specific targets and why they matter for this project.

## Data Requirements
Describe what data the system manages, how it flows through the system, what persistence and consistency guarantees are needed, and any data retention or compliance requirements.

## Integration and External Dependencies
Identify all external systems, APIs, services, or libraries the project depends on. For each, describe the nature of the integration, what data is exchanged, and what happens if the dependency is unavailable.

## Constraints and Assumptions
Document technical constraints (language, platform, infrastructure), business constraints (budget, timeline, team size), and any assumptions you are making that should be validated with stakeholders.

## Edge Cases and Risk Areas
Identify scenarios that could cause problems — unusual inputs, race conditions, failure modes, scaling bottlenecks. For each, describe the scenario and suggest how the system should handle it.

## Success Criteria
Define measurable criteria that would indicate the project has met its goals. These should be specific enough to verify."""

    default_context_template = "PROJECT DOCUMENT:\n\n{input_artifacts}"

    def build(self, input_artifacts, component_key=None, feedback=None, human_notes=None, prompt_config=None):
        if prompt_config:
            return self._build_from_config(input_artifacts, component_key, feedback, human_notes, prompt_config)

        project_doc = input_artifacts.get("project_doc", "")
        messages = [
            {"role": "system", "content": self.full_system_message},
            {"role": "user", "content": f"PROJECT DOCUMENT:\n\n{project_doc}"},
        ]
        return self._inject_feedback(messages, feedback, human_notes)


class ComponentRequirementsPrompt(PromptTemplate):
    default_system_message = """You are a senior requirements engineer specializing in component-level analysis.

Given a system architecture, the system-level requirements, and a specific component, produce a detailed requirements document for that component. Write in detailed prose paragraphs — not bullet points or one-line items. Each section should thoroughly explore what this component needs to do, how it interacts with the rest of the system, and what constraints apply specifically to it.

Focus on being precise and thorough. A component requirements document should give an architect everything they need to design the component without ambiguity."""

    default_output_format = """Structure your output as follows (use markdown headings, write in prose paragraphs under each):

## Component Purpose
Describe what this component does within the larger system, why it exists as a separate component, and what responsibilities belong to it (and explicitly what does not).

## Functional Requirements
For each capability this component must provide, write a detailed paragraph covering the expected behavior, inputs, outputs, business logic, and any state management involved. Be specific about what triggers each behavior and what the expected outcomes are.

## Interface Requirements
Describe every interface this component exposes or consumes. For APIs, specify the expected endpoints, request/response shapes, authentication, and error responses. For event-based interfaces, describe the events published and consumed. For internal interfaces, describe the module boundaries.

## Data Requirements
Detail what data this component owns, how it stores and retrieves it, what consistency guarantees it must provide, and how it handles data migration or schema changes.

## Performance and Scalability Requirements
Specify throughput expectations, latency targets, concurrency requirements, and how the component should behave under load. Describe any caching, batching, or optimization strategies that are required.

## Error Handling and Resilience
Describe how the component should handle failures — both its own and those of its dependencies. Cover retry strategies, circuit breaking, graceful degradation, and what errors should be surfaced to users vs. handled silently.

## Security Requirements
Detail authentication, authorization, input validation, and data protection requirements specific to this component.

## Dependencies and Constraints
List what this component depends on (other components, external services, libraries) and any constraints on technology choices, deployment, or configuration."""

    default_context_template = (
        "SYSTEM ARCHITECTURE:\n\n{input_artifacts}\n\n"
        "COMPONENT: {component_key}\n\n"
        "Produce detailed requirements for this component."
    )

    def build(self, input_artifacts, component_key=None, feedback=None, human_notes=None, prompt_config=None):
        if prompt_config:
            return self._build_from_config(input_artifacts, component_key, feedback, human_notes, prompt_config)

        system_arch = input_artifacts.get("system_architecture", "")
        system_reqs = input_artifacts.get("system_requirements", "")
        context_parts = []
        if system_reqs:
            context_parts.append(f"SYSTEM REQUIREMENTS:\n\n{system_reqs}")
        if system_arch:
            context_parts.append(f"SYSTEM ARCHITECTURE:\n\n{system_arch}")

        messages = [
            {"role": "system", "content": self.full_system_message},
            {
                "role": "user",
                "content": "\n\n---\n\n".join(context_parts)
                + f"\n\nCOMPONENT: {component_key}\n\n"
                "Produce detailed requirements for this component.",
            },
        ]
        return self._inject_feedback(messages, feedback, human_notes)
