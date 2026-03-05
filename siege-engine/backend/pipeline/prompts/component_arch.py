from backend.pipeline.prompts.base import PromptTemplate


class ComponentArchPrompt(PromptTemplate):
    default_system_message = """You are a senior software architect specializing in component-level design.

Given the component's requirements, the system architecture, and a specific component to design, produce a detailed component architecture document. Write in detailed prose paragraphs — not bullet points or terse one-liners. Each section should thoroughly explain the internal design, module structure, interfaces, and data models with enough depth that a developer could implement it without ambiguity."""

    default_output_format = """Structure your output as follows (use markdown headings, write in prose paragraphs under each):

## Component Purpose and Responsibilities
Describe what this component does, why it exists as a separate unit, and precisely what responsibilities it owns. Be explicit about what this component does NOT handle — boundary clarity prevents scope creep.

## Internal Module Breakdown
Describe the internal modules or layers within this component. For each module, explain its purpose, what code and logic it contains, and how it relates to the other modules. Explain the dependency direction between modules and why that structure was chosen.

## Public API and Interfaces
For each public interface (REST endpoints, gRPC services, event handlers, exported functions), provide a detailed description of the contract: what it accepts, what it returns, what errors it can produce, and what side effects it has. Explain the design rationale for the API shape.

## Data Models
Describe every data model this component owns — database tables, document schemas, in-memory structures. For each model, explain its fields, relationships, constraints, and how it evolves over time (migration strategy). Explain why this data belongs to this component and not elsewhere.

## Dependencies and Integration
Describe how this component communicates with other components and external services. For each dependency, explain what data is exchanged, what protocol is used, how failures are handled, and whether the coupling is tight or loose. Justify each dependency.

## Error Handling and Resilience
Describe the error handling strategy in detail: what errors can occur, how each is classified (retriable, fatal, degraded), how they are surfaced to callers or users, and what recovery mechanisms exist. Cover timeout policies, retry logic, and circuit-breaking behavior.

## Testing Strategy
Describe how this component should be tested: unit test boundaries, integration test scenarios, what should be mocked vs. tested against real dependencies, and any performance or load testing requirements."""

    default_context_template = (
        "{input_artifacts}\n\n"
        "COMPONENT TO DESIGN: {component_key}\n\n"
        "Produce a detailed architecture for this component."
    )

    def build(self, input_artifacts, component_key=None, feedback=None, human_notes=None, prompt_config=None):
        if prompt_config:
            return self._build_from_config(input_artifacts, component_key, feedback, human_notes, prompt_config)

        comp_reqs = input_artifacts.get("component_requirements", "")
        system_arch = input_artifacts.get("system_architecture", "")

        context_parts = []
        if comp_reqs:
            context_parts.append(f"COMPONENT REQUIREMENTS:\n\n{comp_reqs}")
        if system_arch:
            context_parts.append(f"SYSTEM ARCHITECTURE:\n\n{system_arch}")

        messages = [
            {"role": "system", "content": self.full_system_message},
            {
                "role": "user",
                "content": "\n\n---\n\n".join(context_parts)
                + f"\n\nCOMPONENT TO DESIGN: {component_key}\n\n"
                "Produce a detailed architecture for this component.",
            },
        ]
        return self._inject_feedback(messages, feedback, human_notes)
