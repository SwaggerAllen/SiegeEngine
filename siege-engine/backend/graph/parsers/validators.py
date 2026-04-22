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

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from backend.graph.parsers.xml_sections import TagNode, extract_tag_tree


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

    # Enforce feature name uniqueness across the whole <features>
    # block. Downstream passes reference features by name (the
    # vocabulary layer is the first such consumer), so duplicates
    # would make references ambiguous.
    seen_names: set[str] = set()
    for feature in result:
        if feature.name in seen_names:
            raise ValidationError(
                f"<features> contains two features with the same name "
                f"{feature.name!r}. Feature names must be unique across "
                "the entire <features> block — downstream passes "
                "reference features by name, and duplicates make those "
                "references ambiguous."
            )
        seen_names.add(feature.name)

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
class Deferral:
    """One ``<defers to="X">phrase</defers>`` entry from a responsibility.

    ``scope`` is the short noun phrase this responsibility explicitly
    does **not** own; ``to`` is the name of the responsibility that
    owns the phrase instead. Cross-reference is validated — ``to``
    must match another responsibility's ``<name>`` in the same
    document (catches typos in the retry loop rather than at
    sysarch time).
    """

    scope: str
    to: str


@dataclass(frozen=True)
class Responsibility:
    """A single validated responsibility from a ``<requirements>`` block.

    ``name`` is the short identifier (2–5 words, title case
    expected). The prose intent that used to live here has been
    replaced by three structured fields that together carry the
    same signal with roughly 70% fewer tokens:

    * ``scope`` — short noun phrases naming the system-side
      concerns this responsibility owns. Primary dedup target:
      no two responsibilities may share a normalized scope entry.
    * ``does_not_own`` — structured boundary disclaimers. Each
      :class:`Deferral` names a scope phrase this responsibility
      explicitly defers and the name of the responsibility that
      owns it instead. Replaces the prose "does not cover X
      because Y" clauses the old intent paragraphs carried.
    * ``failure_surface`` — one sentence describing what breaks
      when this responsibility malfunctions.

    ``owns`` and ``supports`` split feature ownership (unchanged
    from the previous grammar). ``owns`` is the primary
    system-side owner — every feature appears in exactly one
    responsibility's ``<owns>`` across the doc. ``supports`` is
    zero-or-more per feature and captures infrastructure or
    composition coverage.

    ``covers`` is a convenience property returning
    ``owns + supports`` for consumers that want the flat feature
    list without the ownership axis.
    """

    name: str
    scope: tuple[str, ...]
    does_not_own: tuple[Deferral, ...]
    failure_surface: str
    owns: tuple[str, ...]
    supports: tuple[str, ...]

    @property
    def covers(self) -> tuple[str, ...]:
        """Flat feature list: owns followed by supports, no dedup."""
        return self.owns + self.supports


_REQUIREMENTS_ALLOWED_CHILDREN = {"responsibility"}
_RESPONSIBILITY_ALLOWED_CHILDREN = {
    "name",
    "scope",
    "does-not-own",
    "failure-surface",
    "owns",
    "supports",
}
_SCOPE_ALLOWED_CHILDREN = {"item"}
_DOES_NOT_OWN_ALLOWED_CHILDREN = {"defers"}
_FEAT_LIST_ALLOWED_CHILDREN = {"feat"}


