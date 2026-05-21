"""Parsers ported from ``backend/graph/parsers``.

- ``xml_sections``: lenient BS4-based tag-tree extractor (verbatim).
- ``review_xml``: AI-review XML parser + ``ParsedReview`` dataclass
  (verbatim except for the import path).
- ``body_sections``: NEW — splits a body.md into named sections. See
  ``siege.fragments.parse_body_sections``.

The big ``validators.py`` (~4K lines, per-tier XML grammar checkers)
is not yet ported. It's a clean port — all pure-text validators — and
moves into the per-tier ``validate_artifact`` paths when the
validation gate ships.
"""
