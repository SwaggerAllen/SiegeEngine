"""``validate_artifact`` — pre-commit validation gate.

Skills call this between LLM completion and ``git commit``. The check
runs the tier-appropriate parser + structural rules and returns
``{ok, errors, warnings, extracted_metadata}``. A failed validate is a
signal to loop back to the LLM with the errors as feedback, not to
commit broken output.

This is a thin shell for v0. Real per-tier validators (the 4K-line
``backend/graph/parsers/validators.py``) are not yet ported — they're a
clean text-only port and land in a follow-up. The shell returns ok=True
with no findings unless the body is empty or the section headers are
missing entirely.
"""

from __future__ import annotations

from typing import Any

from siege.fragments import parse_body_sections
from siege.state import Tier

# Minimum sections every tier body should carry. Used as a cheap
# sanity gate while the full per-tier validators are still ported.
_MIN_SECTIONS: dict[Tier, tuple[str, ...]] = {
    "feature_expansion": ("summary",),
    "requirements": ("role", "description"),
    "sysarch": (),
    "comparch": ("comparch:techspec", "comparch:pubapi"),
    "subcomparch": ("subcomparch:techspec", "subcomparch:pubapi"),
    "impl": ("impl:approach",),
    "fanin": ("synthesis",),
}


def validate_artifact(tier: Tier, body: str) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []

    if not body or not body.strip():
        errors.append("body is empty")
        return {"ok": False, "errors": errors, "warnings": warnings, "extracted_metadata": {}}

    sections = parse_body_sections(body)
    for required in _MIN_SECTIONS.get(tier, ()):
        if required not in sections:
            warnings.append(f"missing recommended section ## {required}")

    metadata: dict[str, Any] = {
        "section_count": len(sections),
        "section_names": list(sections.keys()),
        "byte_size": len(body.encode("utf-8")),
    }

    return {
        "ok": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "extracted_metadata": metadata,
    }