def validate_requirements(tree: TagNode, *, known_feature_ids: set[str]) -> list[Responsibility]:
    """Validate a parsed ``<requirements>`` tree and return its entries.

    Shape:

    * ``tree.tag`` must be exactly ``"requirements"``.
    * ``<requirements>`` contains one or more ``<responsibility>``
      entries. No other tags at this level.
    * Each ``<responsibility>`` contains exactly one ``<name>``,
      exactly one ``<intent>``, **and** either (a) one ``<owns>``
      block plus at most one ``<supports>`` block, or (b) one
      legacy ``<covers>`` block (accepted for backward
      compatibility with drafts authored before the ownership
      split).
    * ``<owns>`` / ``<supports>`` / ``<covers>`` each contain one
      or more ``<feat id="..."/>`` children. The ``id`` must match
      a known feature from ``known_feature_ids``. Unknown /
      missing IDs are parse errors that feed the retry loop.
    * **Single-owner rule:** every feature in ``known_feature_ids``
      must appear in exactly one responsibility's ``<owns>`` block
      across the whole document (legacy ``<covers>`` entries count
      as ``<owns>`` for this rule). Zero owners ⇒ coverage gap.
      Two or more owners ⇒ scope collision — the gate the review
      loop kept flagging by hand. Appearing in both ``<owns>`` and
      ``<supports>`` inside the same responsibility is disallowed
      (redundant — ``<owns>`` already covers it).
    * ``<supports>`` is multiplicity-free across responsibilities:
      a feature may appear in zero or many ``<supports>`` blocks,
      reflecting the "multiple responsibilities contribute
      infrastructure / composition to one user-visible feature"
      pattern that's legitimate under the rotation.

    Parallel shape to :func:`validate_features`: same general
    layout (one root, a flat list of structured children, each
    child has a name + intent), different tag vocabulary. The
    ownership / support distinction is what distinguishes it from
    its feature-expansion cousin: both collections feed the
    many-to-many edges emitted on approval, and single-owner is
    enforced here so the retry loop catches scope collisions
    before they land in the projection.
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
        result.append(_validate_responsibility(child, index, known_feature_ids=known_feature_ids))

    if not result:
        raise ValidationError(
            "<requirements> block contains no <responsibility> entries. "
            "Every project must have at least one top-level responsibility."
        )

    # Single-owner rule: every known feature must appear in
    # exactly one responsibility's <owns> block across the whole
    # doc. Two or more owners is a scope collision the review
    # loop used to flag by hand; zero owners is a coverage gap.
    owner_of: dict[str, list[str]] = {}
    for resp in result:
        for fid in resp.owns:
            owner_of.setdefault(fid, []).append(resp.name)

    duplicated = {fid: owners for fid, owners in owner_of.items() if len(owners) > 1}
    if duplicated:
        lines = sorted(
            f"  - {fid} owned by {', '.join(owners)}" for fid, owners in duplicated.items()
        )
        raise ValidationError(
            "<requirements> has features with multiple owners. "
            "Every feature must be listed in exactly one responsibility's "
            "<owns> block — put supporting responsibilities in <supports> "
            "instead so the primary owner is unambiguous. Offending "
            "features:\n" + "\n".join(lines)
        )

    covered_as_owned = set(owner_of.keys())
    # Features that appear only in <supports> (or nowhere) still
    # need an owner; report them explicitly so the retry prompt
    # can tell the LLM which owner is missing.
    missing_owner = sorted(known_feature_ids - covered_as_owned)
    if missing_owner:
        raise ValidationError(
            "<requirements> has features with no owner. "
            f"The following feature IDs do not appear in any <owns> block: "
            f"{', '.join(missing_owner)}. Every feature must have exactly "
            "one responsibility that owns it; listing it only in <supports> "
            "does not satisfy the rule."
        )

    # Scope dedup: no two responsibilities may share a normalized
    # <scope>/<item> phrase. This is the mechanical overlap check
    # the review loop kept flagging by hand — "both claim X" —
    # now expressed structurally at the scope level.
    scope_owner: dict[str, list[str]] = {}
    for resp in result:
        for phrase in resp.scope:
            scope_owner.setdefault(_normalize_scope(phrase), []).append(resp.name)
    scope_collisions = {phrase: owners for phrase, owners in scope_owner.items() if len(owners) > 1}
    if scope_collisions:
        lines = sorted(
            f"  - {phrase!r} claimed by {', '.join(owners)}"
            for phrase, owners in scope_collisions.items()
        )
        raise ValidationError(
            "<requirements> has scope phrases claimed by multiple "
            "responsibilities. Every <scope>/<item> must be owned by "
            "exactly one responsibility — if two responsibilities really "
            "do both own a concept, they are drawn too broadly or the "
            "phrase is too vague to disambiguate. Collapse or rephrase. "
            "Offending phrases:\n" + "\n".join(lines)
        )

    # <defers to="X"> cross-reference: every ``to`` must resolve
    # to another responsibility's name in the same document.
    # Catches typos ("Scheduler" vs "Reactive Scheduler") at
    # generation time rather than at sysarch-read time.
    known_names = {resp.name for resp in result}
    unresolved: list[str] = []
    for resp in result:
        for deferral in resp.does_not_own:
            if deferral.to not in known_names:
                unresolved.append(
                    f"{resp.name!r} defers {deferral.scope!r} "
                    f"to {deferral.to!r} (not a known responsibility)"
                )
    if unresolved:
        raise ValidationError(
            "<requirements> has <defers to=...> entries referencing "
            "unknown responsibilities. Every ``to`` attribute must match "
            "another responsibility's <name> exactly. Offending entries:\n"
            + "\n".join(f"  - {e}" for e in unresolved)
        )

    return result


def _validate_responsibility(
    node: TagNode, index: int, *, known_feature_ids: set[str]
) -> Responsibility:
    """Validate a single ``<responsibility>`` entry."""
    pos = f"<responsibility> at position {index}"

    for child in node.children:
        if child.tag not in _RESPONSIBILITY_ALLOWED_CHILDREN:
            raise ValidationError(
                f"{pos} contains an unexpected child <{child.tag}>. "
                "Allowed children: <name>, <scope>, <does-not-own> (optional), "
                "<failure-surface>, <owns>, <supports> (optional)."
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
    name_text = name_children[0].text
    if not name_text:
        raise ValidationError(
            f"{pos} has an empty <name>. The responsibility name "
            "must be a short identifier, typically 2–5 words in title case."
        )

    scope_children = node.find_all("scope")
    if len(scope_children) == 0:
        raise ValidationError(
            f"{pos} is missing a <scope> child. Every responsibility must "
            "have exactly one <scope> block listing the short noun phrases "
            "(one per <item>) that name the system-side concerns this "
            "responsibility owns."
        )
    if len(scope_children) > 1:
        raise ValidationError(
            f"{pos} has {len(scope_children)} <scope> children; exactly one is required."
        )
    scope_phrases = _validate_scope_block(scope_children[0], pos)

    failure_children = node.find_all("failure-surface")
    if len(failure_children) == 0:
        raise ValidationError(
            f"{pos} is missing a <failure-surface> child. Every responsibility "
            "must have exactly one <failure-surface> describing what breaks "
            "when this responsibility malfunctions (one sentence)."
        )
    if len(failure_children) > 1:
        raise ValidationError(
            f"{pos} has {len(failure_children)} <failure-surface> children; exactly one is required."  # noqa: E501
        )
    failure_surface_text = failure_children[0].text
    if not failure_surface_text:
        raise ValidationError(
            f"{pos} has an empty <failure-surface>. Name the concrete "
            "failure mode (data loss, invariant violation, silent degradation) "
            "in a single sentence."
        )

    does_not_own_children = node.find_all("does-not-own")
    if len(does_not_own_children) > 1:
        raise ValidationError(
            f"{pos} has {len(does_not_own_children)} <does-not-own> children; "
            "at most one is allowed."
        )
    if does_not_own_children:
        does_not_own = _validate_does_not_own_block(does_not_own_children[0], pos)
    else:
        does_not_own = ()

    owns_children = node.find_all("owns")
    if len(owns_children) == 0:
        raise ValidationError(
            f"{pos} is missing an <owns> child. Every responsibility "
            "must have exactly one <owns> block listing at least one "
            '<feat id="feat_..."/> child identifying the features it '
            "is the primary system-side owner of."
        )
    if len(owns_children) > 1:
        raise ValidationError(
            f"{pos} has {len(owns_children)} <owns> children; exactly one is required."
        )

    supports_children = node.find_all("supports")
    if len(supports_children) > 1:
        raise ValidationError(
            f"{pos} has {len(supports_children)} <supports> children; at most one is allowed."
        )

    owns = _validate_feat_list(
        owns_children[0],
        pos,
        tag_name="owns",
        allow_empty=False,
        known_feature_ids=known_feature_ids,
    )
    if supports_children:
        supports = _validate_feat_list(
            supports_children[0],
            pos,
            tag_name="supports",
            allow_empty=True,
            known_feature_ids=known_feature_ids,
        )
    else:
        supports = ()

    # Intra-responsibility redundancy: a feature listed in both
    # <owns> and <supports> of the same responsibility is a
    # contradiction — <owns> already covers it.
    redundant = sorted(set(owns) & set(supports))
    if redundant:
        raise ValidationError(
            f"{pos} lists the same feature(s) in both <owns> and <supports>: "
            f"{', '.join(redundant)}. Put each feature in exactly one of the "
            "two — <owns> implies supporting presence already."
        )

    return Responsibility(
        name=name_text,
        scope=scope_phrases,
        does_not_own=does_not_own,
        failure_surface=failure_surface_text,
        owns=owns,
        supports=supports,
    )


def _validate_scope_block(node: TagNode, parent_pos: str) -> tuple[str, ...]:
    """Validate a ``<scope>`` block and return its ordered phrases.

    Each ``<item>`` is a short noun phrase naming a system-side
    concern this responsibility owns. At least one entry is
    required; two responsibilities cannot share a scope entry
    (checked at the document level in :func:`validate_requirements`).
    """
    for child in node.children:
        if child.tag not in _SCOPE_ALLOWED_CHILDREN:
            raise ValidationError(
                f"{parent_pos} has a <scope> block containing an unexpected "
                f"child <{child.tag}>. Only <item>…</item> entries are allowed "
                "inside <scope>."
            )
    item_nodes = node.find_all("item")
    if not item_nodes:
        raise ValidationError(
            f"{parent_pos} has an empty <scope> block. Every responsibility "
            "must name at least one system-side concern it owns via "
            "<item>short noun phrase</item>."
        )
    phrases: list[str] = []
    seen: set[str] = set()
    for i, item in enumerate(item_nodes):
        text = item.text.strip() if item.text else ""
        if not text:
            raise ValidationError(
                f"{parent_pos} has an empty <item> at <scope> position {i}. "
                "Scope items must be short noun phrases (2–8 words, system-side)."
            )
        normalized = _normalize_scope(text)
        if normalized in seen:
            raise ValidationError(
                f"{parent_pos} has a duplicate <item> at <scope> position {i}: "
                f"{text!r}. Each scope phrase may appear at most once per "
                "responsibility."
            )
        seen.add(normalized)
        phrases.append(text)
    return tuple(phrases)


def _validate_does_not_own_block(node: TagNode, parent_pos: str) -> tuple[Deferral, ...]:
    """Validate a ``<does-not-own>`` block and return its deferral entries.

    Each child is a ``<defers to="Responsibility Name">scope phrase</defers>``
    entry. Both the phrase body and the ``to`` attribute must be
    non-empty; cross-references are resolved against the full
    responsibility list at the top-level validator.
    """
    for child in node.children:
        if child.tag not in _DOES_NOT_OWN_ALLOWED_CHILDREN:
            raise ValidationError(
                f"{parent_pos} has a <does-not-own> block containing an "
                f"unexpected child <{child.tag}>. Only "
                '<defers to="Other Responsibility">scope phrase</defers> '
                "entries are allowed."
            )
    defers_nodes = node.find_all("defers")
    entries: list[Deferral] = []
    for i, defers in enumerate(defers_nodes):
        phrase = defers.text.strip() if defers.text else ""
        to_name = (defers.attrs.get("to") or "").strip()
        if not phrase:
            raise ValidationError(
                f"{parent_pos} has an empty <defers> body at <does-not-own> "
                f"position {i}. Provide the short noun phrase being deferred."
            )
        if not to_name:
            raise ValidationError(
                f"{parent_pos} has a <defers> entry at <does-not-own> "
                f"position {i} with no ``to`` attribute. Every <defers> "
                'must carry to="Responsibility Name" naming the responsibility '
                "that owns the phrase instead."
            )
        entries.append(Deferral(scope=phrase, to=to_name))
    return tuple(entries)


def _normalize_scope(phrase: str) -> str:
    """Lowercase + collapse whitespace for cross-responsibility dedup."""
    return " ".join(phrase.lower().split())


def _validate_feat_list(
    node: TagNode,
    parent_pos: str,
    *,
    tag_name: str,
    allow_empty: bool,
    known_feature_ids: set[str],
) -> tuple[str, ...]:
    """Validate a ``<owns>`` or ``<supports>`` block and return its feature IDs.

    Both blocks share the same child grammar (``<feat id="..."/>``
    entries, unique within the block, each id drawn from the
    known-feature allowlist). ``<owns>`` must be non-empty;
    ``<supports>`` may be empty when the responsibility has no
    supporting features to declare.

    ``parent_pos`` is the position marker of the enclosing
    responsibility — used in error messages so the retry prompt
    can direct the LLM to the right responsibility. ``tag_name``
    is ``"owns"`` or ``"supports"`` and surfaces in errors so the
    LLM knows which block to fix.
    """
    for child in node.children:
        if child.tag not in _FEAT_LIST_ALLOWED_CHILDREN:
            raise ValidationError(
                f"{parent_pos} has a <{tag_name}> block containing an unexpected "
                f'child <{child.tag}>. Only <feat id="feat_..."/> entries '
                f"are allowed inside <{tag_name}>."
            )

    feat_nodes = node.find_all("feat")
    if not feat_nodes:
        if allow_empty:
            return ()
        raise ValidationError(
            f"{parent_pos} has an empty <{tag_name}> block. Every responsibility "
            f"must own at least one feature — list the feature IDs via "
            f'<feat id="feat_..."/> children. If this responsibility has '
            "no features to own, it probably shouldn't be a top-level "
            "responsibility at all."
        )

    ids: list[str] = []
    seen: set[str] = set()
    for i, feat_node in enumerate(feat_nodes):
        fid = feat_node.attrs.get("id", "").strip()
        if not fid:
            raise ValidationError(
                f"{parent_pos} has a <feat> entry at <{tag_name}> position {i} "
                "with no id attribute. Every <feat> must carry an "
                'id="feat_..." attribute referencing a known feature.'
            )
        if fid in seen:
            raise ValidationError(
                f"{parent_pos} has a <feat> entry at <{tag_name}> position {i} "
                f"listing duplicate feature id {fid!r}. Each feature id may "
                f"appear at most once per <{tag_name}> block."
            )
        seen.add(fid)
        if fid not in known_feature_ids:
            raise ValidationError(
                f"{parent_pos} has a <feat> entry at <{tag_name}> position {i} "
                f"referencing unknown feature id {fid!r}. Valid feature "
                f"IDs for this project: {', '.join(sorted(known_feature_ids))}. "
                "Only reference IDs from the feature list provided in the prompt."
            )
        ids.append(fid)

    return tuple(ids)


# ── System architecture (Phase 3 stage 2: sysarch → comp_*/policy_*/edges) ──


@dataclass(frozen=True)
class Component:
    """A single validated component entry from a ``<sysarch>`` block.

    ``alias`` is the local reference used inside this sysarch
    document's ``<dependencies>`` and ``<domain-parent>`` edges.
    It is *not* a node ID — the mint handler resolves aliases to
    real ``comp_*`` IDs at approval time. ``resp_refs`` carries
    the top-level ``resp_*`` IDs assigned to this component; the
    1:1 resp→comp invariant is enforced at the ``<sysarch>`` root
    level so every known top-level resp lands in exactly one
    component's list.
    """

    alias: str
    name: str
    kind: Literal["domain", "presentational"]
    role: str
    api_intent: str
    resp_refs: tuple[str, ...]
    is_foundation: bool


@dataclass(frozen=True)
class Policy:
    """A single validated policy entry from a ``<policies>`` block.

    ``required_resp_id`` is the top-level ``resp_*`` ID that must
    be fulfilled at every site the ``trigger`` phrase matches.
    The mint handler stores the whole dataclass as an XML blob
    on the minted ``policy_*`` node's ``content`` column; comparch
    (Phase 4) re-parses it when deciding which components the
    policy applies to.

    Phase-11 followup B8: ``required_resp_id`` is now optional
    (``None``) for universal-scope policies — AGPL license
    obligations, organization-wide conventions — that don't
    have a single enforcing responsibility. The application
    pass emits ``policy_application`` edges to every candidate
    component in scope when ``required_resp_id`` is None.
    """

    name: str
    trigger: str
    required_resp_id: str | None
    rationale: str


@dataclass(frozen=True)
class DepEdge:
    """A ``<dep from=... to=.../>`` entry inside ``<dependencies>``.

    Both endpoints are component aliases within this sysarch doc.
    The mint handler translates them to real ``comp_*`` IDs when
    emitting ``EdgeCreated`` events.
    """

    from_alias: str
    to_alias: str


@dataclass(frozen=True)
class DomainParentEdge:
    """A ``<parent from=... to=.../>`` entry inside ``<domain-parent>``.

    ``from_alias`` is a presentational component; ``to_alias`` is
    a domain component. Both are local aliases that the mint
    handler resolves.
    """

    from_alias: str
    to_alias: str


@dataclass(frozen=True)
class SysarchDoc:
    """The full validated sysarch output as structured data.

    Mint handler consumes this rather than re-walking the parsed
    ``TagNode`` tree, which keeps alias-based concerns in the
    validator and ID-based concerns in the mint handler.
    """

    techspec: str
    components: tuple[Component, ...]
    policies: tuple[Policy, ...]
    deps: tuple[DepEdge, ...]
    domain_parents: tuple[DomainParentEdge, ...]


# Alias syntax: lowercase letter, then up to 31 lowercase
# alphanumerics or underscores. Deterministic, fits in a path
# segment, easy for the LLM to honour.
_ALIAS_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")

_SYSARCH_ALLOWED_CHILDREN = {
    "techspec",
    "components",
    "policies",
    "dependencies",
    "domain-parent",
}
_SYSARCH_REQUIRED_ORDER = (
    "techspec",
    "components",
    "policies",
    "dependencies",
    "domain-parent",
)
_COMPONENT_ALLOWED_CHILDREN = {
    "name",
    "kind",
    "role",
    "api-intent",
    "responsibilities",
    "foundation",
}
_RESPONSIBILITIES_ALLOWED_CHILDREN = {"resp"}
_POLICIES_ALLOWED_CHILDREN = {"policy"}
_POLICY_ALLOWED_CHILDREN = {"name", "trigger", "required", "rationale"}
_DEPENDENCIES_ALLOWED_CHILDREN = {"dep"}
_DOMAIN_PARENT_ALLOWED_CHILDREN = {"parent"}


def validate_sysarch(
    tree: TagNode,
    *,
    known_top_level_resp_ids: set[str],
) -> SysarchDoc:
    """Validate a parsed ``<sysarch>`` tree and return a SysarchDoc.

    Enforces the full shape described in
    :mod:`backend.graph.prompts.sysarch`: single root, five
    sections in order, alias syntax + uniqueness, component field
    completeness, exactly-one-foundation, exactly-one-assignment
    per top-level resp, known resp IDs in ``<responsibilities>``
    and policy ``<required>``, policy sub-grammar, dep acyclicity,
    domain-parent direction.

    ``known_top_level_resp_ids`` is the set of all top-level
    ``resp_*`` IDs minted by ``reqs_*`` approval — collected from
    the DB before the retry loop starts. The validator cross-
    checks every resp reference against this set and enforces
    complete coverage.
    """
    if tree.tag != "sysarch":
        raise ValidationError(
            f"Expected root tag <sysarch>, got <{tree.tag}>. "
            "Wrap the system architecture output in a single "
            "<sysarch>...</sysarch> block."
        )

    # Section order enforcement — each expected section must
    # appear in the right position. Missing or reordered sections
    # get a specific error so the LLM can fix on retry.
    section_map: dict[str, TagNode] = {}
    for child in tree.children:
        if child.tag not in _SYSARCH_ALLOWED_CHILDREN:
            raise ValidationError(
                f"<sysarch> contains an unexpected child <{child.tag}>. "
                f"Allowed children are: {sorted(_SYSARCH_ALLOWED_CHILDREN)}."
            )
        if child.tag in section_map:
            raise ValidationError(
                f"<sysarch> contains more than one <{child.tag}> section; "
                "exactly one of each section is required."
            )
        section_map[child.tag] = child

    actual_order = [c.tag for c in tree.children if c.tag in _SYSARCH_REQUIRED_ORDER]
    if actual_order != list(_SYSARCH_REQUIRED_ORDER):
        raise ValidationError(
            f"<sysarch> sections are not in the required order. "
            f"Expected: {list(_SYSARCH_REQUIRED_ORDER)}. "
            f"Got: {actual_order}. "
            "Reorder the children of <sysarch> to match the required sequence."
        )

    # All five sections present — validate each in turn.
    techspec = _validate_sysarch_techspec(section_map["techspec"])
    components = _validate_sysarch_components(
        section_map["components"], known_top_level_resp_ids=known_top_level_resp_ids
    )
    policies = _validate_sysarch_policies(
        section_map["policies"], known_top_level_resp_ids=known_top_level_resp_ids
    )

    alias_set = {c.alias for c in components}
    alias_kind_map = {c.alias: c.kind for c in components}

    deps = _validate_sysarch_dependencies(section_map["dependencies"], alias_set)
    domain_parents = _validate_sysarch_domain_parent(section_map["domain-parent"], alias_kind_map)

    # Responsibility assignment validation: each resp must be assigned
    # to exactly one domain component, and may optionally also appear
    # in one presentational component that has a domain-parent edge to
    # the domain component that owns it.
    domain_parent_set = {(dp.from_alias, dp.to_alias) for dp in domain_parents}
    domain_assignments: dict[str, str] = {}
    pres_assignments: dict[str, str] = {}
    for comp in components:
        for rid in comp.resp_refs:
            if comp.kind == "domain":
                if rid in domain_assignments:
                    raise ValidationError(
                        f"Responsibility {rid!r} is assigned to domain components "
                        f"{domain_assignments[rid]!r} and {comp.alias!r}. Each "
                        "responsibility must be assigned to exactly one domain "
                        "component."
                    )
                domain_assignments[rid] = comp.alias
            else:
                if rid in pres_assignments:
                    raise ValidationError(
                        f"Responsibility {rid!r} is assigned to presentational "
                        f"components {pres_assignments[rid]!r} and {comp.alias!r}. "
                        "Each responsibility may appear in at most one "
                        "presentational component."
                    )
                pres_assignments[rid] = comp.alias
    for rid, pres_alias in pres_assignments.items():
        if rid not in domain_assignments:
            raise ValidationError(
                f"Responsibility {rid!r} is assigned to presentational component "
                f"{pres_alias!r} but not to any domain component. A responsibility "
                "must first be assigned to a domain component before it can "
                "additionally appear in a presentational counterpart."
            )
        domain_alias = domain_assignments[rid]
        if (pres_alias, domain_alias) not in domain_parent_set:
            raise ValidationError(
                f"Responsibility {rid!r} is assigned to both domain component "
                f"{domain_alias!r} and presentational component {pres_alias!r}, "
                f"but {pres_alias!r} does not have a <domain-parent> edge to "
                f"{domain_alias!r}. A responsibility can only appear in a "
                "presentational component that is the domain parent's counterpart."
            )
    all_assigned = set(domain_assignments.keys())
    missing = sorted(known_top_level_resp_ids - all_assigned)
    if missing:
        raise ValidationError(
            "<sysarch> does not assign every top-level responsibility to a "
            f"domain component. Missing: {', '.join(missing)}."
        )

    # Dep cycle detection on the alias graph before returning.
    _detect_dep_cycles(deps, alias_set)

    # Foundation-dependency rule: every non-foundation component must
    # have a <dep> edge to the foundation component. Foundation itself
    # has no deps and no requirement to depend on anything. This makes
    # "everything depends on foundation" a hard structural invariant
    # rather than a loose convention, and guarantees the foundation
    # component's code is reachable from every downstream comparch
    # pass in Phase 4 without needing to re-derive the rule from the
    # architecture doc.
    _enforce_foundation_dependency(components, deps)

    return SysarchDoc(
        techspec=techspec,
        components=components,
        policies=policies,
        deps=deps,
        domain_parents=domain_parents,
    )


def _validate_sysarch_techspec(node: TagNode) -> str:
    """Extract the non-empty text of ``<techspec>``."""
    if node.children:
        # Any nested tags inside techspec are unexpected for MVP.
        # We still accept them with a warning for now — the LLM's
        # intent is clear — but reject if there's no direct text.
        raise ValidationError(
            "<techspec> must contain plain text only, no nested tags. "
            f"Found children: {[c.tag for c in node.children]}."
        )
    text = node.text.strip() if node.text else ""
    if not text:
        raise ValidationError(
            "<techspec> is empty. The system techspec must be a paragraph "
            "describing project-level technology and architecture choices."
        )
    return text


def _validate_sysarch_components(
    node: TagNode, *, known_top_level_resp_ids: set[str]
) -> tuple[Component, ...]:
    """Validate ``<components>`` and return a tuple of ``Component``."""
    # Allow only <component> children at this level.
    for child in node.children:
        if child.tag != "component":
            raise ValidationError(
                f"<components> contains an unexpected child <{child.tag}>. "
                "Only <component> entries are allowed at this level."
            )
    component_nodes = [c for c in node.children if c.tag == "component"]
    if not component_nodes:
        raise ValidationError(
            "<components> contains no <component> entries. "
            "Every project needs at least one top-level component."
        )

    components: list[Component] = []
    seen_aliases: set[str] = set()
    foundation_aliases: list[str] = []

    for index, cnode in enumerate(component_nodes):
        comp = _validate_component(
            cnode,
            index=index,
            known_top_level_resp_ids=known_top_level_resp_ids,
        )
        if comp.alias in seen_aliases:
            raise ValidationError(
                f"<components> contains two <component> entries with the same "
                f"alias {comp.alias!r}. Aliases must be unique within a sysarch "
                "doc. Rename one of them."
            )
        seen_aliases.add(comp.alias)
        if comp.is_foundation:
            foundation_aliases.append(comp.alias)
        components.append(comp)

    # Foundation requirement: exactly one component must carry the marker.
    if len(foundation_aliases) == 0:
        raise ValidationError(
            "<components> has no foundation component. Exactly one "
            "component must carry a self-closing <foundation/> marker "
            "child — it owns the project's root folder files (build "
            "config, package init, shared utilities). See the "
            "architecture doc §Foundation components."
        )
    if len(foundation_aliases) > 1:
        raise ValidationError(
            f"<components> has {len(foundation_aliases)} foundation components "
            f"({', '.join(sorted(foundation_aliases))}). Exactly one foundation "
            "component is required; promote the others to regular domain "
            "components or merge them into the single foundation."
        )

    return tuple(components)


def _validate_component(
    node: TagNode, *, index: int, known_top_level_resp_ids: set[str]
) -> Component:
    """Validate a single ``<component>`` entry."""
    pos = f"<component> at position {index}"

    alias = node.attrs.get("alias", "").strip()
    if not alias:
        raise ValidationError(
            f"{pos} is missing the alias attribute. Every component must "
            'carry alias="..." (lowercase snake_case, 1-32 chars, starts '
            "with a letter)."
        )
    if not _ALIAS_RE.match(alias):
        raise ValidationError(
            f"{pos} has invalid alias {alias!r}. Aliases must match "
            "^[a-z][a-z0-9_]{0,31}$ — lowercase letter first, then "
            "lowercase alphanumerics or underscores, 1-32 characters."
        )

    # Check children allowlist.
    for child in node.children:
        if child.tag not in _COMPONENT_ALLOWED_CHILDREN:
            raise ValidationError(
                f"{pos} (alias={alias!r}) contains an unexpected child "
                f"<{child.tag}>. Allowed children are: "
                f"{sorted(_COMPONENT_ALLOWED_CHILDREN)}."
            )

    def _require_one(tag: str) -> TagNode:
        matching = node.find_all(tag)
        if len(matching) == 0:
            raise ValidationError(
                f"{pos} (alias={alias!r}) is missing a <{tag}> child. "
                "Every component must have exactly one."
            )
        if len(matching) > 1:
            raise ValidationError(
                f"{pos} (alias={alias!r}) has {len(matching)} <{tag}> "
                "children; exactly one is required."
            )
        return matching[0]

    name_node = _require_one("name")
    kind_node = _require_one("kind")
    role_node = _require_one("role")
    api_intent_node = _require_one("api-intent")
    responsibilities_node = _require_one("responsibilities")

    name = (name_node.text or "").strip()
    if not name:
        raise ValidationError(
            f"{pos} (alias={alias!r}) has an empty <name>. The display "
            "name must be a short title-case identifier."
        )

    # match-case gives mypy proper Literal narrowing without a
    # cast — the `kind` binding in each arm is typed as the
    # matched string literal, which lets it flow straight into
    # the Literal-typed Component.kind field downstream.
    kind: Literal["domain", "presentational"]
    match (kind_node.text or "").strip():
        case "domain":
            kind = "domain"
        case "presentational":
            kind = "presentational"
        case invalid:
            raise ValidationError(
                f"{pos} (alias={alias!r}) has invalid <kind> {invalid!r}. "
                "Must be 'domain' or 'presentational'."
            )

    role = (role_node.text or "").strip()
    if not role:
        raise ValidationError(
            f"{pos} (alias={alias!r}) has an empty <role>. Every component "
            "must have a role paragraph describing what it does."
        )

    api_intent = (api_intent_node.text or "").strip()
    if not api_intent:
        raise ValidationError(
            f"{pos} (alias={alias!r}) has an empty <api-intent>. Every "
            "component must describe the shape of its intended API."
        )

    # Validate the <responsibilities> block.
    for rchild in responsibilities_node.children:
        if rchild.tag not in _RESPONSIBILITIES_ALLOWED_CHILDREN:
            raise ValidationError(
                f"{pos} (alias={alias!r}) has a <responsibilities> block "
                f"containing an unexpected child <{rchild.tag}>. Only "
                '<resp id="resp_..."/> entries are allowed.'
            )
    resp_nodes = responsibilities_node.find_all("resp")
    if not resp_nodes:
        raise ValidationError(
            f"{pos} (alias={alias!r}) has an empty <responsibilities> block. "
            "Every component must be assigned at least one top-level "
            'responsibility via a <resp id="resp_..."/> child.'
        )
    resp_refs: list[str] = []
    seen_refs: set[str] = set()
    for ri, rnode in enumerate(resp_nodes):
        rid = rnode.attrs.get("id", "").strip()
        if not rid:
            raise ValidationError(
                f"{pos} (alias={alias!r}) has a <resp> entry at position {ri} "
                "with no id attribute. Every <resp> must carry an "
                'id="resp_..." attribute referencing a known responsibility.'
            )
        if rid in seen_refs:
            raise ValidationError(
                f"{pos} (alias={alias!r}) has duplicate <resp> reference "
                f"{rid!r} in its <responsibilities> block. Each responsibility "
                "may be listed at most once per component."
            )
        seen_refs.add(rid)
        if rid not in known_top_level_resp_ids:
            raise ValidationError(
                f"{pos} (alias={alias!r}) references unknown top-level "
                f"responsibility {rid!r}. Valid IDs: "
                f"{', '.join(sorted(known_top_level_resp_ids))}."
            )
        resp_refs.append(rid)

    is_foundation = len(node.find_all("foundation")) > 0

    return Component(
        alias=alias,
        name=name,
        kind=kind,
        role=role,
        api_intent=api_intent,
        resp_refs=tuple(resp_refs),
        is_foundation=is_foundation,
    )


def validate_policy_blob(text: str, *, known_resp_ids: set[str]) -> Policy:
    """Parse and validate a single ``<policy>`` XML blob.

    Standalone helper so comparch (Phase 4) and any other consumer
    can parse a stored ``policy_*.content`` back into a ``Policy``
    dataclass without reinventing the sub-grammar. The sysarch
    validator calls this inline for each policy in the
    ``<policies>`` block.

    ``known_resp_ids`` is the set of responsibility IDs the policy
    is allowed to reference via its ``<required>`` field.
    """
    tree = extract_tag_tree(text, "policy")
    return _validate_policy(tree, index=0, known_resp_ids=known_resp_ids)


def _validate_sysarch_policies(
    node: TagNode, *, known_top_level_resp_ids: set[str]
) -> tuple[Policy, ...]:
    """Validate ``<policies>`` and return a tuple of ``Policy``."""
    for child in node.children:
        if child.tag not in _POLICIES_ALLOWED_CHILDREN:
            raise ValidationError(
                f"<policies> contains an unexpected child <{child.tag}>. "
                "Only <policy> entries are allowed."
            )
    policy_nodes = node.find_all("policy")
    policies: list[Policy] = []
    for index, pnode in enumerate(policy_nodes):
        policies.append(
            _validate_policy(pnode, index=index, known_resp_ids=known_top_level_resp_ids)
        )
    return tuple(policies)


def _validate_policy(node: TagNode, *, index: int, known_resp_ids: set[str]) -> Policy:
    """Validate a single ``<policy>`` entry."""
    pos = f"<policy> at position {index}"
    for child in node.children:
        if child.tag not in _POLICY_ALLOWED_CHILDREN:
            raise ValidationError(
                f"{pos} contains an unexpected child <{child.tag}>. "
                "Only <name>, <trigger>, <required>, and <rationale> are allowed."
            )

    def _require_one(tag: str) -> TagNode:
        matching = node.find_all(tag)
        if len(matching) == 0:
            raise ValidationError(
                f"{pos} is missing a <{tag}> child. Every policy must have exactly one."
            )
        if len(matching) > 1:
            raise ValidationError(
                f"{pos} has {len(matching)} <{tag}> children; exactly one is required."
            )
        return matching[0]

    name = (_require_one("name").text or "").strip()
    trigger = (_require_one("trigger").text or "").strip()
    rationale = (_require_one("rationale").text or "").strip()
    # Phase-11 followup B8: <required> is optional. Universal-scope
    # policies (AGPL, org-wide conventions) omit it; the application
    # pass then emits policy_application edges to every candidate
    # component in scope.
    required_nodes = node.find_all("required")
    if len(required_nodes) > 1:
        raise ValidationError(
            f"{pos} has {len(required_nodes)} <required> children; at most one is allowed."
        )
    required: str | None
    if required_nodes:
        candidate = (required_nodes[0].text or "").strip()
        if not candidate:
            # Empty <required></required> is indistinguishable from
            # omission for intent but easier to typo. Treat it as
            # "omitted" (universal) rather than a hard error.
            required = None
        else:
            required = candidate
    else:
        required = None

    if not name:
        raise ValidationError(f"{pos} has an empty <name>.")
    if not trigger:
        raise ValidationError(
            f"{pos} has an empty <trigger>. The trigger is the semantic "
            "phrase identifying where the policy applies (e.g. "
            "'any LLM call', 'any domain write')."
        )
    if not rationale:
        raise ValidationError(
            f"{pos} has an empty <rationale>. The rationale paragraph "
            "explains why the policy exists and carries weight when the "
            "application pass decides which components it applies to."
        )
    if required is not None and required not in known_resp_ids:
        raise ValidationError(
            f"{pos} has <required>{required}</required> referencing an "
            f"unknown responsibility. Valid IDs: "
            f"{', '.join(sorted(known_resp_ids))}. "
            "(Omit <required> entirely for a universal-scope policy.)"
        )

    return Policy(name=name, trigger=trigger, required_resp_id=required, rationale=rationale)


def _validate_sysarch_dependencies(node: TagNode, alias_set: set[str]) -> tuple[DepEdge, ...]:
    """Validate ``<dependencies>`` and return a tuple of ``DepEdge``."""
    for child in node.children:
        if child.tag not in _DEPENDENCIES_ALLOWED_CHILDREN:
            raise ValidationError(
                f"<dependencies> contains an unexpected child <{child.tag}>. "
                "Only <dep> entries are allowed."
            )
    dep_nodes = node.find_all("dep")
    deps: list[DepEdge] = []
    for index, dnode in enumerate(dep_nodes):
        from_alias = dnode.attrs.get("from", "").strip()
        to_alias = dnode.attrs.get("to", "").strip()
        if not from_alias or not to_alias:
            raise ValidationError(
                f"<dep> at position {index} is missing a from or to attribute. "
                'Every <dep> must carry from="..." to="..." with known aliases.'
            )
        if from_alias not in alias_set:
            raise ValidationError(
                f"<dep> at position {index} has unknown from alias {from_alias!r}. "
                f"Valid aliases: {sorted(alias_set)}."
            )
        if to_alias not in alias_set:
            raise ValidationError(
                f"<dep> at position {index} has unknown to alias {to_alias!r}. "
                f"Valid aliases: {sorted(alias_set)}."
            )
        if from_alias == to_alias:
            raise ValidationError(
                f"<dep> at position {index} has from == to (both {from_alias!r}). "
                "A component cannot depend on itself."
            )
        deps.append(DepEdge(from_alias=from_alias, to_alias=to_alias))
    return tuple(deps)


def _validate_sysarch_domain_parent(
    node: TagNode, alias_kind_map: Mapping[str, str]
) -> tuple[DomainParentEdge, ...]:
    """Validate ``<domain-parent>`` and return a tuple of ``DomainParentEdge``."""
    for child in node.children:
        if child.tag not in _DOMAIN_PARENT_ALLOWED_CHILDREN:
            raise ValidationError(
                f"<domain-parent> contains an unexpected child <{child.tag}>. "
                "Only <parent> entries are allowed."
            )
    parent_nodes = node.find_all("parent")
    edges: list[DomainParentEdge] = []
    for index, pnode in enumerate(parent_nodes):
        from_alias = pnode.attrs.get("from", "").strip()
        to_alias = pnode.attrs.get("to", "").strip()
        if not from_alias or not to_alias:
            raise ValidationError(
                f"<parent> at position {index} is missing a from or to "
                'attribute. Every <parent> must carry from="..." to="..." '
                "with known aliases."
            )
        if from_alias not in alias_kind_map:
            raise ValidationError(
                f"<parent> at position {index} has unknown from alias {from_alias!r}."
            )
        if to_alias not in alias_kind_map:
            raise ValidationError(
                f"<parent> at position {index} has unknown to alias {to_alias!r}."
            )
        if alias_kind_map[from_alias] != "presentational":
            raise ValidationError(
                f"<parent> at position {index}: from alias {from_alias!r} must "
                f"be a presentational component (kind={alias_kind_map[from_alias]!r})."
            )
        if alias_kind_map[to_alias] != "domain":
            raise ValidationError(
                f"<parent> at position {index}: to alias {to_alias!r} must "
                f"be a domain component (kind={alias_kind_map[to_alias]!r})."
            )
        edges.append(DomainParentEdge(from_alias=from_alias, to_alias=to_alias))

    # Phase 7 slice-by-task rule: a presentational with more than
    # two domain parents has almost certainly conflated multiple
    # user tasks into one application-shaped component. Reject at
    # three so the sysarch pass splits the slice rather than
    # widening it. Counts per ``from`` alias.
    parent_count_by_from: dict[str, int] = {}
    for edge in edges:
        parent_count_by_from[edge.from_alias] = parent_count_by_from.get(edge.from_alias, 0) + 1
    for from_alias, count in parent_count_by_from.items():
        if count > 2:
            raise ValidationError(
                f"Presentational component {from_alias!r} has {count} "
                "<domain-parent> edges; the cap is 2. More than two "
                "domain parents indicates the component is surfacing "
                "multiple user tasks as one application — split it "
                "into distinct task-shaped presentational components, "
                "each with 1 or 2 <domain-parent> edges."
            )

    return tuple(edges)


def _detect_dep_cycles(deps: tuple[DepEdge, ...], alias_set: set[str]) -> None:
    """DFS on the dependency alias graph; raise on the first cycle found.

    Cycle paths are reported in alias form (the LLM authored the
    aliases, so it can fix them). Deterministic order — aliases
    are sorted for reproducible retry prompts.
    """
    # Build adjacency list in deterministic order.
    adj: dict[str, list[str]] = {a: [] for a in sorted(alias_set)}
    for d in deps:
        adj[d.from_alias].append(d.to_alias)
    for a in adj:
        adj[a].sort()

    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = {a: WHITE for a in adj}
    stack: list[str] = []

    def _dfs(node: str) -> None:
        color[node] = GRAY
        stack.append(node)
        for nxt in adj[node]:
            if color[nxt] == GRAY:
                # Cycle: nxt is the closing point; find it in the stack.
                start = stack.index(nxt)
                cycle = stack[start:] + [nxt]
                raise ValidationError(
                    f"Dependency cycle detected: {' → '.join(cycle)}. "
                    "Remove one of these <dep> edges or restructure the "
                    "components so the graph is a DAG. Foundation should "
                    "typically be a sink (everything depends on it, it "
                    "depends on nothing)."
                )
            if color[nxt] == WHITE:
                _dfs(nxt)
        color[node] = BLACK
        stack.pop()

    for a in adj:
        if color[a] == WHITE:
            _dfs(a)


def _enforce_foundation_dependency(
    components: tuple[Component, ...], deps: tuple[DepEdge, ...]
) -> None:
    """Enforce that every non-foundation component has a dep edge to foundation.

    Phase 3 stage 2 invariant: every top-level component must depend
    on the foundation component. Foundation owns the project root
    (build config, shared utilities, application factory, base types)
    and every other component's code is expected to reach into it at
    runtime, so an explicit dependency edge makes the relationship
    a structural property the rest of the system can rely on.

    The foundation component is identified by the ``<foundation/>``
    marker; the caller's ``_validate_sysarch_components`` already
    enforced that exactly one exists, so we can safely pick the
    single match here.

    Foundation itself is exempt — it has no dependency target (it's
    the only sink in the dep DAG). All non-foundation components
    must have at least one ``DepEdge`` with
    ``from_alias=<their alias>`` and ``to_alias=<foundation alias>``.
    """
    foundation_alias = next(c.alias for c in components if c.is_foundation)
    required_from = {c.alias for c in components if not c.is_foundation}
    seen: set[str] = {d.from_alias for d in deps if d.to_alias == foundation_alias}
    missing = sorted(required_from - seen)
    if missing:
        raise ValidationError(
            "Every non-foundation component must have a <dep> edge "
            f"pointing at the foundation component {foundation_alias!r}. "
            f"Missing foundation dependency from: {', '.join(missing)}. "
            'Add <dep from="<alias>" to="' + foundation_alias + '"/> '
            "for each missing component."
        )


# ── Subrequirements (Phase 3 stage 3: subreqs → subresp resp_*) ────


@dataclass(frozen=True)
class Subresponsibility:
    """A single validated subresponsibility from a ``<subrequirements>`` block.

    ``derived_from`` is the set of top-level resp IDs this subresp
    decomposes — must be a non-empty subset of the owning
    component's assigned top-level resps.
    """

    name: str
    intent: str
    derived_from: tuple[str, ...]


_SUBREQUIREMENTS_ALLOWED_CHILDREN = {"subresponsibility"}
_SUBRESPONSIBILITY_ALLOWED_CHILDREN = {"name", "intent", "derived-from"}
_DERIVED_FROM_ALLOWED_CHILDREN = {"resp"}


def validate_subrequirements(
    tree: TagNode, *, known_parent_resp_ids: set[str]
) -> list[Subresponsibility]:
    """Validate a parsed ``<subrequirements>`` tree.

    Shape parallels ``validate_requirements`` but scoped to a
    single component. ``known_parent_resp_ids`` is the set of
    top-level resps assigned to *this* component (via the
    ``decomposition`` edges minted at sysarch approval). Every
    ``<resp id=...>`` reference in any ``<derived-from>`` block
    must be in this set — cross-component leaks are parse errors.

    Coverage check: every known parent resp must appear in at
    least one ``<derived-from>`` across the full validated set.
    An uncovered parent resp is a parse error that feeds the
    retry loop.
    """
    if tree.tag != "subrequirements":
        raise ValidationError(
            f"Expected root tag <subrequirements>, got <{tree.tag}>. "
            "Wrap the subresponsibility list in a single "
            "<subrequirements>...</subrequirements> block."
        )

    for child in tree.children:
        if child.tag not in _SUBREQUIREMENTS_ALLOWED_CHILDREN:
            raise ValidationError(
                f"<subrequirements> contains an unexpected child "
                f"<{child.tag}>. Only <subresponsibility> entries are "
                "allowed at this level."
            )

    result: list[Subresponsibility] = []
    for index, child in enumerate(tree.children):
        result.append(
            _validate_subresponsibility(child, index, known_parent_resp_ids=known_parent_resp_ids)
        )

    if not result:
        raise ValidationError(
            "<subrequirements> block contains no <subresponsibility> "
            "entries. A component with assigned responsibilities must "
            "have at least one subresponsibility."
        )

    # Coverage check: every parent resp must be covered.
    covered: set[str] = set()
    for subresp in result:
        covered.update(subresp.derived_from)
    missing = sorted(known_parent_resp_ids - covered)
    if missing:
        raise ValidationError(
            "<subrequirements> does not cover every parent responsibility "
            "assigned to this component. Missing: "
            f"{', '.join(missing)}. Every assigned responsibility must "
            "appear in at least one <derived-from> block."
        )

    return result


def _validate_subresponsibility(
    node: TagNode, index: int, *, known_parent_resp_ids: set[str]
) -> Subresponsibility:
    """Validate a single ``<subresponsibility>`` entry."""
    pos = f"<subresponsibility> at position {index}"

    for child in node.children:
        if child.tag not in _SUBRESPONSIBILITY_ALLOWED_CHILDREN:
            raise ValidationError(
                f"{pos} contains an unexpected child <{child.tag}>. "
                "Only <name>, <intent>, and <derived-from> are allowed "
                "inside a <subresponsibility>."
            )

    name_children = node.find_all("name")
    if len(name_children) == 0:
        raise ValidationError(
            f"{pos} is missing a <name> child. Every subresponsibility "
            "must have exactly one <name>."
        )
    if len(name_children) > 1:
        raise ValidationError(
            f"{pos} has {len(name_children)} <name> children; exactly one is required."
        )

    intent_children = node.find_all("intent")
    if len(intent_children) == 0:
        raise ValidationError(
            f"{pos} is missing an <intent> child. Every subresponsibility "
            "must have exactly one <intent>."
        )
    if len(intent_children) > 1:
        raise ValidationError(
            f"{pos} has {len(intent_children)} <intent> children; exactly one is required."
        )

    derived_children = node.find_all("derived-from")
    if len(derived_children) == 0:
        raise ValidationError(
            f"{pos} is missing a <derived-from> child. Every "
            "subresponsibility must have exactly one <derived-from> "
            'block listing at least one <resp id="resp_..."/> child.'
        )
    if len(derived_children) > 1:
        raise ValidationError(
            f"{pos} has {len(derived_children)} <derived-from> children; exactly one is required."
        )

    name_text = name_children[0].text
    if not name_text:
        raise ValidationError(
            f"{pos} has an empty <name>. The subresponsibility name "
            "must be a short identifier, typically 2–5 words in title case."
        )

    intent_text = intent_children[0].text
    if not intent_text:
        raise ValidationError(
            f"{pos} has an empty <intent>. The intent must be a short "
            "paragraph describing the role and scope."
        )

    derived_from = _validate_derived_from(
        derived_children[0], pos, known_parent_resp_ids=known_parent_resp_ids
    )

    return Subresponsibility(name=name_text, intent=intent_text, derived_from=derived_from)


def _validate_derived_from(
    node: TagNode, parent_pos: str, *, known_parent_resp_ids: set[str]
) -> tuple[str, ...]:
    """Validate a single ``<derived-from>`` block and return its resp IDs."""
    for child in node.children:
        if child.tag not in _DERIVED_FROM_ALLOWED_CHILDREN:
            raise ValidationError(
                f"{parent_pos} has a <derived-from> block containing an "
                f"unexpected child <{child.tag}>. Only "
                '<resp id="resp_..."/> entries are allowed inside '
                "<derived-from>."
            )

    resp_nodes = node.find_all("resp")
    if not resp_nodes:
        raise ValidationError(
            f"{parent_pos} has an empty <derived-from> block. Every "
            "subresponsibility must derive from at least one parent "
            'responsibility — list them via <resp id="resp_..."/> children.'
        )

    ids: list[str] = []
    seen: set[str] = set()
    for i, rnode in enumerate(resp_nodes):
        rid = rnode.attrs.get("id", "").strip()
        if not rid:
            raise ValidationError(
                f"{parent_pos} has a <resp> entry at <derived-from> "
                f"position {i} with no id attribute. Every <resp> must "
                'carry an id="resp_..." attribute.'
            )
        if rid in seen:
            raise ValidationError(
                f"{parent_pos} has a <resp> entry at <derived-from> "
                f"position {i} listing duplicate id {rid!r}. Each id "
                "may appear at most once per <derived-from> block."
            )
        seen.add(rid)
        if rid not in known_parent_resp_ids:
            raise ValidationError(
                f"{parent_pos} has a <resp> entry at <derived-from> "
                f"position {i} referencing {rid!r}, which is not one "
                "of the top-level responsibilities assigned to this "
                "component. Cross-component leaks are forbidden. Valid "
                f"IDs for this component: {', '.join(sorted(known_parent_resp_ids))}."
            )
        ids.append(rid)

    return tuple(ids)


# ── Component architecture doc (Phase 4: comparch) ─────────────────


@dataclass(frozen=True)
class Subcomponent:
    """A single validated subcomponent entry from a ``<comparch>`` block.

    ``alias`` is the local reference used inside the owning
    component's ``<sub-dependencies>`` edges — it is *not* a
    node ID. The comparch mint handler resolves aliases to real
    ``comp_*`` IDs at approval time.

    Subcomponents do **not** carry a ``kind`` field; they
    inherit the kind (domain / presentational) of the owning
    top-level component. ``resp_refs`` holds the pre-minted
    subresp IDs this subcomponent owns; the 1:1 subresp →
    subcomponent assignment is enforced at the ``<subcomponents>``
    block level so every minted subresp lands in exactly one
    subcomponent.
    """

    alias: str
    name: str
    role: str
    api_intent: str
    resp_refs: tuple[str, ...]
    is_foundation: bool


@dataclass(frozen=True)
class ArchDoc:
    """The full validated comparch output as structured data.

    Fields mirror the seven sections of the arch doc XML. The
    first five are fragment sections (stored verbatim as the
    persistent, transcluded content of each ``comp_X_<kind>``
    fragment). The last two are mint-time directives that
    project into ``NodeCreated`` / ``EdgeCreated`` events and
    then drop away as standalone artifacts.

    ``external_deps`` holds the raw ``comp_*`` IDs from the
    ``<dependencies>`` section — already globally unique so
    no alias resolution is needed. ``sub_deps`` holds alias
    pairs; the mint handler resolves them against the
    newly-minted subcomponents.
    """

    techspec: str
    pubapi: str
    privapi: str
    policies: tuple[Policy, ...]
    external_deps: tuple[str, ...]
    subcomponents: tuple[Subcomponent, ...]
    sub_deps: tuple[DepEdge, ...]


_COMPARCH_ALLOWED_CHILDREN = {
    "technical-specification",
    "public-surface",
    "private-surface",
    "policies",
    "dependencies",
    "subcomponents",
    "sub-dependencies",
}
_COMPARCH_REQUIRED_ORDER = (
    "technical-specification",
    "public-surface",
    "private-surface",
    "policies",
    "dependencies",
    "subcomponents",
    "sub-dependencies",
)
_SUBCOMPONENTS_ALLOWED_CHILDREN = {"subcomponent"}
_SUBCOMPONENT_ALLOWED_CHILDREN = {
    "name",
    "role",
    "api-intent",
    "responsibilities",
    "foundation",
}
_SUB_DEPENDENCIES_ALLOWED_CHILDREN = {"dep"}


def validate_arch_doc(
    tree: TagNode,
    *,
    known_subresp_ids: set[str],
    known_sibling_comp_ids: set[str],
    known_resp_ids_for_policies: set[str],
    target_is_foundation: bool = False,
) -> ArchDoc:
    """Validate a parsed ``<comparch>`` tree and return an ArchDoc.

    Enforces the seven-section structure described in
    :mod:`backend.graph.prompts.comparch`: single root, seven
    sections in order, non-empty fragment text for the first
    three, policy sub-grammar referencing resps from the
    project-wide + component-local allowed set, ``<dependencies>``
    references constrained to the sibling comp allowlist,
    ``<subcomponents>`` with alias syntax / uniqueness / kind
    inheritance (no ``<kind>`` tag) / exactly-one-foundation (if
    decomposing) / subresp coverage, and ``<sub-dependencies>``
    acyclicity + foundation-dep rule.

    ``known_subresp_ids`` is the set of pre-minted subresp IDs
    owned by this component (from its approved ``subreqs_*``).
    Every resp reference in ``<subcomponents>/<responsibilities>``
    must come from this set and every ID in the set must be
    assigned to exactly one subcomponent when decomposing.

    ``known_sibling_comp_ids`` is the set of top-level
    ``comp_*`` IDs other than this component. ``<dependencies>``
    may only reference IDs from this set.

    ``known_resp_ids_for_policies`` is the union of
    (a) top-level resp_* IDs assigned to this component and
    (b) the component's pre-minted subresps. Component-local
    policies' ``<required>`` field must reference an ID from
    this set — top-level resps owned by OTHER components are
    cross-component leaks.

    ``target_is_foundation`` flips the "foundations don't nest"
    carve-out: when the component being decomposed is itself a
    foundation (top-level or sub), the ``<subcomponents>`` block
    must *not* include another foundation marker, and the
    "every non-foundation sub depends on the foundation"
    check is skipped (there's no foundation sub to depend on).
    Instead, the foundation decomposes exhaustively into concrete
    subcomponents that collectively own all its territory. See
    ``docs/architecture/v2-rearchitecture.md`` §Foundation
    components.

    Un-fanned-out is legal: both ``<subcomponents>`` and
    ``<sub-dependencies>`` may be empty. In that case there is
    no foundation requirement and no subresp coverage check —
    the subresps will be projected into a single ``impl_*``
    leaf by Phase 6.
    """
    if tree.tag != "comparch":
        raise ValidationError(
            f"Expected root tag <comparch>, got <{tree.tag}>. "
            "Wrap the architecture doc in a single "
            "<comparch>...</comparch> block."
        )

    section_map: dict[str, TagNode] = {}
    for child in tree.children:
        if child.tag not in _COMPARCH_ALLOWED_CHILDREN:
            raise ValidationError(
                f"<comparch> contains an unexpected child <{child.tag}>. "
                f"Allowed children are: {sorted(_COMPARCH_ALLOWED_CHILDREN)}."
            )
        if child.tag in section_map:
            raise ValidationError(
                f"<comparch> contains more than one <{child.tag}> section; "
                "exactly one of each section is required."
            )
        section_map[child.tag] = child

    actual_order = [c.tag for c in tree.children if c.tag in _COMPARCH_REQUIRED_ORDER]
    if actual_order != list(_COMPARCH_REQUIRED_ORDER):
        raise ValidationError(
            f"<comparch> sections are not in the required order. "
            f"Expected: {list(_COMPARCH_REQUIRED_ORDER)}. "
            f"Got: {actual_order}. "
            "Reorder the children of <comparch> to match the required sequence."
        )

    techspec = _validate_fragment_section(
        section_map["technical-specification"], "technical-specification"
    )
    pubapi = _validate_fragment_section(section_map["public-surface"], "public-surface")
    privapi = _validate_fragment_section(section_map["private-surface"], "private-surface")

    policies = _validate_arch_doc_policies(
        section_map["policies"], known_resp_ids=known_resp_ids_for_policies
    )
    external_deps = _validate_arch_doc_external_dependencies(
        section_map["dependencies"], known_sibling_comp_ids=known_sibling_comp_ids
    )
    subcomponents = _validate_arch_doc_subcomponents(
        section_map["subcomponents"],
        known_subresp_ids=known_subresp_ids,
        target_is_foundation=target_is_foundation,
    )

    sub_alias_set = {s.alias for s in subcomponents}
    sub_deps = _validate_arch_doc_sub_dependencies(section_map["sub-dependencies"], sub_alias_set)

    # Sub-dep cycle detection + foundation-dep enforcement — only
    # meaningful when decomposing. Un-fanned-out components have
    # no sub-alias set so the checks degenerate to no-ops. When
    # the target is itself a foundation, there is no foundation
    # subcomponent to depend on, so the foundation-dep rule is
    # also skipped (cycle detection still runs).
    if subcomponents:
        _detect_dep_cycles(sub_deps, sub_alias_set)
        if not target_is_foundation:
            _enforce_sub_foundation_dependency(subcomponents, sub_deps)

    return ArchDoc(
        techspec=techspec,
        pubapi=pubapi,
        privapi=privapi,
        policies=policies,
        external_deps=external_deps,
        subcomponents=subcomponents,
        sub_deps=sub_deps,
    )


def _validate_fragment_section(node: TagNode, section_name: str) -> str:
    """Extract the non-empty text of a fragment section.

    Fragment sections (``<technical-specification>``,
    ``<public-surface>``, ``<private-surface>``) are prose with
    optional fenced code blocks. The parser treats the whole
    section as text — no nested XML tags allowed, because the
    parser doesn't have a grammar for "section text" vs
    "structured child" inside a fragment.
    """
    if node.children:
        raise ValidationError(
            f"<{section_name}> must contain plain text and fenced code "
            "blocks only, no nested XML tags. Found children: "
            f"{[c.tag for c in node.children]}."
        )
    text = node.text.strip() if node.text else ""
    if not text:
        raise ValidationError(
            f"<{section_name}> is empty. This fragment section must be "
            "a non-empty paragraph describing the component's "
            f"{section_name.replace('-', ' ')}."
        )
    return text


def _validate_arch_doc_policies(node: TagNode, *, known_resp_ids: set[str]) -> tuple[Policy, ...]:
    """Validate ``<policies>`` and return a tuple of Policy.

    Reuses the existing :func:`_validate_policy` helper that the
    sysarch validator uses — component-local policies have
    identical sub-grammar to top-level ones. The only difference
    is the set of allowed ``<required>`` resp IDs, which the
    caller supplies.
    """
    for child in node.children:
        if child.tag not in _POLICIES_ALLOWED_CHILDREN:
            raise ValidationError(
                f"<policies> contains an unexpected child <{child.tag}>. "
                "Only <policy> entries are allowed."
            )
    policy_nodes = node.find_all("policy")
    policies: list[Policy] = []
    for index, pnode in enumerate(policy_nodes):
        policies.append(_validate_policy(pnode, index=index, known_resp_ids=known_resp_ids))
    return tuple(policies)


def _validate_arch_doc_external_dependencies(
    node: TagNode, *, known_sibling_comp_ids: set[str]
) -> tuple[str, ...]:
    """Validate ``<dependencies>`` and return the sibling comp IDs.

    Unlike sysarch's ``<dependencies>`` which uses local aliases,
    comparch's external dependencies use real ``comp_*`` IDs
    because sibling top-level components are already minted and
    globally unique. Each ``<dep>`` has a single ``to``
    attribute — there's no ``from`` because the owning component
    is implicit.
    """
    for child in node.children:
        if child.tag not in _DEPENDENCIES_ALLOWED_CHILDREN:
            raise ValidationError(
                f"<dependencies> contains an unexpected child <{child.tag}>. "
                'Only <dep to="comp_..."/> entries are allowed.'
            )
    dep_nodes = node.find_all("dep")
    seen: set[str] = set()
    deps: list[str] = []
    for index, dnode in enumerate(dep_nodes):
        target = dnode.attrs.get("to", "").strip()
        if not target:
            raise ValidationError(
                f"<dep> at position {index} is missing the to attribute. "
                'Every external <dep> must carry to="comp_..." with a '
                "real sibling component ID."
            )
        if dnode.attrs.get("from"):
            raise ValidationError(
                f"<dep> at position {index} has a from attribute. "
                "External dependencies are always from this component "
                'implicitly — do not add from="..." to <dependencies> '
                "entries. Sub-dependencies inside <sub-dependencies> "
                "do use from/to aliases."
            )
        if target not in known_sibling_comp_ids:
            valid_list = sorted(known_sibling_comp_ids) or (
                "(none — this is the only top-level component)"
            )
            raise ValidationError(
                f"<dep> at position {index} targets {target!r}, which is "
                "not in the allowed sibling component set. Valid targets: "
                f"{valid_list}."
            )
        if target in seen:
            raise ValidationError(
                f"<dependencies> lists duplicate target {target!r}. Each "
                "sibling may appear at most once."
            )
        seen.add(target)
        deps.append(target)
    return tuple(deps)


def _validate_arch_doc_subcomponents(
    node: TagNode,
    *,
    known_subresp_ids: set[str],
    target_is_foundation: bool = False,
) -> tuple[Subcomponent, ...]:
    """Validate ``<subcomponents>`` and return a tuple of Subcomponent.

    May legitimately be empty (un-fanned-out component). If
    populated: enforces alias syntax + uniqueness, per-subcomponent
    field completeness, and coverage of every pre-minted subresp
    in ``known_subresp_ids``.

    The foundation-marker rule depends on ``target_is_foundation``:

    - **Normal component** (default): exactly one subcomponent
      must carry the ``<foundation/>`` marker. Zero or two+ are
      rejected.
    - **Foundation target**: *no* subcomponent may carry the
      ``<foundation/>`` marker. Foundations don't nest — the
      decomposition is required to divide the foundation's
      territory exhaustively without a sub-foundation catch-all.
    """
    for child in node.children:
        if child.tag not in _SUBCOMPONENTS_ALLOWED_CHILDREN:
            raise ValidationError(
                f"<subcomponents> contains an unexpected child "
                f"<{child.tag}>. Only <subcomponent> entries are allowed."
            )
    subcomponent_nodes = [c for c in node.children if c.tag == "subcomponent"]
    if not subcomponent_nodes:
        # Un-fanned-out: valid only if there are no subresps to cover.
        if known_subresp_ids:
            raise ValidationError(
                "<subcomponents> is empty but the owning component has "
                f"{len(known_subresp_ids)} pre-minted subresponsibilities "
                "from its subreqs approval. Decompose the component into "
                "at least one subcomponent that owns them, or if this "
                "component really has no decomposition, the subreqs "
                "pass should not have produced subresps in the first "
                "place. Missing subresps: "
                f"{', '.join(sorted(known_subresp_ids))}."
            )
        return ()

    subcomponents: list[Subcomponent] = []
    seen_aliases: set[str] = set()
    assigned_subresp_ids: dict[str, str] = {}
    foundation_aliases: list[str] = []

    for index, snode in enumerate(subcomponent_nodes):
        sub = _validate_subcomponent(snode, index=index, known_subresp_ids=known_subresp_ids)
        if sub.alias in seen_aliases:
            raise ValidationError(
                f"<subcomponents> contains two <subcomponent> entries "
                f"with the same alias {sub.alias!r}. Aliases must be "
                "unique within an arch doc. Rename one."
            )
        seen_aliases.add(sub.alias)
        if sub.is_foundation:
            foundation_aliases.append(sub.alias)
        for rid in sub.resp_refs:
            if rid in assigned_subresp_ids:
                raise ValidationError(
                    f"Subresponsibility {rid!r} is assigned to both "
                    f"{assigned_subresp_ids[rid]!r} and {sub.alias!r}. "
                    "Each pre-minted subresp must be assigned to "
                    "exactly one subcomponent."
                )
            assigned_subresp_ids[rid] = sub.alias
        subcomponents.append(sub)

    if target_is_foundation:
        # Foundations don't nest. The foundation role is "catch-all
        # at this level"; nesting another foundation inside it would
        # double-count the role, so the validator rejects any
        # <foundation/> marker in a foundation's own decomposition.
        if foundation_aliases:
            raise ValidationError(
                "<subcomponents> contains a foundation subcomponent "
                f"({', '.join(sorted(foundation_aliases))}) but this "
                "component is itself a foundation. Foundations do not "
                "nest — decompose the foundation's territory "
                "exhaustively into concrete subcomponents with no "
                "sub-foundation catch-all. Remove the <foundation/> "
                "marker from the listed subcomponent(s)."
            )
    else:
        if len(foundation_aliases) == 0:
            raise ValidationError(
                "<subcomponents> has no foundation subcomponent. When a "
                "component decomposes, exactly one subcomponent must carry "
                "a self-closing <foundation/> marker — it owns the "
                "component's root folder territory. Un-fanned-out "
                "components (empty <subcomponents>) do not need one, but "
                "once you decompose at all, a foundation is required."
            )
        if len(foundation_aliases) > 1:
            raise ValidationError(
                f"<subcomponents> has {len(foundation_aliases)} foundation "
                f"subcomponents ({', '.join(sorted(foundation_aliases))}). "
                "Exactly one foundation is required; promote the others to "
                "regular subcomponents or merge them into the single "
                "foundation."
            )

    missing = sorted(known_subresp_ids - set(assigned_subresp_ids.keys()))
    if missing:
        raise ValidationError(
            "<subcomponents> does not assign every pre-minted "
            "subresponsibility to a subcomponent. Missing: "
            f"{', '.join(missing)}. Every subresp from the input list "
            "must appear in exactly one subcomponent's "
            "<responsibilities> block."
        )

    return tuple(subcomponents)


def _validate_subcomponent(
    node: TagNode, *, index: int, known_subresp_ids: set[str]
) -> Subcomponent:
    """Validate a single ``<subcomponent>`` entry."""
    pos = f"<subcomponent> at position {index}"

    alias = node.attrs.get("alias", "").strip()
    if not alias:
        raise ValidationError(
            f"{pos} is missing the alias attribute. Every subcomponent "
            'must carry alias="..." (lowercase snake_case, 1-32 chars, '
            "starts with a letter)."
        )
    if not _ALIAS_RE.match(alias):
        raise ValidationError(
            f"{pos} has invalid alias {alias!r}. Aliases must match "
            "^[a-z][a-z0-9_]{0,31}$ — lowercase letter first, then "
            "lowercase alphanumerics or underscores, 1-32 characters."
        )

    for child in node.children:
        if child.tag not in _SUBCOMPONENT_ALLOWED_CHILDREN:
            raise ValidationError(
                f"{pos} (alias={alias!r}) contains an unexpected child "
                f"<{child.tag}>. Allowed children are: "
                f"{sorted(_SUBCOMPONENT_ALLOWED_CHILDREN)}. Note: "
                "subcomponents do NOT have a <kind> tag — kind is "
                "inherited from the owning component."
            )

    def _require_one(tag: str) -> TagNode:
        matching = node.find_all(tag)
        if len(matching) == 0:
            raise ValidationError(
                f"{pos} (alias={alias!r}) is missing a <{tag}> child. "
                "Every subcomponent must have exactly one."
            )
        if len(matching) > 1:
            raise ValidationError(
                f"{pos} (alias={alias!r}) has {len(matching)} <{tag}> "
                "children; exactly one is required."
            )
        return matching[0]

    name_node = _require_one("name")
    role_node = _require_one("role")
    api_intent_node = _require_one("api-intent")
    responsibilities_node = _require_one("responsibilities")

    name = (name_node.text or "").strip()
    if not name:
        raise ValidationError(
            f"{pos} (alias={alias!r}) has an empty <name>. The display "
            "name must be a short title-case identifier."
        )

    role = (role_node.text or "").strip()
    if not role:
        raise ValidationError(
            f"{pos} (alias={alias!r}) has an empty <role>. Every "
            "subcomponent must have a role paragraph describing what "
            "it does within this component."
        )

    api_intent = (api_intent_node.text or "").strip()
    if not api_intent:
        raise ValidationError(
            f"{pos} (alias={alias!r}) has an empty <api-intent>. Every "
            "subcomponent must describe the shape of its intended API."
        )

    for rchild in responsibilities_node.children:
        if rchild.tag not in _RESPONSIBILITIES_ALLOWED_CHILDREN:
            raise ValidationError(
                f"{pos} (alias={alias!r}) has a <responsibilities> "
                f"block containing an unexpected child <{rchild.tag}>. "
                'Only <resp id="resp_..."/> entries are allowed.'
            )
    resp_nodes = responsibilities_node.find_all("resp")
    if not resp_nodes:
        raise ValidationError(
            f"{pos} (alias={alias!r}) has an empty <responsibilities> "
            "block. Every subcomponent must be assigned at least one "
            'pre-minted subresponsibility via a <resp id="resp_..."/> child.'
        )
    resp_refs: list[str] = []
    seen_refs: set[str] = set()
    for ri, rnode in enumerate(resp_nodes):
        rid = rnode.attrs.get("id", "").strip()
        if not rid:
            raise ValidationError(
                f"{pos} (alias={alias!r}) has a <resp> entry at position "
                f"{ri} with no id attribute. Every <resp> must carry "
                'an id="resp_..." attribute referencing a pre-minted '
                "subresponsibility."
            )
        if rid in seen_refs:
            raise ValidationError(
                f"{pos} (alias={alias!r}) has duplicate <resp> reference "
                f"{rid!r}. Each subresponsibility may be listed at most "
                "once per subcomponent."
            )
        seen_refs.add(rid)
        if rid not in known_subresp_ids:
            raise ValidationError(
                f"{pos} (alias={alias!r}) references unknown "
                f"subresponsibility {rid!r}. Valid pre-minted subresps "
                f"for this component: {', '.join(sorted(known_subresp_ids))}."
            )
        resp_refs.append(rid)

    is_foundation = len(node.find_all("foundation")) > 0

    return Subcomponent(
        alias=alias,
        name=name,
        role=role,
        api_intent=api_intent,
        resp_refs=tuple(resp_refs),
        is_foundation=is_foundation,
    )


def _validate_arch_doc_sub_dependencies(node: TagNode, alias_set: set[str]) -> tuple[DepEdge, ...]:
    """Validate ``<sub-dependencies>`` and return a tuple of DepEdge.

    Same shape as the sysarch dependencies validator: every
    ``<dep from="ALIAS1" to="ALIAS2"/>`` must reference aliases
    declared in ``<subcomponents>``, no self-deps. Acyclicity
    and foundation-dep enforcement happen in the caller via
    :func:`_detect_dep_cycles` and
    :func:`_enforce_sub_foundation_dependency`.
    """
    for child in node.children:
        if child.tag not in _SUB_DEPENDENCIES_ALLOWED_CHILDREN:
            raise ValidationError(
                f"<sub-dependencies> contains an unexpected child "
                f"<{child.tag}>. Only <dep> entries are allowed."
            )
    dep_nodes = node.find_all("dep")
    deps: list[DepEdge] = []
    for index, dnode in enumerate(dep_nodes):
        from_alias = dnode.attrs.get("from", "").strip()
        to_alias = dnode.attrs.get("to", "").strip()
        if not from_alias or not to_alias:
            raise ValidationError(
                f"<dep> at <sub-dependencies> position {index} is "
                "missing a from or to attribute. Every sub-dependency "
                'must carry from="..." to="..." with known aliases.'
            )
        if from_alias not in alias_set:
            raise ValidationError(
                f"<dep> at <sub-dependencies> position {index} has "
                f"unknown from alias {from_alias!r}. Valid aliases: "
                f"{sorted(alias_set)}."
            )
        if to_alias not in alias_set:
            raise ValidationError(
                f"<dep> at <sub-dependencies> position {index} has "
                f"unknown to alias {to_alias!r}. Valid aliases: "
                f"{sorted(alias_set)}."
            )
        if from_alias == to_alias:
            raise ValidationError(
                f"<dep> at <sub-dependencies> position {index} has "
                f"from == to (both {from_alias!r}). A subcomponent "
                "cannot depend on itself."
            )
        deps.append(DepEdge(from_alias=from_alias, to_alias=to_alias))
    return tuple(deps)


@dataclass(frozen=True)
class SubArchDep:
    """A single validated dependency entry from a ``<subcomparch>`` block.

    ``target`` is always a real ``comp_*`` ID — either a
    same-parent sibling subcomponent (which was minted by the
    parent's comparch_mint before this subcomparch gen ran) or
    one of the parent's sibling top-level components. Both kinds
    already exist as nodes at generation time, so the scheme
    doesn't need a placeholder indirection; the mint handler
    uses the target directly when emitting the dependency edge.
    """

    target: str


@dataclass(frozen=True)
class SubArchDoc:
    """The full validated subcomparch output as structured data.

    Fields mirror the four sections of the subcomparch XML. All
    four are fragment sections (stored verbatim as the persistent,
    transcluded content of each subcomponent's fragments). There
    are no mint-time directives at this tier — subcomponents are
    leaves in the comp tree and cannot decompose further, and
    they don't mint new policies.

    ``deps`` holds a tuple of :class:`SubArchDep`. The mint
    handler walks this tuple and emits ``dependency`` edges for
    each entry directly — every target is already a real
    ``comp_*`` ID (same-parent sibling or parent-sibling
    top-level), so no alias resolution is needed at mint time.
    """

    techspec: str
    pubapi: str
    privapi: str
    deps: tuple[SubArchDep, ...]


_SUBCOMPARCH_ALLOWED_CHILDREN = {
    "technical-specification",
    "public-surface",
    "private-surface",
    "dependencies",
}
_SUBCOMPARCH_REQUIRED_ORDER = (
    "technical-specification",
    "public-surface",
    "private-surface",
    "dependencies",
)
_SUBCOMPARCH_FORBIDDEN_CHILDREN = {
    "policies": (
        "subcomponents don't have policies — policies live only at the "
        "top-level comparch tier. If a cross-cutting invariant is "
        "needed, it belongs on the parent component's arch doc, not "
        "here."
    ),
    "subcomponents": (
        "subcomponents can't decompose further — the reducer enforces "
        "a two-level comp_* depth cap. Describe any internal "
        "structure in <private-surface> prose or code blocks instead."
    ),
    "sub-dependencies": (
        "subcomponents can't decompose further — there are no "
        "nested sub-sub-components to have dependencies between."
    ),
}


def validate_sub_arch_doc(
    tree: TagNode,
    *,
    known_sibling_sub_ids: set[str],
    known_parent_sibling_comp_ids: set[str],
) -> SubArchDoc:
    """Validate a parsed ``<subcomparch>`` tree and return a SubArchDoc.

    Enforces the four-section structure described in
    :mod:`backend.graph.prompts.subcomparch`: single root, four
    sections in order, non-empty fragment text for the first three,
    and a ``<dependencies>`` section whose ``<dep to="..."/>``
    entries are all real ``comp_*`` IDs drawn from one of two
    allowlists.

    ``known_sibling_sub_ids`` is the set of real ``comp_*`` IDs
    for same-parent sibling subcomponents (excluding self). These
    were minted by the parent component's comparch_mint before
    this subcomparch gen ran, so the IDs are stable and the LLM
    references them directly rather than via a placeholder alias.

    ``known_parent_sibling_comp_ids`` is the set of real
    ``comp_*`` IDs for top-level components other than the
    parent of this subcomponent.

    ``<dependencies>`` may be empty (leaf subcomponent).
    """
    if tree.tag != "subcomparch":
        raise ValidationError(
            f"Expected root tag <subcomparch>, got <{tree.tag}>. "
            "Wrap the subcomponent architecture doc in a single "
            "<subcomparch>...</subcomparch> block."
        )

    section_map: dict[str, TagNode] = {}
    for child in tree.children:
        if child.tag in _SUBCOMPARCH_FORBIDDEN_CHILDREN:
            reason = _SUBCOMPARCH_FORBIDDEN_CHILDREN[child.tag]
            raise ValidationError(
                f"<subcomparch> contains a forbidden <{child.tag}> section: {reason}"
            )
        if child.tag not in _SUBCOMPARCH_ALLOWED_CHILDREN:
            raise ValidationError(
                f"<subcomparch> contains an unexpected child "
                f"<{child.tag}>. Allowed children are: "
                f"{sorted(_SUBCOMPARCH_ALLOWED_CHILDREN)}."
            )
        if child.tag in section_map:
            raise ValidationError(
                f"<subcomparch> contains more than one <{child.tag}> "
                "section; exactly one of each section is required."
            )
        section_map[child.tag] = child

    actual_order = [c.tag for c in tree.children if c.tag in _SUBCOMPARCH_REQUIRED_ORDER]
    if actual_order != list(_SUBCOMPARCH_REQUIRED_ORDER):
        raise ValidationError(
            f"<subcomparch> sections are not in the required order. "
            f"Expected: {list(_SUBCOMPARCH_REQUIRED_ORDER)}. "
            f"Got: {actual_order}. "
            "Reorder the children of <subcomparch> to match the "
            "required sequence."
        )

    techspec = _validate_fragment_section(
        section_map["technical-specification"], "technical-specification"
    )
    pubapi = _validate_fragment_section(section_map["public-surface"], "public-surface")
    privapi = _validate_fragment_section(section_map["private-surface"], "private-surface")

    deps = _validate_sub_arch_doc_dependencies(
        section_map["dependencies"],
        known_sibling_sub_ids=known_sibling_sub_ids,
        known_parent_sibling_comp_ids=known_parent_sibling_comp_ids,
    )

    return SubArchDoc(
        techspec=techspec,
        pubapi=pubapi,
        privapi=privapi,
        deps=deps,
    )


def _validate_sub_arch_doc_dependencies(
    node: TagNode,
    *,
    known_sibling_sub_ids: set[str],
    known_parent_sibling_comp_ids: set[str],
) -> tuple[SubArchDep, ...]:
    """Validate ``<dependencies>`` at the subcomparch tier.

    Every ``<dep to="..."/>`` target must be a real ``comp_*`` ID
    drawn from the union of two allowlists:

    * ``known_sibling_sub_ids`` — same-parent sibling
      subcomponents (minted by the parent's comparch_mint before
      this gen ran).
    * ``known_parent_sibling_comp_ids`` — top-level components
      other than this subcomponent's parent.

    The two sets never overlap (a node can't be both a
    subcomponent of this parent AND a top-level), so a single
    "unknown target" error is enough. Duplicates are rejected.
    Non-``comp_`` prefixes are rejected with a clear message
    (legacy alias scheme — removed). Empty ``<dependencies>`` is
    legal (leaf subcomponent with no external deps).
    """
    for child in node.children:
        if child.tag not in _DEPENDENCIES_ALLOWED_CHILDREN:
            raise ValidationError(
                f"<dependencies> contains an unexpected child "
                f"<{child.tag}>. Only <dep> entries are allowed."
            )
    dep_nodes = node.find_all("dep")
    deps: list[SubArchDep] = []
    seen: set[str] = set()
    allowed_targets = known_sibling_sub_ids | known_parent_sibling_comp_ids
    for index, dnode in enumerate(dep_nodes):
        target = dnode.attrs.get("to", "").strip()
        if not target:
            raise ValidationError(
                f"<dep> at position {index} is missing the to "
                'attribute. Every <dep> must carry to="comp_..." '
                "with the real ID of a same-parent sibling "
                "subcomponent or a parent-sibling top-level "
                "component."
            )
        if dnode.attrs.get("from"):
            raise ValidationError(
                f"<dep> at position {index} has a from attribute. "
                "Subcomparch <dependencies> entries are always from "
                "this subcomponent implicitly — do not add "
                'from="..." to <dep> entries.'
            )
        if not target.startswith("comp_"):
            raise ValidationError(
                f"<dep> at position {index} targets {target!r}, "
                'which is not a comp_* ID. Use to="comp_XXXXXXXX" '
                "with the real ID of a same-parent sibling "
                "subcomponent or a parent-sibling top-level "
                "component. (The alias scheme was removed in "
                "favour of direct IDs — siblings already have "
                "stable IDs at subcomparch generation time.)"
            )
        if target in seen:
            raise ValidationError(
                f"<dependencies> lists duplicate target {target!r}. "
                "Each dependency target may appear at most once."
            )
        seen.add(target)

        if target not in allowed_targets:
            sibling_list = sorted(known_sibling_sub_ids) or ["(no same-parent siblings)"]
            parent_sibling_list = sorted(known_parent_sibling_comp_ids) or [
                "(no parent-sibling top-level components)"
            ]
            raise ValidationError(
                f"<dep> at position {index} targets {target!r}, "
                "which is not in the allowed set. Valid same-"
                f"parent sibling IDs: {sibling_list}. Valid "
                f"parent-sibling top-level IDs: {parent_sibling_list}."
            )

        deps.append(SubArchDep(target=target))

    return tuple(deps)


def _enforce_sub_foundation_dependency(
    subcomponents: tuple[Subcomponent, ...], deps: tuple[DepEdge, ...]
) -> None:
    """Every non-foundation subcomponent must depend on the foundation.

    Mirrors :func:`_enforce_foundation_dependency` at the
    subcomponent layer. Inlined rather than refactored to a
    shared generic helper because the call sites type the
    components differently (``Component`` vs ``Subcomponent``)
    and a Protocol/TypeVar refactor is more ceremony than this
    five-line check deserves.
    """
    foundation_alias = next(s.alias for s in subcomponents if s.is_foundation)
    required_from = {s.alias for s in subcomponents if not s.is_foundation}
    seen: set[str] = {d.from_alias for d in deps if d.to_alias == foundation_alias}
    missing = sorted(required_from - seen)
    if missing:
        raise ValidationError(
            "Every non-foundation subcomponent must have a <dep> edge "
            f"pointing at the foundation subcomponent {foundation_alias!r}. "
            f"Missing foundation dependency from: {', '.join(missing)}. "
            'Add <dep from="<alias>" to="' + foundation_alias + '"/> '
            "for each missing subcomponent."
        )


# ── Policy application pass (Phase 4) ──────────────────────────────


@dataclass(frozen=True)
class PolicyApplicationDecision:
    """One LLM decision on whether a policy applies to a target.

    ``applies`` is True for ``<applies>`` entries and False for
    ``<does-not-apply>`` entries. ``rationale`` is the paragraph
    the LLM wrote justifying the decision — captured in handler
    logs but not stored in the DB per the Phase 4 stage 9 design
    call.
    """

    policy_id: str
    applies: bool
    rationale: str


_POLICY_APPLICATIONS_ALLOWED_CHILDREN = {"applies", "does-not-apply"}


def validate_policy_applications(
    tree: TagNode, *, known_policy_ids: set[str]
) -> tuple[PolicyApplicationDecision, ...]:
    """Validate a parsed ``<policy-applications>`` tree.

    Enforces: every candidate policy in ``known_policy_ids`` is
    covered exactly once by either an ``<applies>`` or a
    ``<does-not-apply>`` entry, every ``policy`` attribute
    references a known policy ID, and every entry has a
    non-empty ``<rationale>`` child.

    Returns a tuple of :class:`PolicyApplicationDecision` in the
    order the entries appeared in the XML.
    """
    if tree.tag != "policy-applications":
        raise ValidationError(
            f"Expected root tag <policy-applications>, got <{tree.tag}>. "
            "Wrap the application decisions in a single "
            "<policy-applications>...</policy-applications> block."
        )

    decisions: list[PolicyApplicationDecision] = []
    seen: dict[str, str] = {}  # policy_id → which tag it appeared under
    for index, child in enumerate(tree.children):
        if child.tag not in _POLICY_APPLICATIONS_ALLOWED_CHILDREN:
            raise ValidationError(
                f"<policy-applications> contains an unexpected child "
                f"<{child.tag}>. Only <applies> and <does-not-apply> "
                "entries are allowed."
            )
        policy_id = child.attrs.get("policy", "").strip()
        if not policy_id:
            raise ValidationError(
                f"<{child.tag}> at position {index} is missing the policy "
                "attribute. Every entry must carry "
                'policy="policy_..." with a known policy ID.'
            )
        if policy_id not in known_policy_ids:
            raise ValidationError(
                f"<{child.tag}> at position {index} references unknown "
                f"policy {policy_id!r}. Valid candidate IDs: "
                f"{sorted(known_policy_ids)}."
            )
        if policy_id in seen:
            raise ValidationError(
                f"<{child.tag}> at position {index} is a duplicate entry "
                f"for policy {policy_id!r}. The previous occurrence was "
                f"inside <{seen[policy_id]}>. Each candidate policy must "
                "appear exactly once."
            )
        seen[policy_id] = child.tag

        rationale_children = child.find_all("rationale")
        if len(rationale_children) == 0:
            raise ValidationError(
                f"<{child.tag} policy={policy_id!r}> is missing a "
                "<rationale> child. Both applies and does-not-apply "
                "entries require a rationale paragraph."
            )
        if len(rationale_children) > 1:
            raise ValidationError(
                f"<{child.tag} policy={policy_id!r}> has "
                f"{len(rationale_children)} <rationale> children; exactly "
                "one is required."
            )
        rationale_text = (rationale_children[0].text or "").strip()
        if not rationale_text:
            raise ValidationError(
                f"<{child.tag} policy={policy_id!r}> has an empty "
                "<rationale>. The rationale must explain why the policy "
                "does (or does not) apply to this target."
            )

        decisions.append(
            PolicyApplicationDecision(
                policy_id=policy_id,
                applies=(child.tag == "applies"),
                rationale=rationale_text,
            )
        )

    missing = sorted(known_policy_ids - set(seen.keys()))
    if missing:
        raise ValidationError(
            "<policy-applications> does not cover every candidate "
            f"policy. Missing: {', '.join(missing)}. Every candidate "
            "policy must appear exactly once as either <applies> or "
            "<does-not-apply>."
        )

    return tuple(decisions)


# ── Vocabulary ──────────────────────────────────────────────────────
#
# Phase 5.5: project vocabulary layer. The expansion output can
# carry an optional ``<vocabulary>`` sibling section alongside
# ``<features>``, containing ``<term>`` elements that project
# into ``vocab_*`` nodes on expansion approval. See
# ``docs/architecture/v2-rearchitecture.md`` §Project vocabulary.


_VOCAB_TERM_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 \-_]{0,63}$")
_VOCAB_ENTRY_ALLOWED_CHILDREN = {"definition", "disambiguation", "see-also"}
_VOCAB_ENTRY_REQUIRED_ORDER = ("definition", "disambiguation", "see-also")


@dataclass(frozen=True)
class VocabRef:
    """A single ``<ref>`` entry inside a ``<see-also>`` block.

    Exactly one of ``name`` or ``to`` is set — the validator
    rejects entries with both or neither.

    ``name`` form is used at cold-start expansion time, where the
    referenced target terms are being minted in the same pass and
    their IDs don't yet exist. ``to`` form uses a real
    ``vocab_xxxxxxxx`` id and is only accepted post-mint, when
    existing terms can be referenced directly.
    """

    name: str | None
    to: str | None


@dataclass(frozen=True)
class VocabEntry:
    """A single validated ``<term>`` entry from a ``<vocabulary>`` block.

    Carries both the mint-time metadata (``name``, ``scope``,
    ``feature_name``) and the parsed inner ``<vocab-entry>``
    grammar (``definition``, ``disambiguation``, ``see_also_refs``).

    ``raw_content`` is the full ``<vocab-entry>...</vocab-entry>``
    XML block as authored by the LLM, preserved verbatim so the
    mint handler can store it as ``Node.content`` without
    re-serializing. This matches how every other parseable-tier
    stores its full approved content.
    """

    name: str
    scope: Literal["project", "feature"]
    feature_name: str | None  # None when scope == "project"
    definition: str
    disambiguation: str | None
    see_also_refs: tuple[VocabRef, ...]
    raw_content: str


def validate_vocabulary(
    tree: TagNode,
    *,
    known_feature_names: set[str],
    allow_id_refs: bool = False,
) -> tuple[VocabEntry, ...]:
    """Validate a parsed ``<vocabulary>`` tree and return its entries.

    Shape:

    * ``tree.tag`` must be exactly ``"vocabulary"``.
    * Children must all be ``<term>`` elements; unknown tags are
      rejected.
    * Each ``<term>`` must have:
      * a ``name=`` attribute matching a simple vocabulary-name
        regex (alphanumerics, spaces, hyphens, underscores; 1-64
        chars).
      * a ``scope=`` attribute equal to ``"project"`` or ``"feature"``.
      * when ``scope="feature"``, a ``feature-name=`` attribute
        whose value matches one of ``known_feature_names``.
    * Each ``<term>`` must contain exactly one ``<vocab-entry>``
      child, which has the following inner grammar (children in
      fixed order when present):
      * ``<definition>`` — required, non-empty, plain text.
      * ``<disambiguation>`` — optional, non-empty when present,
        plain text.
      * ``<see-also>`` — optional. May contain only ``<ref>``
        children. Each ``<ref>`` carries either ``name=`` (cold-
        start form) or ``to=`` (post-mint ID form, only accepted
        when ``allow_id_refs=True``) but not both.
      * Within a single ``<see-also>``, refs must be unique — no
        duplicates by name or by to.
    * Names are unique within a scope: two project-level terms
      cannot share a name, and two feature-local terms within the
      same feature (matched by ``feature-name``) cannot share a
      name. A project-level and feature-local term can share a
      name.
    * Empty ``<vocabulary>`` is legal — the function returns an
      empty tuple.

    ``known_feature_names`` is the set of feature names parsed
    from the sibling ``<features>`` block; the caller passes it
    in because validator shares are always explicit.

    ``allow_id_refs`` is ``False`` at cold-start expansion time
    (the default) and ``True`` at post-mint edit time where the
    referenced vocab nodes already exist as real DB rows.

    Returns a tuple of :class:`VocabEntry` in document order.
    Raises :class:`ValidationError` on the first problem found.
    """
    if tree.tag != "vocabulary":
        raise ValidationError(
            f"Expected root tag <vocabulary>, got <{tree.tag}>. "
            "Wrap the vocabulary in a single "
            "<vocabulary>...</vocabulary> block."
        )

    for child in tree.children:
        if child.tag != "term":
            raise ValidationError(
                f"<vocabulary> contains an unexpected child "
                f"<{child.tag}>. Only <term> entries are allowed at "
                "this level."
            )

    entries: list[VocabEntry] = []
    seen_project_names: set[str] = set()
    # Feature-local name uniqueness is (feature_name, term_name).
    seen_feature_names: set[tuple[str, str]] = set()

    for index, term_node in enumerate(tree.children):
        entry = _validate_vocab_term(
            term_node,
            index=index,
            known_feature_names=known_feature_names,
            allow_id_refs=allow_id_refs,
        )

        if entry.scope == "project":
            if entry.name in seen_project_names:
                raise ValidationError(
                    f"<vocabulary> contains two project-level terms "
                    f"with the same name {entry.name!r}. Term names "
                    "must be unique within a scope."
                )
            seen_project_names.add(entry.name)
        else:
            key = (entry.feature_name or "", entry.name)
            if key in seen_feature_names:
                raise ValidationError(
                    f"<vocabulary> contains two feature-local terms "
                    f"with the same name {entry.name!r} under feature "
                    f"{entry.feature_name!r}. Term names must be "
                    "unique within a (scope, feature) key."
                )
            seen_feature_names.add(key)

        entries.append(entry)

    return tuple(entries)


def _validate_vocab_term(
    node: TagNode,
    *,
    index: int,
    known_feature_names: set[str],
    allow_id_refs: bool,
) -> VocabEntry:
    """Validate a single ``<term>`` element and return a VocabEntry."""
    pos = f"<term> at position {index}"

    name = node.attrs.get("name", "").strip()
    if not name:
        raise ValidationError(
            f"{pos} is missing the name attribute. Every term must "
            'carry name="..." with the term being defined.'
        )
    if not _VOCAB_TERM_NAME_RE.match(name):
        raise ValidationError(
            f"{pos} has invalid name {name!r}. Term names must "
            "match alphanumerics, spaces, hyphens, or underscores, "
            "1-64 characters, starting with an alphanumeric."
        )

    scope_attr = node.attrs.get("scope", "").strip()
    if scope_attr not in {"project", "feature"}:
        raise ValidationError(
            f"{pos} (name={name!r}) has invalid scope attribute "
            f"{scope_attr!r}. Must be exactly 'project' or "
            "'feature'."
        )
    scope: Literal["project", "feature"] = scope_attr  # type: ignore[assignment]

    feature_name: str | None = None
    if scope == "feature":
        feature_name = node.attrs.get("feature-name", "").strip() or None
        if feature_name is None:
            raise ValidationError(
                f'{pos} (name={name!r}) has scope="feature" but is '
                "missing the feature-name attribute. Feature-local "
                'terms must carry feature-name="..." matching a '
                "feature in the same <features> block."
            )
        if feature_name not in known_feature_names:
            valid_list = (
                ", ".join(sorted(known_feature_names))
                if known_feature_names
                else "(no features defined)"
            )
            raise ValidationError(
                f"{pos} (name={name!r}) references feature "
                f"{feature_name!r}, which is not defined in the "
                f"sibling <features> block. Valid feature names: "
                f"{valid_list}."
            )

    # Exactly one <vocab-entry> child, no other tags.
    for child in node.children:
        if child.tag != "vocab-entry":
            raise ValidationError(
                f"{pos} (name={name!r}) contains an unexpected child "
                f"<{child.tag}>. A <term> must contain exactly one "
                "<vocab-entry> child."
            )
    ve_children = node.find_all("vocab-entry")
    if len(ve_children) == 0:
        raise ValidationError(
            f"{pos} (name={name!r}) is missing a <vocab-entry> child. "
            "A <term> must contain exactly one <vocab-entry> with "
            "the term's definition and optional disambiguation and "
            "see-also."
        )
    if len(ve_children) > 1:
        raise ValidationError(
            f"{pos} (name={name!r}) has {len(ve_children)} "
            "<vocab-entry> children; exactly one is required."
        )
    ve_node = ve_children[0]

    # Validate <vocab-entry> inner grammar.
    definition, disambiguation, refs = _validate_vocab_entry_inner(
        ve_node,
        parent_pos=pos,
        term_name=name,
        allow_id_refs=allow_id_refs,
    )

    # Build raw_content: serialize the <vocab-entry> back to a
    # string form for storage on Node.content. Simple approach:
    # use the inner-text range if the parser exposes it, else
    # rebuild a canonical form. The xml_sections parser returns
    # TagNodes without source-range tracking, so we rebuild from
    # the parsed structure.
    raw_content = _serialize_vocab_entry(ve_node)

    return VocabEntry(
        name=name,
        scope=scope,
        feature_name=feature_name,
        definition=definition,
        disambiguation=disambiguation,
        see_also_refs=refs,
        raw_content=raw_content,
    )


def _validate_vocab_entry_inner(
    node: TagNode,
    *,
    parent_pos: str,
    term_name: str,
    allow_id_refs: bool,
) -> tuple[str, str | None, tuple[VocabRef, ...]]:
    """Validate the inner children of a ``<vocab-entry>`` element.

    Returns ``(definition, disambiguation_or_none, see_also_refs)``.
    """
    for child in node.children:
        if child.tag not in _VOCAB_ENTRY_ALLOWED_CHILDREN:
            raise ValidationError(
                f"{parent_pos} (name={term_name!r}) <vocab-entry> "
                f"contains an unexpected child <{child.tag}>. "
                f"Allowed children are: "
                f"{sorted(_VOCAB_ENTRY_ALLOWED_CHILDREN)}."
            )

    # Check for duplicates and enforce the fixed order.
    seen: dict[str, TagNode] = {}
    for child in node.children:
        if child.tag in seen:
            raise ValidationError(
                f"{parent_pos} (name={term_name!r}) <vocab-entry> has "
                f"more than one <{child.tag}> child; at most one is "
                "allowed."
            )
        seen[child.tag] = child

    actual_order = [c.tag for c in node.children if c.tag in _VOCAB_ENTRY_REQUIRED_ORDER]
    expected_order = [tag for tag in _VOCAB_ENTRY_REQUIRED_ORDER if tag in seen]
    if actual_order != expected_order:
        raise ValidationError(
            f"{parent_pos} (name={term_name!r}) <vocab-entry> "
            "children are not in the required order. Expected: "
            f"{expected_order}. Got: {actual_order}. Reorder to "
            "<definition> → <disambiguation> → <see-also>."
        )

    # <definition> is required and non-empty plain text.
    if "definition" not in seen:
        raise ValidationError(
            f"{parent_pos} (name={term_name!r}) <vocab-entry> is "
            "missing the required <definition> child. Every vocab "
            "entry must have a non-empty definition."
        )
    definition_node = seen["definition"]
    if definition_node.children:
        raise ValidationError(
            f"{parent_pos} (name={term_name!r}) <definition> must "
            "contain plain text only, no nested XML tags."
        )
    definition = (definition_node.text or "").strip()
    if not definition:
        raise ValidationError(
            f"{parent_pos} (name={term_name!r}) <definition> is "
            "empty. The definition must be non-empty prose."
        )

    # <disambiguation> is optional and non-empty plain text when present.
    disambiguation: str | None = None
    if "disambiguation" in seen:
        dis_node = seen["disambiguation"]
        if dis_node.children:
            raise ValidationError(
                f"{parent_pos} (name={term_name!r}) <disambiguation> "
                "must contain plain text only, no nested XML tags."
            )
        dis_text = (dis_node.text or "").strip()
        if not dis_text:
            raise ValidationError(
                f"{parent_pos} (name={term_name!r}) <disambiguation> "
                "is present but empty. Remove the tag or provide "
                "non-empty prose."
            )
        disambiguation = dis_text

    # <see-also> is optional; when present contains <ref> children.
    refs: tuple[VocabRef, ...] = ()
    if "see-also" in seen:
        refs = _validate_vocab_see_also(
            seen["see-also"],
            parent_pos=parent_pos,
            term_name=term_name,
            allow_id_refs=allow_id_refs,
        )

    return definition, disambiguation, refs


def _validate_vocab_see_also(
    node: TagNode,
    *,
    parent_pos: str,
    term_name: str,
    allow_id_refs: bool,
) -> tuple[VocabRef, ...]:
    """Validate a ``<see-also>`` element and return its refs."""
    for child in node.children:
        if child.tag != "ref":
            raise ValidationError(
                f"{parent_pos} (name={term_name!r}) <see-also> "
                f"contains an unexpected child <{child.tag}>. Only "
                "<ref> elements are allowed."
            )

    refs: list[VocabRef] = []
    seen_targets: set[str] = set()
    for ref_index, ref_node in enumerate(node.children):
        name_attr = ref_node.attrs.get("name", "").strip() or None
        to_attr = ref_node.attrs.get("to", "").strip() or None

        if name_attr is None and to_attr is None:
            raise ValidationError(
                f"{parent_pos} (name={term_name!r}) <see-also> "
                f"<ref> at position {ref_index} has neither name "
                "nor to attribute. Each <ref> must carry exactly "
                'one of name="..." or to="vocab_xxxxxxxx".'
            )
        if name_attr is not None and to_attr is not None:
            raise ValidationError(
                f"{parent_pos} (name={term_name!r}) <see-also> "
                f"<ref> at position {ref_index} has both name and "
                "to attributes. Each <ref> must carry exactly one "
                "of the two, not both."
            )
        if to_attr is not None and not allow_id_refs:
            raise ValidationError(
                f"{parent_pos} (name={term_name!r}) <see-also> "
                f"<ref> at position {ref_index} uses id form "
                f'to="{to_attr}". At cold-start expansion time only '
                "name form is accepted, because the referenced terms "
                "are being minted in the same pass and their IDs "
                "don't exist yet. Use name= instead."
            )

        target_key = name_attr or to_attr or ""  # exactly one is set
        if target_key in seen_targets:
            raise ValidationError(
                f"{parent_pos} (name={term_name!r}) <see-also> has "
                f"duplicate reference to {target_key!r}. Each term "
                "can be referenced at most once per see-also list."
            )
        seen_targets.add(target_key)

        refs.append(VocabRef(name=name_attr, to=to_attr))

    return tuple(refs)


def _serialize_vocab_entry(node: TagNode) -> str:
    """Rebuild a canonical ``<vocab-entry>...</vocab-entry>`` XML string.

    The xml_sections parser doesn't track source ranges, so we
    rebuild from the validated structure. The canonical form:

    * Opening ``<vocab-entry>`` tag (no attributes).
    * For each child in document order:
      * ``<definition>`` / ``<disambiguation>``: the stripped text
        wrapped in the tag.
      * ``<see-also>``: each ``<ref>`` as a self-closing element
        with its one attribute.
    * Closing ``</vocab-entry>`` tag.

    Whitespace is normalized (single spaces between tags, newlines
    between sibling elements). The serialized form is what
    ``Node.content`` will store; downstream consumers parse it
    back via ``extract_tag_tree`` and this same validator.
    """
    parts: list[str] = ["<vocab-entry>"]
    for child in node.children:
        if child.tag == "definition":
            parts.append(f"  <definition>{(child.text or '').strip()}</definition>")
        elif child.tag == "disambiguation":
            parts.append(f"  <disambiguation>{(child.text or '').strip()}</disambiguation>")
        elif child.tag == "see-also":
            parts.append("  <see-also>")
            for ref in child.children:
                name_attr = ref.attrs.get("name", "").strip() or None
                to_attr = ref.attrs.get("to", "").strip() or None
                if name_attr is not None:
                    parts.append(f'    <ref name="{name_attr}"/>')
                elif to_attr is not None:
                    parts.append(f'    <ref to="{to_attr}"/>')
            parts.append("  </see-also>")
    parts.append("</vocab-entry>")
    return "\n".join(parts)


# ── References (Phase 6.6: ref_* node tier + reference edge type) ────
#
# Refs are first-class supplemental documents. Each ref's stored
# content is a parseable ``<reference>`` XML block with a required
# ``<title>``, a required ``<body>`` (opaque markdown, validator
# doesn't parse its contents), and an optional ``<see-also>``
# carrying ``<ref to="ref_..."/>`` children. See
# ``docs/architecture/v2-rearchitecture.md`` §Project references.


_REF_ID_RE = re.compile(r"^ref_[0-9A-HJKMNP-TV-Z]{8}$")
_REFERENCE_ALLOWED_CHILDREN = {"title", "body", "see-also"}
_REFERENCE_REQUIRED_ORDER = ("title", "body", "see-also")


@dataclass(frozen=True)
class ReferenceRef:
    """A single ``<ref>`` entry inside a reference's ``<see-also>`` block.

    Unlike vocab refs (which carry either ``name`` or ``to``),
    reference refs always use the id form — refs are minted up
    front and their IDs are stable by the time any ``<see-also>``
    that mentions them is authored.
    """

    to: str


@dataclass(frozen=True)
class ReferenceEntry:
    """A single validated ``<reference>`` block.

    Carries the parsed grammar (``title``, ``body``,
    ``see_also_refs``) plus ``raw_content`` — the full
    ``<reference>...</reference>`` XML as authored, preserved
    verbatim so the handler can store it on ``Node.content``
    without re-serializing.
    """

    title: str
    body: str
    see_also_refs: tuple[ReferenceRef, ...]
    raw_content: str


def validate_reference(tree: TagNode, *, raw_content: str) -> ReferenceEntry:
    """Validate a parsed ``<reference>`` tree and return its entry.

    Grammar:

    * ``tree.tag`` must be exactly ``"reference"``.
    * Children must all be one of ``<title>`` / ``<body>`` /
      ``<see-also>``; unknown tags are rejected.
    * ``<title>`` is required, exactly one, plain text, non-empty.
    * ``<body>`` is required, exactly one, non-empty. The body is
      opaque — the validator does not parse its contents; nested
      markup, markdown, and prose are all allowed as-is.
    * ``<see-also>`` is optional, at most one. When present it
      contains only ``<ref to="ref_..."/>`` children. ``to=`` must
      match the ``ref_xxxxxxxx`` ID form. Duplicates within a
      single ``<see-also>`` are rejected.
    * Children must appear in the fixed order
      ``<title>`` → ``<body>`` → ``<see-also>`` when present.

    ``raw_content`` is the original full string the tree was
    parsed from; the validator stores a reference to it on the
    returned entry so the caller can persist it verbatim.

    Returns a single :class:`ReferenceEntry`. Raises
    :class:`ValidationError` on the first problem found.
    """
    if tree.tag != "reference":
        raise ValidationError(
            f"Expected root tag <reference>, got <{tree.tag}>. "
            "Wrap the reference content in a single "
            "<reference>...</reference> block."
        )

    for child in tree.children:
        if child.tag not in _REFERENCE_ALLOWED_CHILDREN:
            raise ValidationError(
                f"<reference> contains an unexpected child "
                f"<{child.tag}>. Allowed children are: "
                f"{sorted(_REFERENCE_ALLOWED_CHILDREN)}."
            )

    # Check for duplicates and enforce the fixed order.
    seen: dict[str, TagNode] = {}
    for child in tree.children:
        if child.tag in seen:
            raise ValidationError(
                f"<reference> has more than one <{child.tag}> child; at most one is allowed."
            )
        seen[child.tag] = child

    actual_order = [c.tag for c in tree.children if c.tag in _REFERENCE_REQUIRED_ORDER]
    expected_order = [tag for tag in _REFERENCE_REQUIRED_ORDER if tag in seen]
    if actual_order != expected_order:
        raise ValidationError(
            "<reference> children are not in the required order. "
            f"Expected: {expected_order}. Got: {actual_order}. "
            "Reorder to <title> → <body> → <see-also>."
        )

    # <title> is required, non-empty plain text.
    if "title" not in seen:
        raise ValidationError(
            "<reference> is missing the required <title> child. "
            "Every reference must have a non-empty title."
        )
    title_node = seen["title"]
    if title_node.children:
        raise ValidationError(
            "<reference> <title> must contain plain text only, no nested XML tags."
        )
    title = (title_node.text or "").strip()
    if not title:
        raise ValidationError("<reference> <title> is empty. The title must be non-empty prose.")

    # <body> is required, non-empty; contents are opaque.
    if "body" not in seen:
        raise ValidationError(
            "<reference> is missing the required <body> child. "
            "Every reference must have a non-empty body."
        )
    body_node = seen["body"]
    body = _serialize_body_content(body_node)
    if not body:
        raise ValidationError(
            "<reference> <body> is empty. The body must be non-empty markdown or prose."
        )

    # <see-also> is optional; when present contains <ref to="..."/> children.
    refs: tuple[ReferenceRef, ...] = ()
    if "see-also" in seen:
        refs = _validate_reference_see_also(seen["see-also"])

    return ReferenceEntry(
        title=title,
        body=body,
        see_also_refs=refs,
        raw_content=raw_content,
    )


def _serialize_body_content(node: TagNode) -> str:
    """Collect the opaque content of a ``<body>`` element.

    Body is opaque — it may contain markdown, prose, or even nested
    XML/HTML that we choose not to parse. We join the direct text
    plus any nested children's flattened text, stripped.
    """
    parts: list[str] = []
    if node.text:
        parts.append(node.text)
    for child in node.children:
        fragment = _flatten_text(child)
        if fragment:
            parts.append(fragment)
    return "\n\n".join(p.strip() for p in parts if p.strip())


def _flatten_text(node: TagNode) -> str:
    """Recursively flatten a TagNode into plain text."""
    chunks: list[str] = []
    if node.text:
        chunks.append(node.text)
    for child in node.children:
        chunks.append(_flatten_text(child))
    return " ".join(c for c in chunks if c)


def _validate_reference_see_also(node: TagNode) -> tuple[ReferenceRef, ...]:
    """Validate a reference's ``<see-also>`` and return its refs."""
    for child in node.children:
        if child.tag != "ref":
            raise ValidationError(
                f"<reference> <see-also> contains an unexpected "
                f"child <{child.tag}>. Only <ref to='ref_...'/> "
                "elements are allowed."
            )

    refs: list[ReferenceRef] = []
    seen_targets: set[str] = set()
    for ref_index, ref_node in enumerate(node.children):
        to_attr = ref_node.attrs.get("to", "").strip()
        name_attr = ref_node.attrs.get("name", "").strip()
        if name_attr:
            raise ValidationError(
                f"<reference> <see-also> <ref> at position "
                f"{ref_index} uses name= form. Reference refs must "
                'use to="ref_xxxxxxxx" — refs are minted before any '
                "see-also references them."
            )
        if not to_attr:
            raise ValidationError(
                f"<reference> <see-also> <ref> at position "
                f"{ref_index} is missing the to attribute. Each "
                '<ref> must carry to="ref_xxxxxxxx".'
            )
        if not _REF_ID_RE.match(to_attr):
            raise ValidationError(
                f"<reference> <see-also> <ref> at position "
                f"{ref_index} has to={to_attr!r}, which is not a "
                "valid ref ID. Expected ref_ followed by 8 "
                "Crockford base32 characters."
            )
        if to_attr in seen_targets:
            raise ValidationError(
                "<reference> <see-also> has duplicate reference to "
                f"{to_attr!r}. Each target can be referenced at "
                "most once per see-also list."
            )
        seen_targets.add(to_attr)
        refs.append(ReferenceRef(to=to_attr))

    return tuple(refs)


def parse_and_validate_reference(raw: str) -> ReferenceEntry:
    """Convenience helper: parse ``raw`` and validate in one call.

    Raises :class:`ParseError` if the ``<reference>`` root tag is
    missing (via ``extract_tag_tree``), or :class:`ValidationError`
    if the grammar check fails. Used by the generate_reference
    handler's parse-validate loop and by the route-level
    authoring-time content check.
    """
    tree = extract_tag_tree(raw, "reference")
    return validate_reference(tree, raw_content=raw)


# ── Implementation (Phase 8: impl_* leaf nodes) ──────────────────────
#
# Implementation docs are the last articulation layer before code
# territory. One per leaf (every subcomponent, every un-fanned-out
# top-level comp). Content is a ``<implementation>`` XML block with
# four opaque prose sections in fixed order: <behavior> /
# <invariants> / <sequencing> / <edge-cases>. The validator
# enforces structural presence + ordering but does not parse the
# prose contents — the plan prompt (Phase 14) consumes the whole
# <implementation> block verbatim.


_IMPLEMENTATION_ALLOWED_CHILDREN = {"behavior", "invariants", "sequencing", "edge-cases"}
_IMPLEMENTATION_REQUIRED_ORDER = ("behavior", "invariants", "sequencing", "edge-cases")


@dataclass(frozen=True)
class ImplementationEntry:
    """A single validated ``<implementation>`` block.

    Carries the four prose sections plus ``raw_content`` — the full
    ``<implementation>...</implementation>`` XML as authored,
    preserved verbatim so the handler can store it on
    ``Node.content`` without re-serializing. Mirrors the
    :class:`ReferenceEntry` shape.
    """

    behavior: str
    invariants: str
    sequencing: str
    edge_cases: str
    raw_content: str


def validate_implementation(tree: TagNode, *, raw_content: str) -> ImplementationEntry:
    """Validate a parsed ``<implementation>`` tree and return its entry.

    Grammar:

    * ``tree.tag`` must be exactly ``"implementation"``.
    * Children must all be one of ``<behavior>`` / ``<invariants>``
      / ``<sequencing>`` / ``<edge-cases>``; unknown tags are
      rejected.
    * All four sections are **required**, exactly one of each.
    * Children must appear in the fixed order
      ``<behavior>`` → ``<invariants>`` → ``<sequencing>`` →
      ``<edge-cases>``.
    * Each section must be non-empty — an empty section is a
      structural error because it signals the LLM skipped the
      slot. Contents are opaque (the validator does not parse
      nested structure).

    ``raw_content`` is the original full string the tree was
    parsed from; the validator stores a reference to it on the
    returned entry so the caller can persist it verbatim.

    Returns a single :class:`ImplementationEntry`. Raises
    :class:`ValidationError` on the first problem found.
    """
    if tree.tag != "implementation":
        raise ValidationError(
            f"Expected root tag <implementation>, got <{tree.tag}>. "
            "Wrap the implementation content in a single "
            "<implementation>...</implementation> block."
        )

    for child in tree.children:
        if child.tag not in _IMPLEMENTATION_ALLOWED_CHILDREN:
            raise ValidationError(
                f"<implementation> contains an unexpected child "
                f"<{child.tag}>. Allowed children are: "
                f"{sorted(_IMPLEMENTATION_ALLOWED_CHILDREN)}."
            )

    seen: dict[str, TagNode] = {}
    for child in tree.children:
        if child.tag in seen:
            raise ValidationError(
                f"<implementation> has more than one <{child.tag}> "
                "child; exactly one of each section is required."
            )
        seen[child.tag] = child

    for required in _IMPLEMENTATION_REQUIRED_ORDER:
        if required not in seen:
            raise ValidationError(
                f"<implementation> is missing the required "
                f"<{required}> child. All four sections "
                "(<behavior>, <invariants>, <sequencing>, "
                "<edge-cases>) must be present."
            )

    actual_order = [c.tag for c in tree.children if c.tag in _IMPLEMENTATION_REQUIRED_ORDER]
    expected_order = list(_IMPLEMENTATION_REQUIRED_ORDER)
    if actual_order != expected_order:
        raise ValidationError(
            "<implementation> children are not in the required "
            f"order. Expected: {expected_order}. Got: "
            f"{actual_order}. Reorder to <behavior> → "
            "<invariants> → <sequencing> → <edge-cases>."
        )

    sections: dict[str, str] = {}
    for name in _IMPLEMENTATION_REQUIRED_ORDER:
        body = _collect_implementation_section_text(seen[name])
        if not body:
            raise ValidationError(
                f"<implementation> <{name}> is empty. Every section must carry non-empty prose."
            )
        sections[name] = body

    return ImplementationEntry(
        behavior=sections["behavior"],
        invariants=sections["invariants"],
        sequencing=sections["sequencing"],
        edge_cases=sections["edge-cases"],
        raw_content=raw_content,
    )


def _collect_implementation_section_text(node: TagNode) -> str:
    """Collect opaque prose from an implementation section.

    Sections are prose blobs; nested markup (like short bulleted
    lists the LLM emits as a mix of text + child tags) is
    flattened into plain text, stripped. Matches the
    ``<body>`` handling in reference validation.
    """
    chunks: list[str] = []
    if node.text:
        chunks.append(node.text)
    for child in node.children:
        nested = _flatten_text_recursive(child)
        if nested:
            chunks.append(nested)
    return "\n\n".join(c.strip() for c in chunks if c.strip())


def _flatten_text_recursive(node: TagNode) -> str:
    pieces: list[str] = []
    if node.text:
        pieces.append(node.text)
    for child in node.children:
        pieces.append(_flatten_text_recursive(child))
    return " ".join(p for p in pieces if p)


def parse_and_validate_implementation(raw: str) -> ImplementationEntry:
    """Convenience helper: parse ``raw`` and validate in one call."""
    tree = extract_tag_tree(raw, "implementation")
    return validate_implementation(tree, raw_content=raw)


# ── Fan-in (Phase 7: fanin_* domain synthesis nodes) ─────────────────
#
# Fan-in is the bottom-up counterpart to a domain component's
# top-down comparch. One ``fanin_*`` per fanned-out domain comp,
# sitting at the bottom of its subtree. Content is a ``<fanin>``
# XML block with three opaque prose sections in fixed order:
# <summary> / <exposed-surface> / <realized-behavior>. The
# validator enforces structural presence + ordering but does not
# parse the prose contents — downstream presentational regen
# consumes the whole <fanin> block verbatim as bottom-up context.


_FANIN_ALLOWED_CHILDREN = {"summary", "exposed-surface", "realized-behavior"}
_FANIN_REQUIRED_ORDER = ("summary", "exposed-surface", "realized-behavior")


@dataclass(frozen=True)
class FanInEntry:
    """A single validated ``<fanin>`` block.

    Carries the three prose sections plus ``raw_content`` — the
    full ``<fanin>...</fanin>`` XML as authored, preserved
    verbatim so the handler can store it on ``Node.content``
    without re-serializing. Mirrors the
    :class:`ImplementationEntry` shape.
    """

    summary: str
    exposed_surface: str
    realized_behavior: str
    raw_content: str


def validate_fanin(tree: TagNode, *, raw_content: str) -> FanInEntry:
    """Validate a parsed ``<fanin>`` tree and return its entry.

    Grammar:

    * ``tree.tag`` must be exactly ``"fanin"``.
    * Children must all be one of ``<summary>`` /
      ``<exposed-surface>`` / ``<realized-behavior>``; unknown
      tags are rejected.
    * All three sections are **required**, exactly one of each.
    * Children must appear in the fixed order
      ``<summary>`` → ``<exposed-surface>`` →
      ``<realized-behavior>``.
    * Each section must be non-empty — an empty section is a
      structural error because it signals the LLM skipped the
      slot. Contents are opaque (the validator does not parse
      nested structure).

    ``raw_content`` is the original full string the tree was
    parsed from; the validator stores a reference to it on the
    returned entry so the caller can persist it verbatim.

    Returns a single :class:`FanInEntry`. Raises
    :class:`ValidationError` on the first problem found.
    """
    if tree.tag != "fanin":
        raise ValidationError(
            f"Expected root tag <fanin>, got <{tree.tag}>. "
            "Wrap the fan-in content in a single "
            "<fanin>...</fanin> block."
        )

    for child in tree.children:
        if child.tag not in _FANIN_ALLOWED_CHILDREN:
            raise ValidationError(
                f"<fanin> contains an unexpected child "
                f"<{child.tag}>. Allowed children are: "
                f"{sorted(_FANIN_ALLOWED_CHILDREN)}."
            )

    seen: dict[str, TagNode] = {}
    for child in tree.children:
        if child.tag in seen:
            raise ValidationError(
                f"<fanin> has more than one <{child.tag}> child; "
                "exactly one of each section is required."
            )
        seen[child.tag] = child

    for required in _FANIN_REQUIRED_ORDER:
        if required not in seen:
            raise ValidationError(
                f"<fanin> is missing the required <{required}> "
                "child. All three sections (<summary>, "
                "<exposed-surface>, <realized-behavior>) must be "
                "present."
            )

    actual_order = [c.tag for c in tree.children if c.tag in _FANIN_REQUIRED_ORDER]
    expected_order = list(_FANIN_REQUIRED_ORDER)
    if actual_order != expected_order:
        raise ValidationError(
            "<fanin> children are not in the required order. "
            f"Expected: {expected_order}. Got: {actual_order}. "
            "Reorder to <summary> → <exposed-surface> → "
            "<realized-behavior>."
        )

    sections: dict[str, str] = {}
    for name in _FANIN_REQUIRED_ORDER:
        body = _collect_implementation_section_text(seen[name])
        if not body:
            raise ValidationError(
                f"<fanin> <{name}> is empty. Every section must carry non-empty prose."
            )
        sections[name] = body

    return FanInEntry(
        summary=sections["summary"],
        exposed_surface=sections["exposed-surface"],
        realized_behavior=sections["realized-behavior"],
        raw_content=raw_content,
    )


def parse_and_validate_fanin(raw: str) -> FanInEntry:
    """Convenience helper: parse ``raw`` and validate in one call."""
    tree = extract_tag_tree(raw, "fanin")
    return validate_fanin(tree, raw_content=raw)
