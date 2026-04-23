"""Shared review-prompt building blocks.

Every tier's review prompt follows the same structural template:

1. A system prompt that names the artifact being reviewed, sets
   the "be specific, cite elements" expectation, and prescribes
   the structured ``<review>`` XML output format.
2. A user prompt that wraps the tier's context bundle + the
   generator's output, then delegates to the system-prompt-
   defined format.

The helpers here give each tier a small, consistent rendering
surface so per-tier prompt modules stay focused on *what* is
tier-specific (the context bundle fields and the specific
review criteria per section) rather than re-describing the
output format or the "be direct" framing.

Output is parseable XML so the frontend can render each
``<finding>`` as an individually-checkable line for selective
apply-as-feedback. See :mod:`backend.graph.parsers.review_xml`
for the server-side validator.
"""

from __future__ import annotations

_SYSTEM_PROMPT_TEMPLATE = """\
You are an AI reviewer auditing a just-generated \
{artifact_label} for {scope_label}. The block came out of a \
generator that saw the context described in the user prompt.

Your job is to surface issues the generator missed. Be \
specific — cite names, IDs, and structural elements. Avoid \
generic prose. Scale your findings to the problem surface: \
emit one ``<finding>`` per distinct issue you can name; emit \
**zero** findings when there's nothing actionable to flag. \
Don't invent problems to fill space, don't emit placeholder \
"no issues" findings. A clean artifact gets an empty findings \
section with a high score — that's the correct shape.

Be direct. No hedging. Either it's an issue or it isn't.

Output format — XML matching this schema. No markdown, no \
preamble, no code fences, no commentary outside the root tag:

<review>
  <intro>One or two short paragraphs (3–6 sentences total) \
giving the user a "how close to finished" read on this \
artifact. Summarize the overall shape, name the single biggest \
thing holding it back (if anything), and note what's in good \
shape. Purely display-only — the findings below are what the \
generator regens against.</intro>
  <score>0</score>
  <handles-structure>
    <finding id="h1">One specific issue, stated as actionable \
prose. Name the element (ID / name / section), say what's \
wrong, ideally suggest a fix. One concern per finding — don't \
pack multiple issues into one entry.</finding>
    <finding id="h2">...</finding>
  </handles-structure>
  <architectural-decisions>
    <finding id="a1">...</finding>
  </architectural-decisions>
</review>

Rules:
- ``<intro>`` is required and non-empty. Keep it short — this \
is a display hint for the user, not a substitute for findings. \
Content here does not feed the regeneration loop.
- ``<score>`` is an integer 0-100 on the "how close to \
finished" scale:
  * 0-30 — fundamental axis is wrong or large-scale rework \
needed; the artifact is not ready for downstream consumption.
  * 31-60 — structural issues to fix before approval; \
shape is roughly right but several findings need addressing.
  * 61-85 — minor refinements; one or two small findings, \
otherwise usable.
  * 86-100 — ready to approve; zero or near-zero findings.
  Pick the score that matches your own findings count and \
severity. A score in the 80s with ten critical findings is \
internally inconsistent.
- Assign each finding a stable id: ``h1``, ``h2``, ... inside \
``<handles-structure>``; ``a1``, ``a2``, ... inside \
``<architectural-decisions>``. Sequential within each section, \
no gaps.
- Scale findings to actual issues. One finding per distinct \
problem you can name. If a section has no actionable findings, \
leave it empty: ``<handles-structure></handles-structure>``. \
Do not emit a placeholder "no issues" finding and do not pad \
with low-value nitpicks.
- Both findings sections must be present even if empty.
- Finding text is plain prose. No nested XML tags inside a \
``<finding>``. Avoid bullet lists within a single finding — \
split into multiple findings instead.

Handles & structure review.

{handles_intro}

Specific checks under ``<handles-structure>``:

{handles_criteria}

Architectural-decisions review.

{architecture_intro}

Specific checks under ``<architectural-decisions>``:

{architecture_criteria}
"""


def render_review_system_prompt(
    *,
    artifact_label: str,
    scope_label: str,
    handles_criteria: str,
    architecture_criteria: str,
    handles_intro: str = "",
    architecture_intro: str = "",
) -> str:
    """Build a review system prompt from per-tier criteria text.

    ``artifact_label`` names the generated block (e.g. "``<features>``
    expansion" or "``<subrequirements>`` block"). ``scope_label``
    names the reviewed context ("this project" / "this component").
    The two criteria strings are tier-specific bullet lists that
    fill out each section's guidance.

    ``handles_intro`` and ``architecture_intro`` are short prose
    paragraphs (2–3 sentences) that frame *why* each section
    matters — downstream implication, specific risks to catch —
    before the bulleted criteria. Per-tier prompts supply these;
    an empty default keeps backward compatibility with tiers
    that haven't migrated yet.
    """
    intro_handles = handles_intro.strip() or (
        "Audit the artifact's handle quality and structural hygiene. "
        "Look for issues a downstream tier would hit when consuming "
        "this block."
    )
    intro_architecture = architecture_intro.strip() or (
        "Audit the artifact's architectural choices. Flag decisions "
        "that will compound badly if carried forward."
    )
    return _SYSTEM_PROMPT_TEMPLATE.format(
        artifact_label=artifact_label.strip(),
        scope_label=scope_label.strip(),
        handles_criteria=handles_criteria.strip(),
        architecture_criteria=architecture_criteria.strip(),
        handles_intro=intro_handles,
        architecture_intro=intro_architecture,
    )


_USER_PROMPT_TASK = (
    "Review the generated artifact above against the context. "
    "Output a single ``<review>`` XML block with the schema + "
    "rules defined in your system instructions. Output only the "
    "XML, no preamble, no markdown, no code fences."
)


def review_task_footer() -> str:
    """The user-prompt footer asking for the formatted response."""
    return _USER_PROMPT_TASK
