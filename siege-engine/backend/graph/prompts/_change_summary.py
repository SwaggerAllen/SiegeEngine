# ruff: noqa: E501
"""Shared change-summary prompt block (Phase 13).

Every bootstrap-tier + reference prompt appends this block so the
LLM knows to emit a ``<change-summary>`` sibling alongside
``<introduction>`` and its main output tag. The per-draft body
is lifted out by
:func:`backend.graph.parsers.change_summary.extract_change_summary`
inside :func:`persist_draft` and stored on
``Draft.change_summary``. The user sees it as the diff header on
the regen-time diff and on the batched-review walker.

Fan-in is out of scope — its prompt does not embed this block, so
the ``extract_change_summary`` helper's "missing tag is fine"
branch fires and fan-in drafts pass through unchanged.
"""

from __future__ import annotations

_CHANGE_SUMMARY_INSTRUCTION = """\

# Change summary

Emit a single ``<change-summary>`` element as a sibling of \
``<introduction>`` (and your main output tag). One to three short \
sentences of plain prose. This is display-only — a "what's in \
this draft" hint for the reviewer; it does NOT feed the next \
regen's prompt and will not be shown as input to the generator \
on a subsequent pass.

Shape:

  <change-summary>One to three sentences describing what this \
draft contains or — on a regen — what you changed vs. the prior \
draft and why. No bullets, no nested tags, plain prose.</change-summary>

Framing:

* **Initial draft** (no prior version shown above): describe \
what you produced — the rough shape, the notable decisions, any \
axis you had to pick. Example: "First pass — 32 atoms rotating 8 \
features. Biggest cluster is authentication (session lifecycle, \
password hash, rate limit, token refresh, access decision). \
Event log and reducer both emitted as system-emergent atoms \
with no feature tags."
* **Regen** (user feedback or AI-review findings visible above): \
lead with what changed and why. Name the specific atoms / \
components / fragments you edited and the feedback they address. \
Example: "Split ''review routing, notification, and SLA'' into \
three atoms per the review's compound-name finding. Renamed \
''authentication'' → ''session-state lifecycle'' for sharper \
rotation."

Rules:

* Required on every draft. Empty ``<change-summary/>`` is \
accepted by the parser but produces a blank header in the UI, \
so always write something.
* Do not include findings verbatim — paraphrase. Findings flow \
through a separate channel.
* Keep it tight. The goal is a reviewer-readable header, not a \
full changelog. 1-3 sentences.
"""


def change_summary_instruction() -> str:
    """Return the change-summary prompt block.

    Append this to every in-scope tier's system prompt template.
    Starts with a leading newline so callers can concatenate
    without re-formatting the host template.
    """
    return _CHANGE_SUMMARY_INSTRUCTION
