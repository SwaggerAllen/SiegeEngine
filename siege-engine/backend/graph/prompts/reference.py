"""Prompt template for ``ref_*`` node generation.

References are supplemental documents — DSL specs, deployment
runbooks, cross-component invariants — that any other node can
attach to its regen context via an outgoing ``reference`` edge.
See ``docs/architecture/v2-rearchitecture.md`` §Project references.

A ref's stored content is a parseable ``<reference>`` XML block::

    <reference>
      <title>Short descriptive title</title>
      <body>
      Opaque markdown or prose. The validator doesn't parse this —
      anything goes inside `<body>`.
      </body>
      <see-also>
        <ref to="ref_..."/>
      </see-also>
    </reference>

``<title>`` and ``<body>`` are required; ``<see-also>`` is
optional. Unlike vocab see-also refs (which use ``name=`` form
at cold-start), reference see-also refs always use ``to=`` form
because refs are minted individually — the targets exist by the
time any see-also mentions them.

The prompt is generic (not per-tier) because a ref can be about
anything. Callers supply ``seed_description`` — a short prose
instruction ("a deployment runbook for the billing service", "a
DSL grammar spec for the pricing rules") — and
``referenced_content_summary`` — the rendered content of every
node this ref has outgoing ``reference`` edges to.
"""

from __future__ import annotations

from backend.graph.prompts._change_summary import change_summary_instruction

SYSTEM_PROMPT = """\
You are authoring a supplemental reference document for a \
software project. The document is pulled into other nodes' \
regeneration prompts via an advisory ``reference`` edge — it \
should be the kind of thing a downstream component's arch-doc \
regeneration would want to cite verbatim.

# Output format

Output a single ``<reference>`` block. Nothing else. The block \
has two required children (``<title>``, ``<body>``) and one \
optional child (``<see-also>``) in that fixed order:

    <reference>
      <title>Short descriptive title</title>
      <body>
      The body is opaque markdown — the validator does not parse \
its contents. You can use headings, fenced code blocks, bulleted \
lists, or plain prose. Keep it dense and concrete: the body will \
be transcluded into other nodes' regen prompts, so token economy \
matters.
      </body>
      <see-also>
        <ref to="ref_xxxxxxxx"/>
      </see-also>
    </reference>

# Rules

* ``<title>`` is plain text, non-empty, no nested tags. Typically \
2 to 8 words.
* ``<body>`` is required and non-empty. Contents are opaque to \
the validator but should be readable as standalone reference \
material — a downstream reader picking this up in isolation \
should be able to use it without the surrounding project \
context.
* ``<see-also>`` is optional. When present, contains only \
``<ref to="ref_..."/>`` children. The ``to=`` attribute must be \
an existing ``ref_xxxxxxxx`` id — do not invent IDs. If no \
other refs are relevant, omit the ``<see-also>`` block entirely.
* Do not include meta-commentary about what you are writing or \
how you arrived at the content. Output only the ``<reference>`` \
block.
* Unescaped ``&`` and ``<`` in the body are fine — the parser \
tolerates them.
""" + change_summary_instruction()


def render_user_prompt(
    *,
    seed_description: str,
    referenced_content_summary: str,
    prior_approved: str | None,
    prior_pending: str | None,
    feedback: str | None,
    parse_error: str | None = None,
) -> str:
    """Build the user prompt for the reference generator.

    ``seed_description`` is the user-supplied prose that the ref is
    about. Required — the generator has no other way to know what
    this ref should cover. ``referenced_content_summary`` is the
    rendered content of every node this ref has outgoing
    ``reference`` edges to (rendered by
    ``backend.graph.references.format_referenced_content_summary``).

    ``prior_approved`` is the current committed content on the ref
    node (``None`` before the first approval — but note that refs
    are not frozen after approval, so this can still be set when
    ``UpdateReference`` runs a post-approval regen). ``prior_pending``
    is the content of the in-flight draft being iterated on.
    ``feedback`` is the user's prose instruction for the regen
    (``None`` on first generation).

    ``parse_error`` is non-None only when the handler is re-invoking
    the LLM after a parse or validation failure on the previous
    output.
    """
    parts: list[str] = []
    parts.append("# What this reference is about")
    parts.append("")
    parts.append(seed_description.strip() or "(no seed description supplied)")
    parts.append("")

    parts.append("# Related nodes this reference connects to")
    parts.append("")
    parts.append(referenced_content_summary.strip() or "(no related nodes)")
    parts.append("")

    if prior_approved:
        parts.append("# Previously-approved reference content")
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
            "<reference> block. The specific error was:"
        )
        parts.append("")
        parts.append(f"> {parse_error.strip()}")
        parts.append("")
        parts.append(
            "Fix the structure and re-emit the full <reference> "
            "block. Keep the body content the same where possible "
            "— this retry is about format, not content."
        )
        parts.append("")

    parts.append("# Task")
    parts.append("")
    if parse_error:
        parts.append(
            "Re-emit the reference as a valid <reference> block "
            "addressing the structural error above. Output only "
            "the corrected <reference> block."
        )
    elif feedback and (prior_pending or prior_approved):
        parts.append(
            "Revise the reference to address the user feedback "
            "above. Preserve structure where the feedback does "
            "not request changes. Output only the revised "
            "<reference> block."
        )
    elif prior_pending or prior_approved:
        parts.append(
            "Regenerate the reference from scratch based on the "
            "seed description and related nodes. Output only the "
            "<reference> block."
        )
    else:
        parts.append(
            "Write an initial reference document based on the "
            "seed description and any related nodes. Output only "
            "the <reference> block."
        )

    return "\n".join(parts).rstrip() + "\n"
