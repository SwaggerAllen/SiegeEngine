"""Review prompt for the impl tier."""

from __future__ import annotations

from backend.graph.prompts.review._shared import (
    render_review_system_prompt,
    review_task_footer,
)
from backend.graph.review_context.impl import ImplContext

_HANDLES_INTRO = """\
Impl is where handles stop and code starts. The plan needs to \
name concrete files, functions, and sequence steps — not \
hand-wavy prose that leaves every decision open. A plan that \
doesn't cover every element of the owner's public surface is \
a plan that will ship a missing method later. Watch for \
happy-path-only flows: the failure modes upstream tiers named \
must all appear here.
"""

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

_ARCHITECTURE_INTRO = """\
Impl inherits every decision upstream tiers made. Silent \
drift from the owner's techspec (techspec says pure functions, \
impl introduces stateful singletons) or the deps' pubapi \
shapes (impl calls an API that doesn't exist) is the most \
common and most expensive failure here. Flag any drift by \
naming the specific contradiction.
"""

_ARCHITECTURE = """\
- Are the tech choices (libraries, patterns, concurrency \
model) consistent with ``project_techspec`` (the sysarch-tier \
project-wide stack dumped above)? Flag drift — a Python \
library claim on an Elixir project, a Postgres-specific \
pattern when the project techspec names a different store, \
etc. The project_techspec is canonical; do not fall back to \
priors about what "impls like this" usually use. If the \
``project_techspec`` section is missing from the user prompt, \
do not flag tech-stack drift — no baseline.
- Does the plan match the owner's techspec, or does it \
silently drift (e.g. techspec says "pure functions", impl \
introduces stateful singletons)?
- Are the comparch-tier policies (``component_policies`` for \
foundation impls, ``parent_policies`` for sub impls) honoured \
where the impl's code-paths match a trigger? Flag cross- \
cutting concerns the comparch named that the impl silently \
skips.
- Are the comparch-tier failure modes \
(``component_failure_surface`` / ``parent_failure_surface``) \
made observable as the comparch promised? An impl that masks \
a named residual risk (silent default instead of typed error, \
swallowed exception instead of logged escalation) is drift \
from the design intent.
- Are cross-cutting concerns (logging, metrics, auth checks) \
referenced where relevant, or silently omitted?
- Is the plan grounded in the dependencies' pubapi shapes, or \
does it assume APIs that don't exist?
- Are the leaf's dependencies consistent with the project- \
wide ``project_dependencies`` graph? Flag deps that aren't in \
the graph (or its sub-deps).
"""


def render_system_prompt() -> str:
    return render_review_system_prompt(
        artifact_label="``<implementation>`` block",
        scope_label="this leaf",
        handles_criteria=_HANDLES,
        architecture_criteria=_ARCHITECTURE,
        handles_intro=_HANDLES_INTRO,
        architecture_intro=_ARCHITECTURE_INTRO,
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
