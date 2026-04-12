"""Prompt template for the feature-expansion draft.

The feature expansion is a free-form markdown document exploring what
features a project should have, synthesized from the project's input
doc. It is the **first** artifact the user iterates on after creating
a project, before any feature/component nodes have been minted.

Four input shapes:

1. **Initial** — only the input doc. First generation at project
   creation time.
2. **Feedback only** — previously-approved content does not exist yet,
   user rejected the first draft and asked for changes via prose.
3. **Prior pending only** — regeneration with no feedback (retry).
4. **Feedback + prior pending** — typical iteration after the first draft.

The rendered prompt is a single string the CLI will see verbatim;
keep it stable so later prompt-version tracking can diff cleanly.
"""

from __future__ import annotations

SYSTEM_PROMPT = """\
You are a product architect helping the user brainstorm features for a \
software project. You will be given a project description (the \
"input doc") and asked to produce a **feature expansion** — a \
free-form markdown document that explores the features the project \
should have.

Output requirements:

* Use markdown. Use headers, bullet lists, and short prose paragraphs.
* Aim for breadth, not depth — this document is the seed for the \
  structured feature graph. Each feature gets its own detailed \
  expansion later.
* Group related features under ## headers.
* Do not fabricate constraints the input doc doesn't imply.
* Do not include meta-commentary about what you are doing. Output \
  only the feature-expansion markdown.
"""


def render_user_prompt(
    *,
    input_doc: str,
    prior_approved: str | None,
    prior_pending: str | None,
    feedback: str | None,
) -> str:
    """Build the user prompt for the feature-expansion generator.

    All inputs are plain strings. ``prior_approved`` is the current
    committed content on the expansion node (``None`` if nothing is
    approved yet). ``prior_pending`` is the content of the in-flight
    draft being iterated on. ``feedback`` is the user's prose
    instruction for the regeneration (``None`` on first generation).
    """
    parts: list[str] = []
    parts.append("# Project input document")
    parts.append("")
    parts.append(input_doc.strip() or "(no input document supplied)")
    parts.append("")

    if prior_approved:
        parts.append("# Previously-approved feature expansion")
        parts.append("")
        parts.append(prior_approved.strip())
        parts.append("")

    if prior_pending:
        parts.append("# Current draft (not yet approved)")
        parts.append("")
        parts.append(prior_pending.strip())
        parts.append("")

    if feedback:
        parts.append("# User feedback")
        parts.append("")
        parts.append(feedback.strip())
        parts.append("")

    parts.append("# Task")
    parts.append("")
    if feedback and (prior_pending or prior_approved):
        parts.append(
            "Revise the feature expansion to address the user feedback above. "
            "Preserve structure where the feedback does not request changes. "
            "Output only the revised markdown."
        )
    elif prior_pending or prior_approved:
        parts.append(
            "Regenerate the feature expansion from scratch based on the "
            "input document. Output only the markdown."
        )
    else:
        parts.append(
            "Write an initial feature expansion for this project based on "
            "the input document. Output only the markdown."
        )

    return "\n".join(parts).rstrip() + "\n"
