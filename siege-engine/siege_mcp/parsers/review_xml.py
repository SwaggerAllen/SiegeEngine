"""Parser + validator for the Phase 8 AI-review XML format.

The review handler calls :func:`parse_review` on the CLI output
before committing it. Malformed reviews raise :class:`ReviewXMLError`
— the review job marks itself failed, the frontend surfaces the
error, and the user can hit "Retry review" to try again.

Schema (enforced by this module):

.. code-block:: xml

    <review>
      <intro>Short prose summary for the user — "how close to
      finished" read. Display-only; does not feed regens.</intro>
      <score>73</score>
      <handles-structure>
        <finding id="h1">Plain prose finding.</finding>
        <finding id="h2">...</finding>
      </handles-structure>
      <architectural-decisions>
        <finding id="a1">...</finding>
      </architectural-decisions>
    </review>

* ``<intro>`` is required and non-empty. It's a user-facing
  summary (the "how close is this to finished" hint) that does
  NOT participate in the auto-revision feedback loop or the
  user-initiated Reject-&-Regenerate selection path.
* ``<score>`` is required and must parse as an integer in
  ``[0, 100]``. Same 0–100 "ready-to-approve" scale across all
  tiers; displayed alongside the intro.
* Both ``<handles-structure>`` and ``<architectural-decisions>``
  sections must be present.
* Either section may be empty (no findings is a valid review —
  a high score with zero findings is the canonical "ready to
  approve" shape).
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

from siege_mcp.parsers.xml_sections import ParseError, extract_tag_tree


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
    intro: str
    score: int
    handles_structure: tuple[ReviewFinding, ...]
    architectural_decisions: tuple[ReviewFinding, ...]


_INTRO_SECTION = "intro"
_SCORE_SECTION = "score"
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

    sections = {
        s: root.find_all(s)
        for s in (_INTRO_SECTION, _SCORE_SECTION, _HANDLES_SECTION, _ARCH_SECTION)
    }
    for name, matches in sections.items():
        if len(matches) == 0:
            raise ReviewXMLError(f"<review> missing required <{name}> section")
        if len(matches) > 1:
            raise ReviewXMLError(
                f"<review> has {len(matches)} <{name}> sections; expected exactly 1"
            )

    intro = (sections[_INTRO_SECTION][0].text or "").strip()
    if not intro:
        raise ReviewXMLError("<review> has an empty <intro>; one or two short paragraphs required")

    score_text = (sections[_SCORE_SECTION][0].text or "").strip()
    if not score_text:
        raise ReviewXMLError("<review> has an empty <score>; expected an integer 0-100")
    try:
        score = int(score_text)
    except ValueError as e:
        raise ReviewXMLError(f"<score> must be an integer 0-100, got {score_text!r}") from e
    if not 0 <= score <= 100:
        raise ReviewXMLError(f"<score> out of range 0-100: {score}")

    handles = _extract_findings(sections[_HANDLES_SECTION][0], section=_HANDLES_SECTION)
    arch = _extract_findings(sections[_ARCH_SECTION][0], section=_ARCH_SECTION)

    seen: set[str] = set()
    for f in (*handles, *arch):
        if f.id in seen:
            raise ReviewXMLError(f"duplicate finding id {f.id!r} in review")
        seen.add(f.id)

    return ParsedReview(
        intro=intro,
        score=score,
        handles_structure=handles,
        architectural_decisions=arch,
    )


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
