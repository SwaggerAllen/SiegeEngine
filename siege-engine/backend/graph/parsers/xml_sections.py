"""Lenient BS4-based tag-tree extractor for LLM-generated output.

LLMs emit "XML-ish" output that's not strict XML: unescaped ``&``
and ``<`` inside content, prose preamble/postamble around the
structured block, whitespace noise, the occasional smart quote.
Strict XML parsers choke on all of this and produce retry storms
where the LLM is asked to fix cosmetic problems it's not well-
positioned to fix.

This module uses BeautifulSoup 4 with the stdlib ``html.parser``
backend — lenient enough for the LLM's output, and zero new
compiled dependencies.

**Scope of "parse success":**

* The input must contain an opening and closing ``<root_tag>`` pair
  somewhere in its text.
* The content inside that pair is extracted as a hierarchical
  ``TagNode`` tree.
* Prose outside the root tag is ignored.
* Tag nesting is preserved.
* Text inside tags is preserved, stripped of outer whitespace.

**What we deliberately do NOT do here:**

* Validate specific structural invariants ("features has at least
  one feature", "feature has exactly one name"). That's the job
  of callers using :mod:`backend.graph.parsers.validators`.
* Escape or normalize content text — callers get it as-is.
* Pretty-print or round-trip the parsed tree back to text.

Parse errors raised here are only for the catastrophic cases: the
root tag isn't present anywhere, or the input isn't even a string.
Everything else is a validator concern.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from bs4 import BeautifulSoup


class ParseError(ValueError):
    """Raised when the parser cannot find the expected root tag at all.

    Message is suitable for feeding back into a retry prompt — it
    names the tag that was expected and says it wasn't found.
    """


@dataclass
class TagNode:
    """A node in the parsed tag tree.

    Each node has:

    * ``tag`` — the tag name (e.g. ``"features"``, ``"feature"``).
    * ``text`` — direct text content *of this tag*, stripped. Empty
      string if the tag is purely structural (only has children).
      For leaves like ``<name>Billing</name>``, this is the leaf
      content.
    * ``children`` — child ``TagNode``s in document order.

    Mixed content (text interleaved with tags) is flattened: the
    ``text`` field is whatever direct text exists between the
    opening tag and the first child / closing tag, stripped. This
    is fine for our grammar because all of our target structures
    are either text-only leaves (``<name>``) or pure containers
    (``<features>``, ``<feature>``); we never have real mixed
    content.
    """

    tag: str
    text: str = ""
    children: list["TagNode"] = field(default_factory=list)

    def find_all(self, tag: str) -> list["TagNode"]:
        """Return immediate children with the given tag name."""
        return [c for c in self.children if c.tag == tag]

    def find(self, tag: str) -> "TagNode | None":
        """Return the first immediate child with the given tag name, or None."""
        for c in self.children:
            if c.tag == tag:
                return c
        return None


def extract_tag_tree(raw: str, root_tag: str) -> TagNode:
    """Extract a ``TagNode`` tree rooted at the first ``<root_tag>`` in ``raw``.

    The parser is lenient: it finds the first opening/closing pair
    of ``root_tag`` anywhere in the input, tolerates prose
    preamble/postamble, tolerates unescaped ``&`` and ``<`` inside
    content (via ``html.parser``'s leniency), and strips surrounding
    whitespace from the extracted text.

    Raises :class:`ParseError` only if ``root_tag`` isn't found at
    all, or if ``raw`` isn't a string. All other structural
    concerns are validator territory.
    """
    if not isinstance(raw, str):
        raise ParseError(f"Parser input must be a string, got {type(raw).__name__}")

    soup = BeautifulSoup(raw, "html.parser")
    root = soup.find(root_tag)
    if root is None:
        raise ParseError(
            f"Expected a <{root_tag}> block in the output, but none was found. "
            "Wrap the structured part of your response in "
            f"<{root_tag}>...</{root_tag}> and try again."
        )

    return _bs_to_tag_node(root)


def _bs_to_tag_node(element) -> TagNode:  # type: ignore[no-untyped-def]
    """Convert a BeautifulSoup element into a :class:`TagNode` tree.

    Walks the element's direct contents, separating child tags from
    direct text. Direct text is joined and stripped — leading/
    trailing whitespace is removed, but interior whitespace
    (including newlines between sentences of a paragraph) is
    preserved as-is.
    """
    text_fragments: list[str] = []
    children: list[TagNode] = []

    for node in element.contents:
        # html.parser gives us either Tag objects or NavigableString
        # objects. Tag objects have a .name attribute that's a real
        # string; NavigableString objects have .name == None.
        name = getattr(node, "name", None)
        if name is None:
            text = str(node)
            if text:
                text_fragments.append(text)
        else:
            children.append(_bs_to_tag_node(node))

    direct_text = "".join(text_fragments).strip()
    return TagNode(tag=element.name, text=direct_text, children=children)
