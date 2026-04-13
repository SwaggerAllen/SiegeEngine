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

    ``group_label`` is the enclosing ``<group>``'s ``<name>`` if
    the feature was inside one, or ``None`` for ungrouped
    features. ``is_implicit`` is ``True`` when the ``<feature>``
    carried an ``<implicit/>`` marker, signalling that the LLM
    inferred it as obviously-necessary rather than finding it in
    the user's input doc.
    """

    name: str
    intent: str
    group_label: str | None = None
    is_implicit: bool = False


_FEATURE_ALLOWED_CHILDREN = {"name", "intent", "implicit"}
_FEATURES_ALLOWED_CHILDREN = {"feature", "group"}
_GROUP_ALLOWED_CHILDREN = {"name", "feature"}


def validate_features(tree: TagNode) -> list[Feature]:
    """Validate a parsed ``<features>`` tree and return its features.

    Shape:

    * ``tree.tag`` must be exactly ``"features"``.
    * ``<features>`` may contain a mix of ``<feature>`` entries
      (ungrouped) and ``<group>`` blocks (each holding one or more
      ``<feature>`` entries).
    * There must be at least one ``<feature>`` overall (grouped
      or ungrouped).
    * Unknown tags at any level are rejected.
    * Each ``<feature>`` contains exactly one ``<name>`` and
      exactly one ``<intent>``. Both must be non-empty after
      stripping. An optional ``<implicit/>`` marker flags the
      feature as LLM-inferred.
    * Each ``<group>`` contains exactly one ``<name>`` (the group
      label) and at least one ``<feature>``. Groups do not nest —
      a ``<group>`` inside a ``<group>`` is rejected.

    The returned list is **flat** in document order: grouped and
    ungrouped features appear in the order they were written,
    with each ``Feature.group_label`` reflecting its source
    ``<group>`` (or ``None`` if ungrouped).

    Raises :class:`ValidationError` on the first problem found,
    with a message naming the offending tag path.
    """
    if tree.tag != "features":
        raise ValidationError(
            f"Expected root tag <features>, got <{tree.tag}>. "
            "Wrap the feature list in a single <features>...</features> block."
        )

    # Reject unknown children at the features level. Only
    # <feature> and <group> are permitted.
    for child in tree.children:
        if child.tag not in _FEATURES_ALLOWED_CHILDREN:
            raise ValidationError(
                f"<features> contains an unexpected child <{child.tag}>. "
                "Only <feature> entries and <group> blocks are allowed at "
                "this level."
            )

    result: list[Feature] = []
    feature_index = 0  # flat position across groups + ungrouped
    for child in tree.children:
        if child.tag == "feature":
            result.append(_validate_feature(child, feature_index, group_label=None))
            feature_index += 1
        elif child.tag == "group":
            group_label, group_features = _validate_group(child, feature_index)
            result.extend(group_features)
            feature_index += len(group_features)

    if not result:
        raise ValidationError(
            "<features> block contains no <feature> entries. "
            "Every project must have at least one feature."
        )

    return result


def _validate_group(node: TagNode, base_index: int) -> tuple[str, list[Feature]]:
    """Validate a ``<group>`` block and return ``(label, [Feature, ...])``.

    ``base_index`` is the flat feature index the first child
    feature will take — used only for error messages to help the
    LLM locate the problem in a retry prompt.
    """
    # Reject unknown children inside a group.
    for child in node.children:
        if child.tag not in _GROUP_ALLOWED_CHILDREN:
            raise ValidationError(
                f"<group> contains an unexpected child <{child.tag}>. "
                "Only <name> and <feature> entries are allowed inside a <group>. "
                "Groups do not nest."
            )

    name_children = node.find_all("name")
    if len(name_children) == 0:
        raise ValidationError(
            "<group> is missing a <name> child. Every group must have "
            "exactly one <name> identifying the grouping theme."
        )
    if len(name_children) > 1:
        raise ValidationError(
            f"<group> has {len(name_children)} <name> children; exactly one is required."
        )

    label = name_children[0].text
    if not label:
        raise ValidationError(
            "<group> has an empty <name>. The group name must be a short "
            'label identifying the theme (e.g. "User Management").'
        )

    feature_children = node.find_all("feature")
    if not feature_children:
        raise ValidationError(
            f'<group> "{label}" contains no <feature> entries. A group '
            "with no features is meaningless — inline the features directly "
            "under <features> or add features to the group."
        )

    features: list[Feature] = []
    for offset, feature_node in enumerate(feature_children):
        features.append(
            _validate_feature(
                feature_node,
                base_index + offset,
                group_label=label,
            )
        )
    return label, features


def _validate_feature(node: TagNode, index: int, *, group_label: str | None) -> Feature:
    """Validate a single ``<feature>`` entry and return its ``Feature``.

    ``index`` is the flat position of this feature across the
    whole ``<features>`` block — used in error messages to help
    the LLM locate the problem. ``group_label`` is propagated from
    the enclosing ``<group>``, or ``None`` when the feature sits
    directly under ``<features>``.
    """
    pos = f"<feature> at position {index}"

    # Reject unknown children inside a feature. <implicit/> is a
    # self-closing marker with no text or children of its own.
    for child in node.children:
        if child.tag not in _FEATURE_ALLOWED_CHILDREN:
            raise ValidationError(
                f"{pos} contains an unexpected child <{child.tag}>. "
                "Only <name>, <intent>, and an optional <implicit/> marker "
                "are allowed inside a <feature>."
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

    implicit_children = node.find_all("implicit")
    if len(implicit_children) > 1:
        raise ValidationError(
            f"{pos} has {len(implicit_children)} <implicit/> markers; at most one is allowed."
        )
    is_implicit = len(implicit_children) == 1

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

    return Feature(
        name=name_text,
        intent=intent_text,
        group_label=group_label,
        is_implicit=is_implicit,
    )


# ── Requirements (Phase 3: reqs → resp_*) ────────────────────────────


@dataclass(frozen=True)
class Responsibility:
    """A single validated responsibility from a ``<requirements>`` block.

    ``name`` is the short identifier (2–5 words, title case
    expected). ``intent`` is the paragraph-length description of
    the responsibility's role and scope. Both are non-empty and
    already whitespace-stripped at their outer edges.
    """

    name: str
    intent: str


_REQUIREMENTS_ALLOWED_CHILDREN = {"responsibility"}
_RESPONSIBILITY_ALLOWED_CHILDREN = {"name", "intent"}


def validate_requirements(tree: TagNode) -> list[Responsibility]:
    """Validate a parsed ``<requirements>`` tree and return its entries.

    Shape:

    * ``tree.tag`` must be exactly ``"requirements"``.
    * ``<requirements>`` contains one or more ``<responsibility>``
      entries. No other tags at this level.
    * Each ``<responsibility>`` contains exactly one ``<name>`` and
      exactly one ``<intent>``. Both must be non-empty after
      stripping. No other tags inside.
    * At least one ``<responsibility>`` must be present.

    Parallel shape to :func:`validate_features`: same general
    layout (one root, a flat list of structured children, each
    child has a name + intent), different tag vocabulary. Error
    messages name the offending tag path so the parse-validate
    retry loop can feed the problem back to the LLM.
    """
    if tree.tag != "requirements":
        raise ValidationError(
            f"Expected root tag <requirements>, got <{tree.tag}>. "
            "Wrap the responsibility list in a single <requirements>...</requirements> block."
        )

    for child in tree.children:
        if child.tag not in _REQUIREMENTS_ALLOWED_CHILDREN:
            raise ValidationError(
                f"<requirements> contains an unexpected child <{child.tag}>. "
                "Only <responsibility> entries are allowed at this level."
            )

    result: list[Responsibility] = []
    for index, child in enumerate(tree.children):
        result.append(_validate_responsibility(child, index))

    if not result:
        raise ValidationError(
            "<requirements> block contains no <responsibility> entries. "
            "Every project must have at least one top-level responsibility."
        )

    return result


def _validate_responsibility(node: TagNode, index: int) -> Responsibility:
    """Validate a single ``<responsibility>`` entry."""
    pos = f"<responsibility> at position {index}"

    for child in node.children:
        if child.tag not in _RESPONSIBILITY_ALLOWED_CHILDREN:
            raise ValidationError(
                f"{pos} contains an unexpected child <{child.tag}>. "
                "Only <name> and <intent> are allowed inside a <responsibility>."
            )

    name_children = node.find_all("name")
    if len(name_children) == 0:
        raise ValidationError(
            f"{pos} is missing a <name> child. Every responsibility must have exactly one <name>."
        )
    if len(name_children) > 1:
        raise ValidationError(
            f"{pos} has {len(name_children)} <name> children; exactly one is required."
        )

    intent_children = node.find_all("intent")
    if len(intent_children) == 0:
        raise ValidationError(
            f"{pos} is missing an <intent> child. Every responsibility "
            "must have exactly one <intent>."
        )
    if len(intent_children) > 1:
        raise ValidationError(
            f"{pos} has {len(intent_children)} <intent> children; exactly one is required."
        )

    name_text = name_children[0].text
    if not name_text:
        raise ValidationError(
            f"{pos} has an empty <name>. The responsibility name "
            "must be a short identifier, typically 2–5 words in title case."
        )

    intent_text = intent_children[0].text
    if not intent_text:
        raise ValidationError(
            f"{pos} has an empty <intent>. The responsibility intent "
            "must be a short paragraph describing the role and scope."
        )

    return Responsibility(name=name_text, intent=intent_text)
