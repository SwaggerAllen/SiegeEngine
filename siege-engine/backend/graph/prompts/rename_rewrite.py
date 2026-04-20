"""Prompt templates for the Phase 11 rename-rewrite handler.

One prompt per rewrite call — the handler feeds each node's
content + each owned fragment through
:func:`render_rename_rewrite_prompt` in turn. Output is expected
to be the rewritten text *verbatim*, with no explanation and no
XML / markdown wrapper. The handler strips leading/trailing
whitespace and commits the result.

If the LLM strays (explanatory preamble, code fence, extra
commentary), the handler falls back to the word-boundary regex
path so the rename itself still commits.
"""

from __future__ import annotations

SYSTEM_PROMPT = """You rewrite prose to reflect a rename of a single named entity.

Rules:
- Replace every occurrence of the old name with the new name where
  the reference is to the renamed entity.
- Preserve every other word, punctuation mark, whitespace character,
  and line break exactly.
- Do not add commentary, headings, explanations, code fences, or any
  wrapper text.
- Do not rewrite names that only share a prefix or substring with the
  old name. Example: rewriting "Bill" to "Invoice" must not touch
  "Billing" or "Bill-boards" unless they refer to the same entity.
- If no occurrences of the old name are found, return the input
  unchanged.
- Return only the rewritten text.
"""


def render_rename_rewrite_prompt(*, old_name: str, new_name: str, text: str) -> str:
    """Build the user prompt for a single-document rewrite call.

    ``text`` is the current content of the node or fragment; the
    LLM returns the rewritten version. Output is treated as a
    complete replacement for ``text`` — no diff, no section
    wrapping, just the post-rewrite prose.
    """
    return (
        f"Rename: {old_name!r} → {new_name!r}\n"
        f"\n"
        f"Input:\n"
        f"---\n"
        f"{text}\n"
        f"---\n"
        f"\n"
        f"Return the rewritten Input, preserving every other character exactly.\n"
    )
