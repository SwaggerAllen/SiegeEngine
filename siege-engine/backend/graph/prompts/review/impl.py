"""Review prompt for the impl tier."""

from __future__ import annotations

from backend.graph.prompts.review._shared import (
    render_review_system_prompt,
    review_task_footer,
)
from backend.graph.review_context.impl import ImplContext

_HANDLES = """\
- Does the implementation plan name concrete files / modules \
/ functions, or does it stay at a hand-wavy level?
- Are sequence / data-flow steps specific enough that an \
engineer could follow them to write code?
- Does the plan reference every element of the owner's \
public surface? If the pubapi has an ``auth(token)`` method, \
the impl should explain how it works internally.
- Does the plan respect the owner's private surface — not \
leak internals into public paths?
- Are error / edge cases named, or does the plan assume a \
happy path?
- Are tests described at a meaningful granularity — not just \
"unit tests will be written"?
"""

_ARCHITECTURE = """\
- Are the tech choices (libraries, patterns, concurrency \
model) defensible for this leaf's scope? Flag over- \
engineering for simple functions, under-engineering for \
complex flows.
- Does the plan match the owner's techspec, or does it \
silently drift (e.g. techspec says "pure functions", impl \
introduces stateful singletons)?
- Are cross-cutting concerns (logging, metrics, auth checks) \
referenced where relevant, or silently omitted?
- Is the plan grounded in the dependencies' pubapi shapes, or \
does it assume APIs that don't exist?
"""


def render_system_prompt() -> str:
    return render_review_system_prompt(
        artifact_label="``<implementation>`` block",
        scope_label="this leaf",
        handles_criteria=_HANDLES,
        architecture_criteria=_ARCHITECTURE,
    )


def render_user_prompt(context: ImplContext, generated_output: str) -> str:
    parts: list[str] = []
    parts.append(f"# Leaf under review: {context.owner_name}")
    parts.append("")
    for key, value in context.context_kwargs.items():
        if not isinstance(value, str) or not value.strip():
            continue
        parts.append(f"# {key}")
        parts.append("")
        parts.append(value.strip())
        parts.append("")
    parts.append("# Generated implementation (the artifact to review)")
    parts.append("")
    parts.append(generated_output.strip())
    parts.append("")
    parts.append("# Task")
    parts.append("")
    parts.append(review_task_footer())
    return "\n".join(parts).rstrip() + "\n"
