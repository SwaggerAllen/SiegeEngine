"""Prompt template for the feature-expansion draft.

The feature expansion decomposes a project's input doc into a
structured, tag-based list of features that downstream phases
consume as pre-minted ``feat_*`` nodes. Output format:

    <features>
      <feature>
        <name>Billing</name>
        <intent>Users can pay for tiered service plans via credit
        card, with monthly and annual billing cycles. Failed
        payments trigger a grace-period retry before suspending
        the account.</intent>
      </feature>
      ...
    </features>

The tag structure is parsed by ``backend.graph.parsers.xml_sections``
and validated by ``backend.graph.parsers.validators.validate_features``
at mint time (see ``docs/architecture/v2-rearchitecture.md`` §Data
model / Feature expansion). If the LLM's output fails to parse or
validate, the mint handler runs a parse-validate retry loop with
the error fed back into the prompt.

Four input shapes for ``render_user_prompt``:

1. **Initial** — only the input doc. First generation at project
   creation time.
2. **Feedback only** — previously-approved content does not exist
   yet, user rejected the first draft and asked for changes via
   prose.
3. **Prior pending only** — regeneration with no feedback (retry).
4. **Feedback + prior pending** — typical iteration after the first
   draft.

Plus one orthogonal retry signal — ``parse_error`` — which is
passed in when the mint handler is re-invoking the LLM after a
parse or validation failure. ``parse_error`` composes with any of
the four shapes above.

The rendered prompt is a single string the CLI will see verbatim;
keep it stable so later prompt-version tracking can diff cleanly.
"""

from __future__ import annotations

SYSTEM_PROMPT = """\
You are a product architect helping the user brainstorm features \
for a software project. You will be given a project description \
(the "input doc") and asked to produce a **feature expansion** — \
a structured list of the features the project should have, which \
downstream passes will decompose into responsibilities and \
components.

# Output format

Output a single ``<features>`` block. Nothing else. Inside it, one \
``<feature>`` entry per feature, each with exactly one ``<name>`` \
and exactly one ``<intent>``:

    <features>
      <feature>
        <name>Billing</name>
        <intent>Users can pay for tiered service plans via credit \
card, with monthly and annual billing cycles. Invoices are emailed \
to the account owner and available for download from the settings \
page. Failed payments trigger a grace-period retry schedule before \
suspending the account.</intent>
      </feature>
      <feature>
        <name>Collaborative Editing</name>
        <intent>Multiple users can edit the same document \
simultaneously with real-time cursor awareness, presence \
indicators, and operational-transform conflict resolution. History \
is preserved per user so contributions are attributable. \
Disconnected clients reconcile on reconnect.</intent>
      </feature>
    </features>

# Rules

* Use the tag structure exactly as shown. Each ``<feature>`` has \
exactly one ``<name>`` and exactly one ``<intent>``. No other tags \
at any level.
* ``<name>`` is a short identifier — typically 2 to 5 words, title \
case. Think "Billing", "Collaborative Editing", "Access Control", \
not "The ability for users to pay for things."
* ``<intent>`` is a short paragraph — typically 2 to 5 sentences, \
longer only when the feature is complex. Describe *what* the \
feature does and *why*, not *how* it will be built. It should be \
concrete enough that a downstream decomposition pass can derive \
meaningful responsibilities from it, but not so detailed that it \
constrains implementation choices.
* Aim for breadth, not depth. The feature expansion is the seed \
for the structured feature graph; each feature gets its own \
detailed decomposition later.
* Do not fabricate constraints the input doc doesn't imply.
* Do not include meta-commentary about what you are doing, what \
the tags mean, or how you arrived at the list. Output only the \
``<features>`` block.
* Unescaped ``&`` and ``<`` in the intent text are fine — the \
parser tolerates them.
"""


def render_user_prompt(
    *,
    input_doc: str,
    prior_approved: str | None,
    prior_pending: str | None,
    feedback: str | None,
    parse_error: str | None = None,
) -> str:
    """Build the user prompt for the feature-expansion generator.

    All content inputs are plain strings. ``prior_approved`` is the
    current committed content on the expansion node (``None`` if
    nothing is approved yet). ``prior_pending`` is the content of
    the in-flight draft being iterated on. ``feedback`` is the
    user's prose instruction for the regeneration (``None`` on
    first generation).

    ``parse_error`` is non-None only when the mint handler is
    re-invoking the LLM after a parse or validation failure on the
    previous output. When set, the prompt includes an explicit
    "previous output failed with this error; fix it" section and
    asks the model to re-emit the corrected ``<features>`` block.
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

    if parse_error:
        parts.append("# Previous output failed structural validation")
        parts.append("")
        parts.append(
            "Your previous response did not parse into a valid "
            "<features> block. The specific error was:"
        )
        parts.append("")
        parts.append(f"> {parse_error.strip()}")
        parts.append("")
        parts.append(
            "Fix the structure and re-emit the full <features> block. "
            "Keep the feature set itself the same where possible — this "
            "retry is about format, not content."
        )
        parts.append("")

    parts.append("# Task")
    parts.append("")
    if parse_error:
        parts.append(
            "Re-emit the feature expansion as a valid <features> block "
            "addressing the structural error above. Output only the "
            "corrected <features> block."
        )
    elif feedback and (prior_pending or prior_approved):
        parts.append(
            "Revise the feature expansion to address the user feedback "
            "above. Preserve structure where the feedback does not "
            "request changes. Output only the revised <features> block."
        )
    elif prior_pending or prior_approved:
        parts.append(
            "Regenerate the feature expansion from scratch based on the "
            "input document. Output only the <features> block."
        )
    else:
        parts.append(
            "Write an initial feature expansion for this project based "
            "on the input document. Output only the <features> block."
        )

    return "\n".join(parts).rstrip() + "\n"
