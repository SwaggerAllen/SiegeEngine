"""Review prompt for the fanin tier."""

from __future__ import annotations

from backend.graph.prompts.review._shared import (
    render_review_system_prompt,
    review_task_footer,
)
from backend.graph.review_context.fanin import FanInContext

_HANDLES_INTRO = """\
Fan-in is the bottom-up synthesis — it summarizes what the \
subcomponents as-built actually do, which presentational \
counterparts read for their rotation. If the synthesis drifts \
from the sub impls (claiming behavior the code doesn't \
actually implement), presentational components inherit that \
drift and ship UI for capabilities the domain doesn't have. \
Flag claims not grounded in the sub impls directly.
"""

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

_ARCHITECTURE_INTRO = """\
Fan-in has no tech decisions of its own — it's a pure rollup \
of what the subs built. The architectural read here is about \
the gap between top-down intent (comparch + subcomparch \
pubapis) and bottom-up reality (impls). Surface patterns \
worth promoting; flag mismatches worth regenerating the \
upstream tier for.
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
        handles_intro=_HANDLES_INTRO,
        architecture_intro=_ARCHITECTURE_INTRO,
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
