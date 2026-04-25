# ruff: noqa: E501
"""Prompt for the single-feature expansion handler.

Used by ``v2.expand_single_feature`` to flesh out a feat node minted
by a ``ProposeFeature`` instruction. The user types a one-line
description; this prompt asks the LLM to produce a canonical name
+ 2-4 sentence intent paragraph + optional group label that fits
the existing feature voice and group structure.

Distinct from ``backend.graph.prompts.feature_expansion`` (which
generates the **whole** feature list from the input doc) — this
prompt is single-feature-focused so it stays cheap and doesn't
re-invent the world. It reads the existing feature list as
context for voice + group consistency, but emits a single
``<feature>`` block.
"""

from __future__ import annotations

_SYSTEM_PROMPT = """\
You are expanding a **single proposed feature** into the project's \
canonical feature shape. The user has typed a short description; \
your job is to produce one ``<feature>`` block that fits the \
project's existing feature voice and group structure.

You will be given:

1. The project input document (for project framing and \
terminology).
2. The existing feature list (with names, intents, and group \
labels) — for voice consistency. Match the existing intent-\
paragraph length, tone, and level of specificity.
3. The new feature's user-supplied description.

# Output format

Emit a ``<features>`` block containing exactly one feature. If \
the new feature belongs to an existing group (or warrants a new \
one), wrap the ``<feature>`` in a ``<group>`` with a ``<name>``. \
If it doesn't, emit the ``<feature>`` directly under ``<features>``. \
Examples:

Grouped (most common):

    <features>
      <group>
        <name>Authentication</name>
        <feature>
          <name>Two-factor Authentication</name>
          <intent>Lets a user enable a second-factor verification step \
on sign-in (TOTP authenticator app or hardware key) and recover \
access through a one-time backup code if their primary factor is \
lost.</intent>
        </feature>
      </group>
    </features>

Ungrouped (when the existing feature list has no groups):

    <features>
      <feature>
        <name>Two-factor Authentication</name>
        <intent>...</intent>
      </feature>
    </features>

# Rules

* The output's ``<features>`` block must contain **exactly one** \
``<feature>`` (counted across any wrapping ``<group>``). The \
caller validates this and rejects multi-feature output.
* ``<name>`` — short, title-cased, 2-6 words. Match the noun-phrase \
shape of existing feature names (look at the input list for \
patterns). The user's description is *intent*, not the name; \
extract the canonical name from it. If the user's description is \
already a usable name (rare — usually it's a sentence), still \
emit it as the canonical name. **Don't include the user's \
prefix-style "(proposing) ..." placeholder** — that was a \
synthetic stand-in to make the row visible in the queue while \
this expansion ran. The canonical name replaces it via \
``NodeRenamed`` once you emit.
* ``<intent>`` — 2-4 sentences of plain prose describing what \
this feature does **for the user**. Match the length and \
specificity of existing feature intents in the input list. \
Don't speculate about implementation or stack — that's downstream \
tier territory. Write at the same abstraction level as the \
existing feature intents.
* ``<group>`` (wrapper) — if the existing feature list uses \
groups and this feature naturally fits one of them, wrap the \
``<feature>`` in a ``<group>`` with the existing group's exact \
label as its ``<name>``. If it doesn't fit any existing group \
but the project's feature list is grouped, propose a short new \
label (1-3 words). If the existing list has no groups at all, \
omit the wrapper entirely.
* ``<implicit/>`` — emit this self-closing marker inside the \
``<feature>`` **only** if the input document does not explicitly \
name this feature but the user's description implies it as a \
derivative of something the doc does name. Most user-proposed \
features are explicit intent and should NOT carry this marker.
* No commentary outside the ``<features>`` block. No \
``<introduction>``, no preamble, no markdown headers.
* Unescaped ``&`` and ``<`` inside ``<intent>`` text are fine.
"""


def render_system_prompt() -> str:
    """Return the single-feature expansion system prompt."""
    return _SYSTEM_PROMPT


def render_user_prompt(
    *,
    input_doc: str,
    existing_features_summary: str,
    name_hint: str,
    description: str,
) -> str:
    """Build the user prompt.

    ``input_doc`` is the project's raw input. ``existing_features_summary``
    is a markdown rendering of the current feature list (name + intent
    excerpt + group). ``name_hint`` is the synthetic placeholder
    currently visible in the projection (e.g. ``"(proposing) MFA setup"``)
    and is NOT the canonical name — the LLM produces the canonical.
    ``description`` is the user's one-liner.
    """
    parts: list[str] = []
    if input_doc and input_doc.strip():
        parts.append("# Project input document")
        parts.append("")
        parts.append(input_doc.strip())
        parts.append("")
    parts.append("# Existing features (for voice + group consistency)")
    parts.append("")
    parts.append(existing_features_summary.strip() or "(no existing features)")
    parts.append("")
    parts.append("# New feature being proposed")
    parts.append("")
    parts.append(f"**Placeholder name (replace with canonical):** {name_hint.strip()}")
    parts.append("")
    parts.append(f"**User description:** {description.strip()}")
    parts.append("")
    parts.append("# Task")
    parts.append("")
    parts.append(
        "Produce a single ``<feature>`` block for this proposed feature, "
        "fitting it into the existing feature list's voice and group "
        "structure. Emit only the ``<feature>`` block — no other tags, "
        "no commentary."
    )
    return "\n".join(parts).rstrip() + "\n"


def format_existing_features_summary(features: list[dict]) -> str:
    """Render the existing feature list as bulleted markdown.

    Each entry includes name + first ~120 chars of intent + group label.
    Truncated intents keep the prompt small for projects with many
    features. Caller passes ``[{name, content, group_label}, ...]``.
    """
    if not features:
        return "(no existing features)"
    lines: list[str] = []
    for feat in features:
        name = (feat.get("name") or "").strip() or "(unnamed)"
        intent = (feat.get("content") or "").strip()
        if len(intent) > 120:
            intent = intent[:117] + "…"
        group = (feat.get("group_label") or "").strip()
        group_part = f" *[group: {group}]*" if group else ""
        lines.append(f"- **{name}**{group_part}: {intent}")
    return "\n".join(lines)
