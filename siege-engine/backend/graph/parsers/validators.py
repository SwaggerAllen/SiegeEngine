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
    the responsibility's role and scope. ``covers`` is the set of
    feature IDs this responsibility serves — at least one, drawn
    from a closed set of known features (the validator checks
    membership against a caller-supplied allowlist). All strings
    are non-empty and already whitespace-stripped at their outer
    edges.
    """

    name: str
    intent: str
    covers: tuple[str, ...]


_REQUIREMENTS_ALLOWED_CHILDREN = {"responsibility"}
_RESPONSIBILITY_ALLOWED_CHILDREN = {"name", "intent", "covers"}
_COVERS_ALLOWED_CHILDREN = {"feat"}


def validate_requirements(tree: TagNode, *, known_feature_ids: set[str]) -> list[Responsibility]:
    """Validate a parsed ``<requirements>`` tree and return its entries.

    Shape:

    * ``tree.tag`` must be exactly ``"requirements"``.
    * ``<requirements>`` contains one or more ``<responsibility>``
      entries. No other tags at this level.
    * Each ``<responsibility>`` contains exactly one ``<name>``,
      exactly one ``<intent>``, and exactly one ``<covers>``. No
      other tags inside.
    * Each ``<covers>`` contains one or more ``<feat id="..."/>``
      children. The ``id`` must match a known feature from
      ``known_feature_ids``. Unknown / missing IDs are parse
      errors that feed the retry loop.
    * **Coverage requirement:** every feature in
      ``known_feature_ids`` must appear in at least one
      ``<covers>`` block across the full validated set. Missing
      coverage is a parse error.

    Parallel shape to :func:`validate_features`: same general
    layout (one root, a flat list of structured children, each
    child has a name + intent), different tag vocabulary. The
    ``<covers>`` requirement is what distinguishes it from its
    feature-expansion cousin: the many-to-many edges emitted on
    approval come from parsing these IDs, so ID validity is
    enforced here rather than at mint time.
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

    # Coverage check: every known feature must be covered by at
    # least one responsibility. Collect all the covered IDs across
    # the full output and diff against the known set.
    covered: set[str] = set()
    for resp in result:
        covered.update(resp.covers)
    missing = sorted(known_feature_ids - covered)
    if missing:
        raise ValidationError(
            "<requirements> block does not cover every feature. "
            f"The following feature IDs are not listed in any <covers> block: "
            f"{', '.join(missing)}. Every feature must be implicated by "
            "at least one responsibility."
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
                "Only <name>, <intent>, and <covers> are allowed inside a <responsibility>."
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

    covers_children = node.find_all("covers")
    if len(covers_children) == 0:
        raise ValidationError(
            f"{pos} is missing a <covers> child. Every responsibility "
            "must have exactly one <covers> block listing at least one "
            '<feat id="feat_..."/> child identifying the feature IDs '
            "it serves."
        )
    if len(covers_children) > 1:
        raise ValidationError(
            f"{pos} has {len(covers_children)} <covers> children; exactly one is required."
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

    covers = _validate_covers(covers_children[0], pos, known_feature_ids=known_feature_ids)

    return Responsibility(name=name_text, intent=intent_text, covers=covers)


def _validate_covers(
    node: TagNode, parent_pos: str, *, known_feature_ids: set[str]
) -> tuple[str, ...]:
    """Validate a single ``<covers>`` block and return its feature IDs.

    ``parent_pos`` is the position marker of the enclosing
    responsibility — used in error messages so the retry prompt
    can direct the LLM to the right responsibility.
    """
    # Reject unknown children inside <covers>.
    for child in node.children:
        if child.tag not in _COVERS_ALLOWED_CHILDREN:
            raise ValidationError(
                f"{parent_pos} has a <covers> block containing an unexpected "
                f'child <{child.tag}>. Only <feat id="feat_..."/> entries '
                "are allowed inside <covers>."
            )

    feat_nodes = node.find_all("feat")
    if not feat_nodes:
        raise ValidationError(
            f"{parent_pos} has an empty <covers> block. Every responsibility "
            "must cover at least one feature — list the feature IDs via "
            '<feat id="feat_..."/> children.'
        )

    ids: list[str] = []
    seen: set[str] = set()
    for i, feat_node in enumerate(feat_nodes):
        fid = feat_node.attrs.get("id", "").strip()
        if not fid:
            raise ValidationError(
                f"{parent_pos} has a <feat> entry at <covers> position {i} "
                "with no id attribute. Every <feat> must carry an "
                'id="feat_..." attribute referencing a known feature.'
            )
        if fid in seen:
            raise ValidationError(
                f"{parent_pos} has a <feat> entry at <covers> position {i} "
                f"listing duplicate feature id {fid!r}. Each feature id may "
                "appear at most once per <covers> block."
            )
        seen.add(fid)
        if fid not in known_feature_ids:
            raise ValidationError(
                f"{parent_pos} has a <feat> entry at <covers> position {i} "
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
    """

    name: str
    trigger: str
    required_resp_id: str
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
    assigned_resp_ids: dict[str, str] = {}  # resp_id → alias that assigned it
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
        for rid in comp.resp_refs:
            if rid in assigned_resp_ids:
                raise ValidationError(
                    f"Responsibility {rid!r} is assigned to both "
                    f"{assigned_resp_ids[rid]!r} and {comp.alias!r}. Each "
                    "top-level responsibility must be assigned to exactly one "
                    "component."
                )
            assigned_resp_ids[rid] = comp.alias
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

    # Coverage check: every known top-level resp must be assigned.
    missing = sorted(known_top_level_resp_ids - set(assigned_resp_ids.keys()))
    if missing:
        raise ValidationError(
            "<sysarch> does not assign every top-level responsibility to a "
            f"component. Missing: {', '.join(missing)}. Every responsibility "
            "in the input list must appear in exactly one component's "
            "<responsibilities> block."
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
    required = (_require_one("required").text or "").strip()
    rationale = (_require_one("rationale").text or "").strip()

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
    if not required:
        raise ValidationError(
            f"{pos} has an empty <required>. It must contain a single "
            "resp_* ID referencing the responsibility that must be "
            "fulfilled at every trigger site."
        )
    if required not in known_resp_ids:
        raise ValidationError(
            f"{pos} has <required>{required}</required> referencing an "
            f"unknown responsibility. Valid IDs: "
            f"{', '.join(sorted(known_resp_ids))}."
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
        section_map["subcomponents"], known_subresp_ids=known_subresp_ids
    )

    sub_alias_set = {s.alias for s in subcomponents}
    sub_deps = _validate_arch_doc_sub_dependencies(section_map["sub-dependencies"], sub_alias_set)

    # Sub-dep cycle detection + foundation-dep enforcement — only
    # meaningful when decomposing. Un-fanned-out components have
    # no sub-alias set so the checks degenerate to no-ops.
    if subcomponents:
        _detect_dep_cycles(sub_deps, sub_alias_set)
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
    node: TagNode, *, known_subresp_ids: set[str]
) -> tuple[Subcomponent, ...]:
    """Validate ``<subcomponents>`` and return a tuple of Subcomponent.

    May legitimately be empty (un-fanned-out component). If
    populated: enforces alias syntax + uniqueness, per-subcomponent
    field completeness, exactly-one-foundation, and coverage of
    every pre-minted subresp in ``known_subresp_ids``.
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
