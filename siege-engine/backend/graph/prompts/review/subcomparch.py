"""Review prompt for the subcomparch tier."""

from __future__ import annotations

from backend.graph.prompts.review._shared import (
    render_review_system_prompt,
    review_task_footer,
)
from backend.graph.review_context.subcomparch import SubcomparchContext

_HANDLES = """\
- ``<technical-specification>`` narrows the parent comparch \
techspec to this sub's slice — doesn't duplicate it verbatim. \
Flag wholesale copying.
- ``<public-surface>`` names types + signatures + error modes \
for what sibling subs and the parent's external dependents \
call. Flag method-names-without-signatures, bloated public \
surface, or missing error shapes.
- ``<private-surface>`` is this sub's internal toolkit only \
— helpers and types the sub's impl uses. Flag re-exported \
public API.
- ``<dependencies>`` targets are valid: real comp_* IDs for \
parent-sibling deps, local aliases for same-parent sibling \
subs. Flag unknown IDs or invalid alias syntax.
- Is the sub's scope (what its role says vs what it actually \
builds via public + private surface) coherent?
"""

_ARCHITECTURE = """\
- Is this sub's tech choice consistent with the parent \
component's tech spec? Flag drift (e.g. parent says async, \
sub's pubapi is sync-only).
- Is the decomposition of subresps into this sub's pubapi the \
right cut? Over-bundled or leaky?
- Are the dependencies between sibling subs a DAG and \
minimal?
"""


def render_system_prompt() -> str:
    return render_review_system_prompt(
        artifact_label="``<subcomparch>`` block",
        scope_label="this subcomponent",
        handles_criteria=_HANDLES,
        architecture_criteria=_ARCHITECTURE,
    )


def render_user_prompt(context: SubcomparchContext, generated_output: str) -> str:
    parts: list[str] = []
    parts.append(f"# Subcomponent under review: {context.sub_name}")
    parts.append("")
    for key, value in context.context_kwargs.items():
        if not isinstance(value, str) or not value.strip():
            continue
        parts.append(f"# {key}")
        parts.append("")
        parts.append(value.strip())
        parts.append("")
    parts.append("# Generated subcomparch (the artifact to review)")
    parts.append("")
    parts.append(generated_output.strip())
    parts.append("")
    parts.append("# Task")
    parts.append("")
    parts.append(review_task_footer())
    return "\n".join(parts).rstrip() + "\n"
