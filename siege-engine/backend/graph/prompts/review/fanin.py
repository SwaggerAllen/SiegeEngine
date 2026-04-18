"""Review prompt for the fanin tier."""

from __future__ import annotations

from backend.graph.prompts.review._shared import (
    render_review_system_prompt,
    review_task_footer,
)
from backend.graph.review_context.fanin import FanInContext

_HANDLES = """\
- Does the fan-in synthesis faithfully summarize what the \
subcomponents as-built actually do? Flag claims not grounded \
in the sub impls.
- Are cross-sub dependencies / sequencing / data flows \
captured accurately? Flag omissions.
- Does the synthesis preserve the domain comp's api-intent \
contract, or does it drift?
- Is the synthesis specific about observed behavior (what \
the code does) rather than just restating the sub roles?
"""

_ARCHITECTURE = """\
- Does the synthesis reveal drift between the top-down design \
intent (comparch / subcomparch pubapis) and the bottom-up \
reality (impls)? If so, call out the mismatch.
- Are emergent patterns across subs worth surfacing — shared \
abstractions, repeated idioms, coherent data flow?
- Does the synthesis suggest refactoring opportunities the \
top-down design missed?
"""


def render_system_prompt() -> str:
    return render_review_system_prompt(
        artifact_label="``<fanin>`` synthesis",
        scope_label="this fanned-out domain component",
        handles_criteria=_HANDLES,
        architecture_criteria=_ARCHITECTURE,
    )


def render_user_prompt(context: FanInContext, generated_output: str) -> str:
    parts: list[str] = []
    parts.append(f"# Domain component: {context.owner_comp_name}")
    parts.append("")
    # Dump whatever prose fields the synthesis context exposes.
    for attr_name in dir(context.synthesis_ctx):
        if attr_name.startswith("_"):
            continue
        value = getattr(context.synthesis_ctx, attr_name, None)
        if not isinstance(value, str) or not value.strip():
            continue
        parts.append(f"# {attr_name}")
        parts.append("")
        parts.append(value.strip())
        parts.append("")
    parts.append("# Generated fan-in (the artifact to review)")
    parts.append("")
    parts.append(generated_output.strip())
    parts.append("")
    parts.append("# Task")
    parts.append("")
    parts.append(review_task_footer())
    return "\n".join(parts).rstrip() + "\n"
