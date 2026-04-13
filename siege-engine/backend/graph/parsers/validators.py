"""Structural validators for parsed tag trees.

The lenient parser in :mod:`backend.graph.parsers.xml_sections`
extracts whatever tree it can find. These validators layer on top
and enforce the per-caller structural invariants — "this kind of
tree must have exactly these children, with exactly these tags,
with non-empty text in these leaf positions."

Validator errors are the signal that feeds back into the parse-
validate retry loop. The error messages are deliberately worded
to make sense as LLM feedback: they name the tag path that was
wrong and say what was expected.

Each caller adds its own ``validate_*`` function here:

* :func:`validate_features` — for the expansion → feat_* mint path
  (Phase 2).
* ``validate_arch_doc`` (future) — for the component arch doc
  parseable-sections path (Phase 4).
* And so on.
"""

from __future__ import annotations

from dataclasses import dataclass

from backend.graph.parsers.xml_sections import TagNode


class ValidationError(ValueError):
    """Raised when a parsed tag tree fails structural validation.

    Message is suitable for feeding back into a retry prompt —
    names the tag path and explains what's wrong.
    """


# ── Features (Phase 2: expansion → feat_*) ───────────────────────────


@dataclass(frozen=True)
class Feature:
    """A single validated feature from an expansion's <features> block.

    ``name`` is the short identifier (2–5 words, title case
    expected). ``intent`` is the paragraph-length description of
    what the feature does. Both are non-empty and already
    whitespace-stripped at their outer edges.
    """

    name: str
    intent: str


_FEATURE_ALLOWED_CHILDREN = {"name", "intent"}
_FEATURES_ALLOWED_CHILDREN = {"feature"}


def validate_features(tree: TagNode) -> list[Feature]:
    """Validate a parsed ``<features>`` tree and return its features.

    Rules:

    * ``tree.tag`` must be exactly ``"features"``.
    * It must contain at least one ``<feature>`` child.
    * Unknown tags at the ``<features>`` level are rejected.
    * Each ``<feature>`` must contain exactly one ``<name>`` and
      exactly one ``<intent>``, with no other child tags.
    * Both ``<name>`` and ``<intent>`` must have non-empty text
      after stripping.

    Raises :class:`ValidationError` on the first problem found,
    with a message naming the offending tag path.
    """
    if tree.tag != "features":
        raise ValidationError(
            f"Expected root tag <features>, got <{tree.tag}>. "
            "Wrap the feature list in a single <features>...</features> block."
        )

    # Reject unknown children at the features level.
    for child in tree.children:
        if child.tag not in _FEATURES_ALLOWED_CHILDREN:
            raise ValidationError(
                f"<features> contains an unexpected child <{child.tag}>. "
                "Only <feature> entries are allowed at this level."
            )

    feature_children = tree.find_all("feature")
    if not feature_children:
        raise ValidationError(
            "<features> block contains no <feature> entries. "
            "Every project must have at least one feature."
        )

    result: list[Feature] = []
    for idx, feature_node in enumerate(feature_children):
        result.append(_validate_feature(feature_node, idx))
    return result


def _validate_feature(node: TagNode, index: int) -> Feature:
    """Validate a single ``<feature>`` entry and return its ``Feature``."""
    pos = f"<feature> at position {index}"

    # Reject unknown children inside a feature.
    for child in node.children:
        if child.tag not in _FEATURE_ALLOWED_CHILDREN:
            raise ValidationError(
                f"{pos} contains an unexpected child <{child.tag}>. "
                "Only <name> and <intent> are allowed inside a <feature>."
            )

    name_children = node.find_all("name")
    if len(name_children) == 0:
        raise ValidationError(
            f"{pos} is missing a <name> child. Every feature must have exactly one <name>."
        )
    if len(name_children) > 1:
        raise ValidationError(
            f"{pos} has {len(name_children)} <name> children; exactly one is required."
        )

    intent_children = node.find_all("intent")
    if len(intent_children) == 0:
        raise ValidationError(
            f"{pos} is missing an <intent> child. Every feature must have exactly one <intent>."
        )
    if len(intent_children) > 1:
        raise ValidationError(
            f"{pos} has {len(intent_children)} <intent> children; exactly one is required."
        )

    name_text = name_children[0].text
    if not name_text:
        raise ValidationError(
            f"{pos} has an empty <name>. The feature name must be "
            "a short identifier, typically 2–5 words in title case."
        )

    intent_text = intent_children[0].text
    if not intent_text:
        raise ValidationError(
            f"{pos} has an empty <intent>. The feature intent must "
            "be a short paragraph describing what the feature does."
        )

    return Feature(name=name_text, intent=intent_text)
