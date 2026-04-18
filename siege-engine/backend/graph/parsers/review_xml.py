"""Parser + validator for the Phase 8 AI-review XML format.

The review handler calls :func:`parse_review` on the CLI output
before committing it. Malformed reviews raise :class:`ReviewXMLError`
— the review job marks itself failed, the frontend surfaces the
error, and the user can hit "Retry review" to try again.

Schema (enforced by this module):

.. code-block:: xml

    <review>
      <handles-structure>
        <finding id="h1">Plain prose finding.</finding>
        <finding id="h2">...</finding>
      </handles-structure>
      <architectural-decisions>
        <finding id="a1">...</finding>
      </architectural-decisions>
    </review>

* Both ``<handles-structure>`` and ``<architectural-decisions>``
  sections must be present.
* Either section may be empty (no findings is a valid review).
* Each ``<finding>`` must carry a non-empty ``id`` attribute
  and non-empty text body.
* Finding ids are unique within the review.

Parsing is intentionally lenient on the outer wrapper — prose
preamble/postamble around the ``<review>`` block is ignored
(same lenient-extractor behavior :mod:`xml_sections` uses for
every tier). We only enforce structural rules *inside* the
root.
"""

from __future__ import annotations

from dataclasses import dataclass

from backend.graph.parsers.xml_sections import ParseError, extract_tag_tree


class ReviewXMLError(ValueError):
    """Raised when review output doesn't match the documented schema.

    Message is user-facing — surfaces on the tier detail as
    ``review_last_error`` and is readable in the retry-prompt
    banner without further formatting.
    """


@dataclass(frozen=True)
class ReviewFinding:
    id: str
    text: str


@dataclass(frozen=True)
class ParsedReview:
    handles_structure: tuple[ReviewFinding, ...]
    architectural_decisions: tuple[ReviewFinding, ...]


_HANDLES_SECTION = "handles-structure"
_ARCH_SECTION = "architectural-decisions"


def parse_review(raw: str) -> ParsedReview:
    """Parse + validate a ``<review>`` XML block.

    Raises :class:`ReviewXMLError` with a user-readable message
    if the output doesn't match the schema. Callers treat the
    exception the same way they treat ``ReviewError`` from the
    :mod:`_bootstrap_review` runner: the review job fails, the
    user can retry.
    """
    try:
        root = extract_tag_tree(raw, "review")
    except ParseError as e:
        raise ReviewXMLError(str(e)) from e

    sections = {s: root.find_all(s) for s in (_HANDLES_SECTION, _ARCH_SECTION)}
    for name, matches in sections.items():
        if len(matches) == 0:
            raise ReviewXMLError(f"<review> missing required <{name}> section")
        if len(matches) > 1:
            raise ReviewXMLError(
                f"<review> has {len(matches)} <{name}> sections; expected exactly 1"
            )

    handles = _extract_findings(sections[_HANDLES_SECTION][0], section=_HANDLES_SECTION)
    arch = _extract_findings(sections[_ARCH_SECTION][0], section=_ARCH_SECTION)

    seen: set[str] = set()
    for f in (*handles, *arch):
        if f.id in seen:
            raise ReviewXMLError(f"duplicate finding id {f.id!r} in review")
        seen.add(f.id)

    return ParsedReview(handles_structure=handles, architectural_decisions=arch)


def _extract_findings(section_node, *, section: str) -> tuple[ReviewFinding, ...]:  # type: ignore[no-untyped-def]
    findings: list[ReviewFinding] = []
    for idx, child in enumerate(section_node.find_all("finding"), start=1):
        finding_id = (child.attrs.get("id") or "").strip()
        if not finding_id:
            raise ReviewXMLError(f"<finding> #{idx} in <{section}> missing required id attribute")
        text = child.text.strip()
        if not text:
            raise ReviewXMLError(f"<finding id={finding_id!r}> in <{section}> has empty body")
        findings.append(ReviewFinding(id=finding_id, text=text))
    return tuple(findings)
