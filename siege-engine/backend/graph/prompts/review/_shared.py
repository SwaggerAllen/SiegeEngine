"""Shared review-prompt building blocks.

Every tier's review prompt follows the same structural template:

1. A system prompt that names the artifact being reviewed, sets
   the "be specific, cite elements" expectation, and prescribes
   a two-section markdown output.
2. A user prompt that wraps the tier's context bundle + the
   generator's output, then delegates to the system-prompt-
   defined format.

The helpers here give each tier a small, consistent rendering
surface so per-tier prompt modules stay focused on *what* is
tier-specific (the context bundle fields and the specific
review criteria per section) rather than re-describing the
output format or the "be direct" framing.
"""

from __future__ import annotations

_SYSTEM_PROMPT_TEMPLATE = """\
You are an AI reviewer auditing a just-generated \
{artifact_label} for {scope_label}. The block came out of a \
generator that saw the context described in the user prompt.

Your job is to surface issues the generator missed. Be \
specific — cite names, IDs, and structural elements. Avoid \
generic prose. A thin review is better than a padded one; if \
you have nothing to say in a section, write "No issues." and \
move on. Don't invent problems to fill space.

Be direct. No hedging. Either it's an issue or it isn't.

Output format — one markdown response with exactly these two \
top-level sections, in order:

## Handles & structure

{handles_criteria}

## Architectural decisions

{architecture_criteria}
"""


def render_review_system_prompt(
    *,
    artifact_label: str,
    scope_label: str,
    handles_criteria: str,
    architecture_criteria: str,
) -> str:
    """Build a review system prompt from per-tier criteria text.

    ``artifact_label`` names the generated block (e.g. "``<features>``
    expansion" or "``<subrequirements>`` block"). ``scope_label``
    names the reviewed context ("this project" / "this component").
    The two criteria strings are tier-specific bullet lists that
    fill out each section's guidance.
    """
    return _SYSTEM_PROMPT_TEMPLATE.format(
        artifact_label=artifact_label.strip(),
        scope_label=scope_label.strip(),
        handles_criteria=handles_criteria.strip(),
        architecture_criteria=architecture_criteria.strip(),
    )


_USER_PROMPT_TASK = (
    "Review the generated artifact above against the context. "
    "Output a markdown response with the two sections defined in "
    "your system instructions — ``## Handles & structure`` and "
    "``## Architectural decisions``. Output only the markdown "
    "review, no preamble."
)


def review_task_footer() -> str:
    """The user-prompt footer asking for the formatted response."""
    return _USER_PROMPT_TASK
