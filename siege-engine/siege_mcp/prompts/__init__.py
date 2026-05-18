"""Per-tier prompt instructions.

The text in this directory is extracted verbatim from the old backend's
``backend/graph/prompts/*.py`` modules (the ``_SYSTEM_PROMPT_TEMPLATE``
/ ``SYSTEM_PROMPT`` constants). One ``<tier>.md`` per tier for the
generator instruction, plus one ``review_<tier>.md`` per tier for the
reviewer instruction.

The per-tier readers in ``siege_mcp/tiers/`` attach the appropriate
prompt text under the ``instructions`` key of the context bundle they
return; skills then use it verbatim as the LLM's user prompt without
needing to know where it lives.

If a prompt needs updating, edit the ``.md`` file here — there's no
auto-regen from the old backend anymore.
"""

from __future__ import annotations

from pathlib import Path

_PROMPTS_DIR = Path(__file__).parent


def load_generation_prompt(tier: str) -> str:
    """Return the generator instruction text for a tier.

    Returns empty string if the tier's prompt file is missing, so a
    half-ported deployment degrades gracefully.
    """
    path = _PROMPTS_DIR / f"{tier}.md"
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def load_review_prompt(tier: str) -> str:
    """Return the reviewer's architecture-critique section for a tier."""
    path = _PROMPTS_DIR / f"review_{tier}.md"
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")
