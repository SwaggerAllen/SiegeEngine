from backend.pipeline.prompts.base import PromptTemplate

CONSOLIDATE_SYSTEM_PROMPT = """\
You are an expert technical editor. Your task is to consolidate this architecture \
document — making it significantly shorter while preserving every design decision, \
constraint, rationale ("why"), and structural detail.

Follow these consolidation rules:

1. Establish patterns once, reference thereafter. When the document explains a \
recurring convention, pattern, or mechanism in a dedicated section, that is the \
authoritative explanation. In all other sections, replace re-explanations with a \
brief reference (e.g., "following the [X] convention described above" or "using \
the standard [X] mechanism"). Do not re-describe how a pattern works after it has \
been fully explained once.

2. Eliminate duplicated content across sections. When the same technical detail \
appears in multiple sections (e.g., a mechanism described in a component section \
and again in a data flow or cross-cutting concerns section), keep the most complete \
version in whichever section it fits most naturally and reduce the other to a \
cross-reference or one-sentence summary.

3. Collapse repeated listings. When the same list of interfaces, functions, fields, \
or capabilities appears in multiple sections (e.g., listed where defined AND listed \
again where consumed), keep the authoritative list at the point of definition. At \
consumption sites, reference the list by name and location without re-enumerating \
every item.

4. Deduplicate dependency and integration descriptions. When a component's \
relationships are described both in a centralized dependency/integration section \
AND repeated in individual component sections, keep the centralized description \
and reduce per-component repetitions to a single sentence or remove them entirely.

5. Merge redundant cross-cutting descriptions. When a cross-cutting concern \
(error handling, observability, security, resilience) is explained in individual \
component sections AND in a dedicated cross-cutting section, keep one authoritative \
description and replace others with references.

6. Preserve all of the following without cuts:
- Design decisions and the reasoning behind them, including rejected alternatives \
and tradeoffs
- Architectural constraints and invariants
- Component responsibilities and ownership boundaries
- Behavioral semantics (how flows, processes, or lifecycles actually work)
- Security model details
- Deployment and operational architecture
- Information that appears only once anywhere in the document

7. Do NOT:
- Summarize rationale paragraphs into bullet points — keep the reasoning prose intact
- Remove example signatures, code snippets, or concrete illustrations
- Merge separate components or concepts into combined descriptions
- Remove or reorder sections — sections may be shorter but should not be removed \
or reordered
- Add commentary about what was changed

Output the consolidated document in full."""


class ConsolidatePromptTemplate(PromptTemplate):
    """Prompt template for consolidating documents to remove redundancy."""

    default_system_message = CONSOLIDATE_SYSTEM_PROMPT

    def build(
        self,
        input_artifacts,
        component_key=None,
        human_notes=None,
        current_content=None,
        upstream_changes=None,
    ):
        if not current_content:
            raise ValueError("Cannot consolidate: artifact has no content")

        return [
            {"role": "system", "content": self.default_system_message},
            {
                "role": "user",
                "content": (
                    "Here is the document to consolidate:\n\n"
                    f"{current_content}"
                ),
            },
        ]
