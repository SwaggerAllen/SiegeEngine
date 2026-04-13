"""Parsers and validators for LLM-generated tagged output.

v2 uses tag-based structured output (``<features>``, ``<feature>``,
``<public-surface>``, etc.) because it parses more reliably out of
Claude than free-form markdown, lets us display the structure to
the user verbatim, and gives us clean retry feedback on malformed
output.

This package has two halves:

* :mod:`backend.graph.parsers.xml_sections` — a lenient BS4-based
  tag-tree extractor. Tolerates prose preamble/postamble around the
  structured block, unescaped ``&`` or ``<`` inside tag content,
  whitespace noise, and most of the other sloppiness LLMs produce.
  Only fails when the output is catastrophically missing the
  structure we asked for.
* :mod:`backend.graph.parsers.validators` — callers-specific
  structural validators layered on top of the parser. Each caller
  (Phase 2 expansion, Phase 4 component arch, …) supplies its own
  tag vocabulary and its own invariants. Validator errors are the
  signal that feeds back into the parse-validate retry loop.

The two-layer split means the parser is lenient about format drift
(no spurious retries on harmless LLM quirks) while the validators
are strict about semantic correctness (catches the errors we want
to retry on, with messages suitable for feeding back into the next
LLM call).
"""

from backend.graph.parsers.xml_sections import (
    ParseError,
    TagNode,
    extract_tag_tree,
)

__all__ = [
    "ParseError",
    "TagNode",
    "extract_tag_tree",
]
