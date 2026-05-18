"""Fragment kinds + body-section extraction.

Ported from ``backend/graph/fragments.py`` with one structural change:
fragments are no longer rows in a database table; they're sections
within a tier artifact's ``body.md`` file. The MCP server parses a body
into sections on demand and serves them to downstream tier readers via
the same ``FragmentKind`` enum the old code used.

Tier → section conventions:

- **Sysarch** artifact body carries the per-comp ``TECHSPEC`` /
  ``PUBAPI`` skeletal seeds for top-level components. Subcomps are
  not present at sysarch time.
- **Comparch** body carries the rich ``COMPARCH_TECHSPEC`` /
  ``COMPARCH_PUBAPI`` / ``COMPARCH_PRIVAPI`` / ``COMPARCH_POLICIES`` /
  ``COMPARCH_DEPS`` / ``COMPARCH_FAILURE_SURFACE`` sections for the
  comp itself, plus the per-subcomp ``TECHSPEC`` / ``PUBAPI`` skeletal
  seeds (one stanza per minted sub).
- **Subcomparch** body carries the rich ``SUBCOMPARCH_*`` sections for
  one sub.

The section delimiters in body.md mirror the old XML/markdown layout:

    ## comparch:techspec
    <body...>

    ## comparch:pubapi
    <body...>

    ## subcomparch:techspec
    <body...>

The parser is permissive — unknown sections are kept verbatim and
ignored. New section kinds can land without breaking older bodies.
"""

from __future__ import annotations

import re
from enum import Enum


class FragmentKind(str, Enum):
    """Vocabulary of parseable architecture-doc fragments.

    Single-token values; the layered model from the old code is
    preserved verbatim so prompt builders keep working.
    """

    TECHSPEC = "techspec"
    PUBAPI = "pubapi"
    PRIVAPI = "privapi"
    POLICIES = "policies"
    DEPS = "deps"
    FAILURE_SURFACE = "failuresurface"

    COMPARCH_TECHSPEC = "comparchtechspec"
    COMPARCH_PUBAPI = "comparchpubapi"
    COMPARCH_PRIVAPI = "comparchprivapi"
    COMPARCH_POLICIES = "comparchpolicies"
    COMPARCH_DEPS = "comparchdeps"
    COMPARCH_FAILURE_SURFACE = "comparchfailuresurface"

    SUBCOMPARCH_TECHSPEC = "subcomparchtechspec"
    SUBCOMPARCH_PUBAPI = "subcomparchpubapi"
    SUBCOMPARCH_PRIVAPI = "subcomparchprivapi"
    SUBCOMPARCH_DEPS = "subcomparchdeps"


COMPARCH_LAYER_KINDS: tuple[FragmentKind, ...] = (
    FragmentKind.COMPARCH_TECHSPEC,
    FragmentKind.COMPARCH_PUBAPI,
    FragmentKind.COMPARCH_PRIVAPI,
    FragmentKind.COMPARCH_POLICIES,
    FragmentKind.COMPARCH_DEPS,
    FragmentKind.COMPARCH_FAILURE_SURFACE,
)

SUBCOMPARCH_LAYER_KINDS: tuple[FragmentKind, ...] = (
    FragmentKind.SUBCOMPARCH_TECHSPEC,
    FragmentKind.SUBCOMPARCH_PUBAPI,
    FragmentKind.SUBCOMPARCH_PRIVAPI,
    FragmentKind.SUBCOMPARCH_DEPS,
)

COMPARCH_LAYER_FALLBACK: dict[FragmentKind, FragmentKind] = {
    FragmentKind.COMPARCH_TECHSPEC: FragmentKind.TECHSPEC,
    FragmentKind.COMPARCH_PUBAPI: FragmentKind.PUBAPI,
    FragmentKind.COMPARCH_PRIVAPI: FragmentKind.PRIVAPI,
    FragmentKind.COMPARCH_POLICIES: FragmentKind.POLICIES,
    FragmentKind.COMPARCH_DEPS: FragmentKind.DEPS,
    FragmentKind.COMPARCH_FAILURE_SURFACE: FragmentKind.FAILURE_SURFACE,
}

SUBCOMPARCH_LAYER_FALLBACK: dict[FragmentKind, FragmentKind] = {
    FragmentKind.SUBCOMPARCH_TECHSPEC: FragmentKind.TECHSPEC,
    FragmentKind.SUBCOMPARCH_PUBAPI: FragmentKind.PUBAPI,
    FragmentKind.SUBCOMPARCH_PRIVAPI: FragmentKind.PRIVAPI,
    FragmentKind.SUBCOMPARCH_DEPS: FragmentKind.DEPS,
}

LAYERED_KIND_FOR_TOP_LEVEL: dict[FragmentKind, FragmentKind] = {
    legacy: layer for layer, legacy in COMPARCH_LAYER_FALLBACK.items()
}
LAYERED_KIND_FOR_SUBCOMP: dict[FragmentKind, FragmentKind] = {
    legacy: layer for layer, legacy in SUBCOMPARCH_LAYER_FALLBACK.items()
}


# Single-token invariant enforced at import time, same as the old code.
for _kind in FragmentKind:
    assert "_" not in _kind.value, (
        f"FragmentKind.{_kind.name} value {_kind.value!r} contains an "
        "underscore; fragment kinds must be single-token."
    )
del _kind


# ---------- Body section parsing ----------

_SECTION_HEADER_RE = re.compile(r"^##\s+([a-z]+(?::[a-z_]+)*)\s*$", re.MULTILINE)


def parse_body_sections(body: str) -> dict[str, str]:
    """Parse a body.md into a {section_name: content} dict.

    Section headers are H2s of the form ``## <prefix>:<name>`` (e.g.
    ``## comparch:techspec``, ``## subcomparch:pubapi``). Anything
    before the first header is filed under ``""``. Unknown sections are
    preserved verbatim; downstream callers decide whether to use them.
    """
    sections: dict[str, str] = {}
    matches = list(_SECTION_HEADER_RE.finditer(body))
    if not matches:
        sections[""] = body.strip()
        return sections

    if matches[0].start() > 0:
        head = body[: matches[0].start()].strip()
        if head:
            sections[""] = head

    for i, m in enumerate(matches):
        name = m.group(1)
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        sections[name] = body[start:end].strip()
    return sections


def section_for_kind(kind: FragmentKind, sub_id: str | None = None) -> str:
    """Map a FragmentKind + optional sub_id to the section name in body.md.

    Comparch-body sections for the comp itself: ``comparch:<short>``.
    Comparch-body sections for a sub seed: ``sub:<sub_id>:<short>``.
    Subcomparch-body sections: ``subcomparch:<short>``.
    Sysarch-body per-comp seeds: ``seed:<comp_id>:<short>`` (the sysarch
    body iterates comps; consumers index by comp_id).
    """
    short_map = {
        FragmentKind.COMPARCH_TECHSPEC: "comparch:techspec",
        FragmentKind.COMPARCH_PUBAPI: "comparch:pubapi",
        FragmentKind.COMPARCH_PRIVAPI: "comparch:privapi",
        FragmentKind.COMPARCH_POLICIES: "comparch:policies",
        FragmentKind.COMPARCH_DEPS: "comparch:deps",
        FragmentKind.COMPARCH_FAILURE_SURFACE: "comparch:failuresurface",
        FragmentKind.SUBCOMPARCH_TECHSPEC: "subcomparch:techspec",
        FragmentKind.SUBCOMPARCH_PUBAPI: "subcomparch:pubapi",
        FragmentKind.SUBCOMPARCH_PRIVAPI: "subcomparch:privapi",
        FragmentKind.SUBCOMPARCH_DEPS: "subcomparch:deps",
        FragmentKind.TECHSPEC: "techspec",
        FragmentKind.PUBAPI: "pubapi",
        FragmentKind.PRIVAPI: "privapi",
        FragmentKind.POLICIES: "policies",
        FragmentKind.DEPS: "deps",
        FragmentKind.FAILURE_SURFACE: "failuresurface",
    }
    if sub_id is None:
        return short_map[kind]
    return f"sub:{sub_id}:{short_map[kind].split(':')[-1]}"
